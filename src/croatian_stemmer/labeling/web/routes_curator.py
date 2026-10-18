"""Curator routes: corpus import and publication, exports, annotators, settings, erasures.

Every route depends on ctx.curator (the curator group/role in the access token
plus a non-blocked annotator record). Privileged actions write label_admin_event.
"""

import csv
import io
import json
from typing import Literal
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy import String, cast, func, select, update
from sqlalchemy.dialects.postgresql import insert

from ..schema import FIELDS
from .common import Caller, corpus_json, excluded_annotators, failure, scoring_params
from .licenses import allowed
from .models import AdminEvent, Annotator, Corpus, ErasureRequest, Item, ItemAudit, ItemState, Judgment, Setting
from .scheduler import audit_key, item_bits
from .requests import Candidate, ImportRequest, PublishRequest, SettingsRequest, StatusRequest


def register(app, ctx):
    session, curator = ctx.session, ctx.curator

    def event(db, caller, kind, target, details):
        db.add(AdminEvent(actor_id=caller.id, kind=kind, target=str(target), details=details))

    async def locked_corpus(db, corpus_id):
        corpus = (await db.execute(select(Corpus).where(Corpus.id == corpus_id).with_for_update())).scalar_one_or_none()
        if corpus is None:
            raise failure(404, "not_found")
        return corpus

    async def item_rows(db, corpus_id, unique):
        """Every imported item's queue row and its immutable membership row (with the
        keyed sampling bits), in the import's transaction. A re-import keeps both."""
        key = await audit_key(db)
        params = await scoring_params(db)
        ids = list(unique)
        for start in range(0, len(ids), 1000):
            chunk = ids[start:start + 1000]
            await db.execute(insert(ItemState).values([
                {"corpus_id": corpus_id, "item_id": item_id, "kind": unique[item_id].kind} for item_id in chunk])
                .on_conflict_do_nothing())
            audits = []
            for item_id in chunk:
                sample, review, rank = item_bits(key, corpus_id, item_id, params["audit_sample_rate"],
                                                 params["review_sample_rate"])
                audits.append({"corpus_id": corpus_id, "item_id": item_id, "audit_sample": sample,
                               "review_sample": review, "audit_rank": rank})
            await db.execute(insert(ItemAudit).values(audits).on_conflict_do_nothing())

    # ---- corpora -------------------------------------------------------------

    @app.post("/api/import")
    async def import_candidates(request: Request, caller: Caller = Depends(curator), db=Depends(session)):
        try:
            data = ImportRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            raise failure(422, "invalid_candidates") from exc
        first = data.candidates[0]
        unique = {row.item_id: row for row in data.candidates}
        async with db.begin():
            await db.execute(insert(Corpus).values(id=first.corpus_id, name=data.name, sha256=first.corpus_sha256,
                                                   source_uri=first.source_uri, license=first.license,
                                                   created_by=caller.id)
                             .on_conflict_do_nothing(index_elements=[Corpus.id]))
            corpus = await locked_corpus(db, first.corpus_id)
            if (corpus.sha256, corpus.source_uri, corpus.license) != (first.corpus_sha256, first.source_uri, first.license):
                raise failure(409, "corpus_provenance_conflict")
            existing = set()
            ids = list(unique)
            for start in range(0, len(ids), 1000):
                found = (await db.execute(select(Item.id, Item.payload).where(
                    Item.corpus_id == corpus.id, Item.id.in_(ids[start:start + 1000])))).all()
                for item_id, payload in found:
                    if Candidate.model_validate(payload).question != unique[item_id].question:
                        raise failure(409, "immutable_item_conflict")
                    existing.add(item_id)
            ordinal = (await db.execute(select(func.max(Item.ordinal)).where(Item.corpus_id == corpus.id))).scalar_one()
            ordinal = 0 if ordinal is None else ordinal + 1
            batch, added = [], 0
            for item_id, candidate in unique.items():
                if item_id in existing:
                    continue
                batch.append({"corpus_id": corpus.id, "id": item_id, "ordinal": ordinal + added,
                              "kind": candidate.kind, "payload": candidate.model_dump(mode="json")})
                added += 1
                if len(batch) == 1000:
                    await db.execute(insert(Item), batch)
                    batch.clear()
            if batch:
                await db.execute(insert(Item), batch)
            await item_rows(db, corpus.id, unique)
            event(db, caller, "corpus.import", corpus.id,
                  {"name": data.name, "added": added, "already_present": len(existing)})
        return {"corpus": corpus_json(corpus), "added": added, "already_present": len(existing)}

    @app.post("/api/corpora/{corpus_id}/publish")
    async def publish(corpus_id: UUID, data: PublishRequest, caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            corpus = await locked_corpus(db, corpus_id)
            permitted = allowed(corpus.license)
            if data.labels_license not in permitted:
                raise failure(409, "license_not_publishable", source_license=corpus.license, allowed=list(permitted))
            if corpus.status == "published":
                if corpus.labels_license != data.labels_license:
                    raise failure(409, "corpus_already_published", labels_license=corpus.labels_license)
                return {"corpus": corpus_json(corpus)}
            previous = corpus.status
            corpus.status, corpus.labels_license, corpus.published_at = "published", data.labels_license, func.now()
            event(db, caller, "corpus.publish", corpus.id,
                  {"from": previous, "labels_license": data.labels_license})
        await db.refresh(corpus)
        return {"corpus": corpus_json(corpus)}

    async def change_status(corpus_id, caller, db, kind, target, allowed_from):
        async with db.begin():
            corpus = await locked_corpus(db, corpus_id)
            if corpus.status not in allowed_from:
                raise failure(409, "corpus_not_published" if kind == "corpus.unpublish" else "invalid_corpus_status")
            previous, corpus.status = corpus.status, target
            event(db, caller, kind, corpus.id, {"from": previous, "to": target})
        return {"corpus": corpus_json(corpus)}

    @app.post("/api/corpora/{corpus_id}/unpublish")
    async def unpublish(corpus_id: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        return await change_status(corpus_id, caller, db, "corpus.unpublish", "draft", ("published",))

    @app.post("/api/corpora/{corpus_id}/archive")
    async def archive(corpus_id: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        return await change_status(corpus_id, caller, db, "corpus.archive", "archived", ("draft", "published"))

    # ---- exports -------------------------------------------------------------

    def export_query(corpus_id, include_excluded):
        query = (select(Item, Judgment, Annotator.status)
                 .join(Judgment, (Judgment.corpus_id == Item.corpus_id) & (Judgment.item_id == Item.id))
                 .join(Annotator, Annotator.id == Judgment.annotator_id)
                 .where(Item.corpus_id == corpus_id)
                 .order_by(Item.ordinal, Judgment.annotator_id, Judgment.revision))
        if not include_excluded:
            query = query.where(Judgment.annotator_id.not_in(excluded_annotators()))
        return query

    async def existing_corpus(db, corpus_id):
        async with db.begin():
            if (await db.execute(select(Corpus.id).where(Corpus.id == corpus_id))).scalar_one_or_none() is None:
                raise failure(404, "not_found")

    async def stream(query, line):
        # Own session: the response outlives the request's dependencies.
        async with ctx.sessions() as db:
            result = await db.stream(query.execution_options(yield_per=250))
            try:
                async for row in result:
                    yield line(*row)
            finally:
                await result.close()

    @app.get("/api/corpora/{corpus_id}/export.tsv")
    async def export_tsv(corpus_id: UUID, include_excluded: bool = False, caller: Caller = Depends(curator),
                         db=Depends(session)):
        """Schema v1 TSV over all annotators; annotator_id is the pseudonymous uuid."""
        await existing_corpus(db, corpus_id)
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=FIELDS, delimiter="\t", lineterminator="\n")

        def take():
            value = buffer.getvalue().encode("utf-8")
            buffer.seek(0)
            buffer.truncate(0)
            return value

        def line(item, judgment, _status):
            writer.writerow(Candidate.model_validate(item.payload).annotation(
                owner=str(judgment.annotator_id), revision=judgment.revision, answer=judgment.answer,
                lemma=judgment.lemma, irregular=judgment.irregular, annotation_id=judgment.id,
                annotated_at=judgment.created_at).row())
            return take()

        async def rows():
            writer.writeheader()
            yield take()
            async for chunk in stream(export_query(corpus_id, include_excluded), line):
                yield chunk

        return StreamingResponse(rows(), media_type="text/tab-separated-values; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="labels-{corpus_id}.tsv"'})

    @app.get("/api/corpora/{corpus_id}/export.jsonl")
    async def export_jsonl(corpus_id: UUID, include_excluded: bool = False, caller: Caller = Depends(curator),
                           db=Depends(session)):
        """Every judgment column (elapsed_ms is behavioural: curator only) plus the candidate."""
        await existing_corpus(db, corpus_id)
        async with db.begin():
            excluded = set((await db.execute(excluded_annotators())).scalars().all())

        def line(item, judgment, status):
            return (json.dumps({
                "id": str(judgment.id), "corpus_id": str(judgment.corpus_id), "item_id": str(judgment.item_id),
                "annotator_id": str(judgment.annotator_id), "revision": judgment.revision,
                "answer": judgment.answer, "lemma": judgment.lemma, "irregular": judgment.irregular,
                "item_revision": judgment.item_revision, "client_version": judgment.client_version,
                "source": judgment.source, "elapsed_ms": judgment.elapsed_ms,
                "created_at": judgment.created_at.isoformat(), "annotator_status": status,
                "excluded": judgment.annotator_id in excluded, "candidate": item.payload},
                ensure_ascii=False) + "\n").encode("utf-8")

        return StreamingResponse(stream(export_query(corpus_id, include_excluded), line),
                                 media_type="application/x-ndjson; charset=utf-8",
                                 headers={"Content-Disposition": f'attachment; filename="judgments-{corpus_id}.jsonl"'})

    # ---- annotators ----------------------------------------------------------

    @app.get("/api/admin/annotators")
    async def annotators(status: Literal["active", "quarantined", "blocked", "erased"] | None = None,
                         offset: int = Query(0, ge=0, le=2**31 - 1), caller: Caller = Depends(curator),
                         db=Depends(session)):
        counts = (select(Judgment.annotator_id, func.count().label("judgments"),
                         func.count(func.distinct(Judgment.item_id)).label("item_count"))
                  .group_by(Judgment.annotator_id).subquery())
        reason = (select(AdminEvent.details["reason"].astext)
                  .where(AdminEvent.kind == "annotator.status", AdminEvent.target == cast(Annotator.id, String))
                  .order_by(AdminEvent.id.desc()).limit(1).scalar_subquery())
        query = (select(Annotator, func.coalesce(counts.c.judgments, 0), func.coalesce(counts.c.item_count, 0), reason)
                 .outerjoin(counts, counts.c.annotator_id == Annotator.id))
        if status:
            query = query.where(Annotator.status == status)
        async with db.begin():
            rows = (await db.execute(query.order_by(Annotator.created_at.desc(), Annotator.id.desc()).offset(offset).limit(101))).all()
        return {"items": [{"id": str(a.id), "email": a.email, "email_verified": a.email_verified, "status": a.status,
                           "created_at": a.created_at.isoformat(), "last_seen_at": a.last_seen_at.isoformat(),
                           "counts": {"judgments": judgments, "items": items}, "status_reason": reason}
                          for a, judgments, items, reason in rows[:100]],
                "next_offset": offset + 100 if len(rows) > 100 else None}

    @app.put("/api/admin/annotators/{annotator_id}/status")
    async def annotator_status(annotator_id: UUID, data: StatusRequest, caller: Caller = Depends(curator),
                               db=Depends(session)):
        if annotator_id == caller.id:
            raise failure(409, "own_status_change")
        async with db.begin():
            person = (await db.execute(select(Annotator).where(Annotator.id == annotator_id).with_for_update())).scalar_one_or_none()
            if person is None:
                raise failure(404, "not_found")
            if person.status == "erased":
                # Erasure is the data subject's action and cannot be undone or overridden.
                raise failure(409, "annotator_erased")
            previous, person.status = person.status, data.status
            event(db, caller, "annotator.status", person.id, {"from": previous, "to": data.status, "reason": data.reason})
        return {"id": str(annotator_id), "status": data.status}

    # ---- settings ------------------------------------------------------------

    @app.get("/api/admin/settings")
    async def get_settings(caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            value = (await db.execute(select(Setting.value).where(Setting.key == "accepting_judgments"))).scalar_one_or_none()
        return {"accepting_judgments": value is None or value is True, "read_only": ctx.settings.read_only}

    @app.put("/api/admin/settings")
    async def put_settings(data: SettingsRequest, caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            await db.execute(insert(Setting).values(key="accepting_judgments", value=data.accepting_judgments,
                                                    updated_at=func.now(), updated_by=caller.id)
                             .on_conflict_do_update(index_elements=[Setting.key],
                                                    set_={"value": data.accepting_judgments,
                                                          "updated_at": func.now(), "updated_by": caller.id}))
            event(db, caller, "setting.update", "accepting_judgments", {"value": data.accepting_judgments})
        ctx.forget_settings()
        return {"accepting_judgments": data.accepting_judgments, "read_only": ctx.settings.read_only}

    # ---- erasures ------------------------------------------------------------

    @app.get("/api/admin/erasures")
    async def erasures(pending: bool = True, caller: Caller = Depends(curator), db=Depends(session)):
        query = (select(ErasureRequest, AdminEvent.details, func.now() - ErasureRequest.requested_at)
                 .outerjoin(AdminEvent, (AdminEvent.kind == "erasure.requested")
                            & (AdminEvent.target == cast(ErasureRequest.annotator_id, String))))
        if pending:
            query = query.where(ErasureRequest.keycloak_deleted_at.is_(None))
        async with db.begin():
            rows = (await db.execute(query.order_by(ErasureRequest.requested_at).limit(500))).all()
        return {"items": [{"id": e.id, "annotator_id": str(e.annotator_id), "requested_at": e.requested_at.isoformat(),
                           "age_days": age.days,
                           "keycloak_deleted_at": e.keycloak_deleted_at.isoformat() if e.keycloak_deleted_at else None,
                           # The Keycloak user (id) the curator must delete; gone once completed.
                           "keycloak_user_id": (details or {}).get("keycloak_user_id"),
                           "reason": (details or {}).get("reason")} for e, details, age in rows]}

    @app.post("/api/admin/erasures/{erasure_id}/complete")
    async def complete_erasure(erasure_id: int, caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            request = (await db.execute(select(ErasureRequest).where(ErasureRequest.id == erasure_id)
                                        .with_for_update())).scalar_one_or_none()
            if request is None:
                raise failure(404, "not_found")
            if request.keycloak_deleted_at is not None:
                raise failure(409, "erasure_not_pending")
            request.keycloak_deleted_at, request.subject_sha256 = func.now(), None
            # The one sanctioned UPDATE of the journal (the trigger allows only this).
            await db.execute(update(AdminEvent).where(AdminEvent.kind == "erasure.requested",
                                                      AdminEvent.target == str(request.annotator_id))
                             .values(details={}))
            event(db, caller, "erasure.keycloak_deleted", request.annotator_id, {"erasure_request_id": request.id})
        return {"id": erasure_id, "completed": True}

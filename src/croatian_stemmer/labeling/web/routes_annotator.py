"""Annotator routes: own account and data-subject rights, corpora, queue, answers.

Nothing here returns another annotator's answers or identity; vote counts appear
only as corpus-level totals.
"""

import hashlib
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, case, delete, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from .common import Caller, corpus_json, definite_votes, failure, judgment_json, visible_corpus
from .models import AdminEvent, Annotator, Assignment, Consent, Corpus, ErasureRequest, Item, Judgment
from .requests import AnswerRequest, Candidate, ConsentRequest, EraseRequest

KINDS = ("pair", "lemma", "stem")
Kind = Literal["pair", "lemma", "stem"]
# An item shown and neither answered nor skipped-and-returned comes back after this.
RESHOW = text("now() - interval '30 minutes'")


def _mine(caller):
    """Join condition: the caller's assignment for an Item row."""
    return and_(Assignment.annotator_id == caller.id, Assignment.corpus_id == Item.corpus_id,
                Assignment.item_id == Item.id)


def _my_latest(caller):
    """Join condition: the caller's latest judgment, via the assignment's revision."""
    return and_(Judgment.annotator_id == caller.id, Judgment.corpus_id == Assignment.corpus_id,
                Judgment.item_id == Assignment.item_id, Judgment.revision == Assignment.current_revision)


def _question(item, assignment, judgment):
    return {"candidate": item.payload, "ordinal": item.ordinal, "status": item.status,
            "assignment": {"current_revision": assignment.current_revision if assignment else 0},
            "judgment": judgment_json(judgment)}


def register(app, ctx):
    settings, limiter = ctx.settings, ctx.limiter
    session, annotator_any, annotator, consented = ctx.session, ctx.annotator_any, ctx.annotator, ctx.consented

    # ---- own account -------------------------------------------------------

    @app.get("/api/me")
    async def me(caller: Caller = Depends(annotator_any), db=Depends(session)):
        async with db.begin():
            consents = (await db.execute(select(Consent).where(Consent.annotator_id == caller.id)
                                         .order_by(Consent.accepted_at, Consent.id))).scalars().all()
            judgments = (await db.execute(select(func.count()).select_from(Judgment)
                                          .where(Judgment.annotator_id == caller.id))).scalar_one()
            items = (await db.execute(select(func.count()).select_from(Assignment).where(
                Assignment.annotator_id == caller.id, Assignment.current_revision > 0))).scalar_one()
        required = {"privacy": settings.privacy_version, "terms": settings.terms_version}
        latest = {"privacy": None, "terms": None}
        for row in consents:
            latest[row.document] = row.version
        accepted = {(row.document, row.version) for row in consents}
        return {"annotator_id": str(caller.id), "status": caller.status, "curator": caller.curator,
                "consent": latest, "required": required,
                "consented": all((doc, version) in accepted for doc, version in required.items()),
                "consents": [{"document": row.document, "version": row.version, "locale": row.locale,
                              "accepted_at": row.accepted_at.isoformat()} for row in consents],
                "counts": {"judgments": judgments, "items_labelled": items}}

    @app.post("/api/me/consent")
    async def consent(data: ConsentRequest, caller: Caller = Depends(annotator), db=Depends(session)):
        limiter.take("account", caller.id)
        required = {"privacy": settings.privacy_version, "terms": settings.terms_version}
        if (data.privacy_version, data.terms_version) != (required["privacy"], required["terms"]):
            raise failure(409, "consent_version_mismatch", required=required)
        async with db.begin():
            await db.execute(insert(Consent).values([
                {"annotator_id": caller.id, "document": document, "version": version, "locale": data.locale,
                 "age_confirmed": data.age_confirmed, "ui_version": data.ui_version}
                for document, version in required.items()]).on_conflict_do_nothing(
                index_elements=[Consent.annotator_id, Consent.document, Consent.version]))
        return {"consented": True, "required": required}

    @app.get("/api/me/export.json")
    async def export_mine(caller: Caller = Depends(annotator_any), db=Depends(session)):
        limiter.take("account", caller.id)
        async with db.begin():
            person = (await db.execute(select(Annotator).where(Annotator.id == caller.id))).scalar_one()
            consents = (await db.execute(select(Consent).where(Consent.annotator_id == caller.id)
                                         .order_by(Consent.id))).scalars().all()
            judgments = (await db.execute(select(Judgment).where(Judgment.annotator_id == caller.id)
                                          .order_by(Judgment.created_at, Judgment.id))).scalars().all()
            assignments = (await db.execute(select(Assignment).where(Assignment.annotator_id == caller.id)
                                            .order_by(Assignment.first_shown_at))).scalars().all()
            erasures = (await db.execute(select(ErasureRequest).where(ErasureRequest.annotator_id == caller.id)
                                         .order_by(ErasureRequest.id))).scalars().all()
        iso = lambda value: value.isoformat() if value else None
        body = {
            "format": "croatian-stemmer-labeling-personal-export/1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "annotator": {"annotator_id": str(person.id), "email": person.email,
                          "email_verified": person.email_verified, "status": person.status,
                          "created_at": iso(person.created_at), "last_seen_at": iso(person.last_seen_at),
                          "erased_at": iso(person.erased_at)},
            "consents": [{"document": c.document, "version": c.version, "locale": c.locale,
                          "age_confirmed": c.age_confirmed, "ui_version": c.ui_version,
                          "accepted_at": iso(c.accepted_at)} for c in consents],
            "judgments": [{"id": str(j.id), "corpus_id": str(j.corpus_id), "item_id": str(j.item_id),
                           "revision": j.revision, "answer": j.answer, "lemma": j.lemma,
                           "irregular": j.irregular, "item_revision": j.item_revision,
                           "client_version": j.client_version, "source": j.source,
                           "elapsed_ms": j.elapsed_ms, "created_at": iso(j.created_at)} for j in judgments],
            "assignments": [{"corpus_id": str(a.corpus_id), "item_id": str(a.item_id),
                             "first_shown_at": iso(a.first_shown_at), "last_shown_at": iso(a.last_shown_at),
                             "shown_count": a.shown_count, "current_revision": a.current_revision,
                             "last_answer_at": iso(a.last_answer_at)} for a in assignments],
            "erasure_requests": [{"id": e.id, "requested_at": iso(e.requested_at),
                                  "app_erased_at": iso(e.app_erased_at),
                                  "keycloak_deleted_at": iso(e.keycloak_deleted_at)} for e in erasures],
        }
        return JSONResponse(body, headers={"Content-Disposition":
                                           f'attachment; filename="my-labeling-data-{caller.id}.json"'})

    @app.post("/api/me/erase")
    async def erase(data: EraseRequest, caller: Caller = Depends(annotator_any), db=Depends(session)):
        limiter.take("account", caller.id)
        principal = caller.principal
        async with db.begin():
            person = (await db.execute(select(Annotator).where(Annotator.id == caller.id).with_for_update())).scalar_one()
            if person.status == "erased":
                raise failure(409, "erasure_pending")
            await db.execute(insert(ErasureRequest).values(
                annotator_id=caller.id, subject_sha256=hashlib.sha256(principal.subject.encode()).hexdigest(),
                requested_at=func.now(), app_erased_at=func.now()))
            # What the curator needs to find the Keycloak user; deleted on completion.
            db.add(AdminEvent(actor_id=caller.id, kind="erasure.requested", target=str(caller.id),
                              details={"preferred_username": principal.username,
                                       "email": principal.email or person.email}))
            await db.execute(update(Annotator).where(Annotator.id == caller.id).values(
                subject=None, email=None, email_verified=False, status="erased", erased_at=func.now()))
            await db.execute(delete(Assignment).where(Assignment.annotator_id == caller.id))
            await db.execute(update(Judgment).where(Judgment.annotator_id == caller.id,
                                                    Judgment.elapsed_ms.is_not(None)).values(elapsed_ms=None))
        return {"erased": True, "keycloak_deletion": "pending"}

    # ---- corpora and labeling ----------------------------------------------

    async def kind_counts(db, corpus_ids):
        counts = {cid: {kind: 0 for kind in KINDS} for cid in corpus_ids}
        if corpus_ids:
            rows = await db.execute(select(Item.corpus_id, Item.kind, func.count()).where(
                Item.corpus_id.in_(corpus_ids), Item.status == "active").group_by(Item.corpus_id, Item.kind))
            for cid, kind, count in rows:
                counts[cid][kind] = count
        return counts

    @app.get("/api/corpora")
    async def corpora(offset: int = Query(0, ge=0, le=2**31 - 1), caller: Caller = Depends(annotator),
                      db=Depends(session)):
        query = select(Corpus)
        if not caller.curator:
            query = query.where(Corpus.status == "published")
        async with db.begin():
            rows = (await db.execute(query.order_by(Corpus.created_at, Corpus.id).offset(offset).limit(101))).scalars().all()
            counts = await kind_counts(db, [row.id for row in rows[:100]])
        return {"items": [corpus_json(row, counts[row.id]) for row in rows[:100]],
                "next_offset": offset + 100 if len(rows) > 100 else None}

    @app.get("/api/corpora/{corpus_id}/progress")
    async def progress(corpus_id: UUID, caller: Caller = Depends(annotator), db=Depends(session)):
        async with db.begin():
            await visible_corpus(db, caller, corpus_id)
            votes = definite_votes(corpus_id)
            rows = (await db.execute(
                select(Item.kind, func.count(Item.id),
                       func.count(Judgment.id),
                       func.count(Judgment.id).filter(Judgment.answer == "unsure"),
                       func.count(votes.c.item_id).filter(votes.c.n > 0))
                .outerjoin(Assignment, _mine(caller)).outerjoin(Judgment, _my_latest(caller))
                .outerjoin(votes, votes.c.item_id == Item.id)
                .where(Item.corpus_id == corpus_id, Item.status == "active").group_by(Item.kind))).all()
            events = (await db.execute(select(func.count()).select_from(Judgment).where(
                Judgment.annotator_id == caller.id, Judgment.corpus_id == corpus_id))).scalar_one()
        kinds = {kind: {"total": 0, "reviewed": 0, "unsure": 0, "definite": 0, "items_with_votes": 0} for kind in KINDS}
        for kind, total, reviewed, unsure, voted in rows:
            kinds[kind] = {"total": total, "reviewed": reviewed, "unsure": unsure,
                           "definite": reviewed - unsure, "items_with_votes": voted}
        return {"kinds": kinds, "revision_events": events}

    @app.get("/api/corpora/{corpus_id}/next")
    async def next_item(corpus_id: UUID, kind: Kind = "pair", caller: Caller = Depends(consented),
                        db=Depends(session)):
        limiter.take("read", caller.id)
        async with db.begin():
            await visible_corpus(db, caller, corpus_id, labeling=True)
            votes = definite_votes(corpus_id)
            count = func.coalesce(votes.c.n, 0)
            item = (await db.execute(
                select(Item).outerjoin(votes, votes.c.item_id == Item.id).outerjoin(Assignment, _mine(caller))
                .where(Item.corpus_id == corpus_id, Item.kind == kind, Item.status == "active",
                       or_(Assignment.annotator_id.is_(None),
                           and_(Assignment.current_revision == 0, Assignment.last_shown_at < RESHOW)),
                       count < settings.target_votes)
                .order_by(count, Item.ordinal).limit(1))).scalar_one_or_none()
            if item is None:
                return {"item": None}
            now = func.now()
            assignment = (await db.execute(insert(Assignment).values(
                annotator_id=caller.id, corpus_id=corpus_id, item_id=item.id, first_shown_at=now,
                last_shown_at=now, shown_count=1).on_conflict_do_update(
                index_elements=[Assignment.annotator_id, Assignment.corpus_id, Assignment.item_id],
                set_={"last_shown_at": now, "shown_count": Assignment.shown_count + 1})
                .returning(Assignment))).scalar_one()
        return {"item": _question(item, assignment, None)}

    @app.get("/api/corpora/{corpus_id}/items")
    async def my_items(corpus_id: UUID, kind: Kind = "pair",
                       state: Literal["mine_labelled", "mine_unsure"] = "mine_labelled",
                       after: int = Query(-1, ge=-1, le=2**31 - 1), limit: int = Query(1, ge=1, le=50),
                       caller: Caller = Depends(consented), db=Depends(session)):
        limiter.take("read", caller.id)
        unsure = Judgment.answer == "unsure"
        async with db.begin():
            await visible_corpus(db, caller, corpus_id, labeling=True)
            rows = (await db.execute(
                select(Item, Assignment, Judgment).join(Assignment, _mine(caller)).join(Judgment, _my_latest(caller))
                .where(Item.corpus_id == corpus_id, Item.kind == kind, Item.status == "active",
                       Item.ordinal > after, unsure if state == "mine_unsure" else ~unsure)
                .order_by(Item.ordinal).limit(limit + 1))).all()
        return {"items": [_question(*row) for row in rows[:limit]],
                "next_after": rows[limit - 1][0].ordinal if len(rows) > limit else None}

    @app.get("/api/corpora/{corpus_id}/items/{item_id}")
    async def item_detail(corpus_id: UUID, item_id: UUID, caller: Caller = Depends(consented),
                          db=Depends(session)):
        async with db.begin():
            await visible_corpus(db, caller, corpus_id, labeling=True)
            row = (await db.execute(
                select(Item, Assignment, Judgment).outerjoin(Assignment, _mine(caller))
                .outerjoin(Judgment, _my_latest(caller))
                .where(Item.corpus_id == corpus_id, Item.id == item_id))).one_or_none()
        if row is None:
            raise failure(404, "not_found")
        return _question(*row)

    @app.post("/api/corpora/{corpus_id}/items/{item_id}/answer")
    async def answer(corpus_id: UUID, item_id: UUID, data: AnswerRequest,
                     caller: Caller = Depends(consented), db=Depends(session)):
        if not await ctx.accepting_judgments(db):
            raise failure(503, "judgments_paused")
        limiter.take("answer", caller.id)
        async with db.begin():
            today = (await db.execute(select(func.count()).select_from(Judgment).where(
                Judgment.annotator_id == caller.id,
                Judgment.created_at > text("now() - interval '24 hours'")))).scalar_one()
        if today >= settings.daily_cap:
            raise failure(429, "daily_cap_reached")
        try:
            async with db.begin():
                item = (await db.execute(select(Item).where(Item.corpus_id == corpus_id, Item.id == item_id))).scalar_one_or_none()
                if item is None:
                    raise failure(404, "not_found")
                await visible_corpus(db, caller, corpus_id, labeling=True)
                # Answering an item that was never fetched is allowed and recorded as unseen.
                now = datetime.now(timezone.utc)
                await db.execute(insert(Assignment).values(
                    annotator_id=caller.id, corpus_id=corpus_id, item_id=item_id, first_shown_at=now,
                    last_shown_at=now, shown_count=0).on_conflict_do_nothing())
                assignment = (await db.execute(select(Assignment).where(
                    Assignment.annotator_id == caller.id, Assignment.corpus_id == corpus_id,
                    Assignment.item_id == item_id).with_for_update())).scalar_one()
                old = (await db.execute(select(Judgment).where(Judgment.id == data.request_id))).scalar_one_or_none()
                if old is not None:
                    if (old.annotator_id, old.corpus_id, old.item_id, old.revision - 1, old.answer, old.lemma,
                            old.irregular) != (caller.id, corpus_id, item_id, data.base_revision, data.answer,
                                               data.lemma, data.irregular):
                        raise failure(409, "request_id_conflict")
                    return {"annotation_id": str(old.id), "revision": old.revision,
                            "current_revision": assignment.current_revision}
                if item.status == "retired":
                    raise failure(409, "item_retired")
                if assignment.current_revision != data.base_revision:
                    raise failure(409, "revision_conflict", current_revision=assignment.current_revision)
                revision = assignment.current_revision + 1
                try:
                    Candidate.model_validate(item.payload).annotation(
                        owner=str(caller.id), revision=revision, answer=data.answer, lemma=data.lemma,
                        irregular=data.irregular, annotation_id=data.request_id, annotated_at=now).validate()
                except ValueError as exc:
                    raise failure(422, "invalid_judgment") from exc
                db.add(Judgment(id=data.request_id, corpus_id=corpus_id, item_id=item_id, annotator_id=caller.id,
                                revision=revision, answer=data.answer, lemma=data.lemma, irregular=data.irregular,
                                item_revision=item.revision, client_version=data.client_version, source="web",
                                elapsed_ms=data.elapsed_ms, created_at=now))
                assignment.current_revision, assignment.last_answer_at = revision, now
            return {"annotation_id": str(data.request_id), "revision": revision, "current_revision": revision}
        except IntegrityError as exc:
            raise failure(409, "request_id_conflict") from exc

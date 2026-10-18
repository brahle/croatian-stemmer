"""Annotator routes: own account and data-subject rights, corpora, queue, answers.

Nothing here returns another annotator's answers or identity; vote counts appear
only as corpus-level totals.
"""

from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from fastapi import Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, literal, or_, select, text, true, tuple_
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError

from ..scoring import corpus_params
from . import scheduler
from . import trust_view
from .common import Caller, corpus_json, definite_votes, failure, judgment_json, trust_event, visible_corpus
from .config import MINIMUM_AGE
from .erasure import erase_profile, still_present
from .scoring_run import moderation_tx
from .models import Annotator, Assignment, Consent, Corpus, ErasureRequest, Gold, Item, ItemAudit, ItemState, Judgment
from .scheduler import candidate_view
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


def _question(item, assignment, judgment, presentation=None):
    """The single serialiser of an item for annotators. It never joins gold: a known-answer
    item and any other item differ only in the payload and presentation (4.3.6). No positional
    field (the import ordinal) is sent: items imported together, such as a gold reserve, would
    be recognisable by it."""
    presentation = presentation or (assignment.presentation if assignment and assignment.presentation else "shown")
    return {"candidate": candidate_view(item.payload, presentation), "status": item.status,
            "presentation": presentation,
            "assignment": {"current_revision": assignment.current_revision if assignment else 0},
            "judgment": judgment_json(judgment)}


CURSOR = r"^([0-9]{1,20}~[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?$"


def _cursor(assignment):
    """An opaque position in the caller's own list: when the item was first shown to them."""
    shown = assignment.first_shown_at
    micros = (shown - datetime(1970, 1, 1, tzinfo=timezone.utc)) // timedelta(microseconds=1)
    return f"{micros}~{assignment.item_id}"


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
            required = settings.required_documents
            latest = {document: None for document in required}
            for row in consents:
                latest[row.document] = row.version
            reason = await trust_view.block_reason(db, caller.id, caller.status)
            anchor, _ = await scheduler.standing(db, caller.id, "pair")
        # A quarantine is silent (4.8.2): the person's view says `active`.
        return {"annotator_id": str(caller.id), "status": trust_view.shown_status(caller.status),
                "status_reason": reason, "trust_url": "/api/me/trust", "curator": caller.curator, "anchor": anchor,
                "consent": latest, "required": required,
                "consented": ctx.consent_complete((row.document, row.version, row.age_threshold) for row in consents),
                "consents": [{"document": row.document, "version": row.version, "locale": row.locale,
                              "accepted_at": row.accepted_at.isoformat()} for row in consents],
                "counts": {"judgments": judgments, "items_labelled": items}}

    @app.post("/api/me/consent")
    async def consent(data: ConsentRequest, caller: Caller = Depends(annotator), db=Depends(session)):
        limiter.take("account", caller.id)
        required = settings.required_documents
        if (data.privacy_version, data.terms_version, data.participation_version) != tuple(required.values()):
            raise failure(409, "consent_version_mismatch", required=required)
        async with db.begin():
            # Holds off a concurrent erasure (e.g. the 30-day expiry) until the consent is in.
            await still_present(db, caller)
            await db.execute(insert(Consent).values([
                {"annotator_id": caller.id, "document": document, "version": version, "locale": data.locale,
                 "age_confirmed": data.age_confirmed, "age_threshold": MINIMUM_AGE, "ui_version": data.ui_version}
                for document, version in required.items()]).on_conflict_do_nothing(
                index_elements=[Consent.annotator_id, Consent.document, Consent.version]))
        return {"consented": True, "required": required}

    @app.get("/api/me/trust")
    async def my_trust(lang: Literal["hr", "en"] = "hr", caller: Caller = Depends(annotator_any), db=Depends(session)):
        """The trust card: tier and band per kind, rounded counts. Complete data are in the export."""
        limiter.take("read", caller.id)
        async with db.begin():
            anchor, _ = await scheduler.standing(db, caller.id, "pair")
            return await trust_view.card(db, caller, anchor, lang)

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
            trust = await trust_view.export_section(db, caller.id)
            checked = await trust_view.checked_items(db, caller.id)
        if checked:
            # Answers on known-answer items no longer in use are marked; the marks disclose those
            # answers, so later revisions never count as skill on them (4.3.5).
            await disclose(db, checked)
        iso = lambda value: value.isoformat() if value else None
        body = {
            "format": "croatian-stemmer-labeling-personal-export/1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "annotator": {"annotator_id": str(person.id), "email": person.email,
                          "email_verified": person.email_verified, "status": person.status,
                          "created_at": iso(person.created_at), "last_seen_at": iso(person.last_seen_at),
                          "erased_at": iso(person.erased_at)},
            "consents": [{"document": c.document, "version": c.version, "locale": c.locale,
                          "age_confirmed": c.age_confirmed, "age_threshold": c.age_threshold,
                          "ui_version": c.ui_version,
                          "accepted_at": iso(c.accepted_at)} for c in consents],
            "judgments": [{"id": str(j.id), "corpus_id": str(j.corpus_id), "item_id": str(j.item_id),
                           "revision": j.revision, "answer": j.answer, "lemma": j.lemma,
                           "irregular": j.irregular, "item_revision": j.item_revision,
                           "client_version": j.client_version, "source": j.source,
                           "elapsed_ms": j.elapsed_ms, "created_at": iso(j.created_at),
                           "presentation": j.presentation or "shown",
                           "checked_against_known_answer": (j.corpus_id, j.item_id) in checked} for j in judgments],
            "assignments": [{"corpus_id": str(a.corpus_id), "item_id": str(a.item_id),
                             "first_shown_at": iso(a.first_shown_at), "last_shown_at": iso(a.last_shown_at),
                             "shown_count": a.shown_count, "current_revision": a.current_revision,
                             "last_answer_at": iso(a.last_answer_at), "presentation": a.presentation or "shown"}
                            for a in assignments],
            "erasure_requests": [{"id": e.id, "requested_at": iso(e.requested_at),
                                  "app_erased_at": iso(e.app_erased_at),
                                  "keycloak_deleted_at": iso(e.keycloak_deleted_at)} for e in erasures],
            "trust": trust,
        }
        return JSONResponse(body, headers={"Content-Disposition":
                                           f'attachment; filename="my-labeling-data-{caller.id}.json"'})

    async def disclose(db, items):
        async with db.begin():
            await moderation_tx(db)
            known = {(r[0], r[1]) for r in (await db.execute(text(
                "SELECT corpus_id, item_id FROM label_trust_event WHERE kind = 'gold.disclosed'"))).all()}
            for corpus_id, item_id in sorted(items - known):
                await trust_event(db, "gold.disclosed", corpus_id=corpus_id, item_id=item_id,
                                  details={"reason": "access_export"})

    @app.post("/api/me/erase")
    async def erase(data: EraseRequest, caller: Caller = Depends(annotator_any), db=Depends(session)):
        limiter.take("account", caller.id)
        async with db.begin():
            await moderation_tx(db)
            person = (await db.execute(select(Annotator).where(Annotator.id == caller.id).with_for_update())).scalar_one()
            if person.status == "erased":
                raise failure(409, "erasure_pending")
            # The curator finds the Keycloak user by its id (the token's sub); cleared on completion.
            await erase_profile(db, person, actor_id=caller.id, details={"keycloak_user_id": person.subject})
        return {"erased": True, "keycloak_deletion": "pending"}

    # ---- corpora and labeling ----------------------------------------------

    async def kind_counts(db, corpus_ids):
        counts = {cid: {kind: 0 for kind in KINDS} for cid in corpus_ids}
        if corpus_ids:
            rows = await db.execute(select(Item.corpus_id, Item.kind, func.count()).where(
                Item.corpus_id.in_(corpus_ids), Item.status == "active", scheduler.ordinary())
                .group_by(Item.corpus_id, Item.kind))
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
                .where(Item.corpus_id == corpus_id, Item.status == "active", scheduler.ordinary())
                .group_by(Item.kind))).all()
            events = (await db.execute(select(func.count()).select_from(Judgment).where(
                Judgment.annotator_id == caller.id, Judgment.corpus_id == corpus_id))).scalar_one()
        kinds = {kind: {"total": 0, "reviewed": 0, "unsure": 0, "definite": 0, "items_with_votes": 0} for kind in KINDS}
        for kind, total, reviewed, unsure, voted in rows:
            kinds[kind] = {"total": total, "reviewed": reviewed, "unsure": unsure,
                           "definite": reviewed - unsure, "items_with_votes": voted}
        return {"kinds": kinds, "revision_events": events}

    async def serve(db, caller, corpus_ids, kind, expert_work):
        """The next item of corpus_ids (one corpus), shown (assignment upserted), as /next returns it."""
        params, key = await ctx.serving_params(db), await ctx.audit_key(db)
        if await ctx.trust_scheduling(db, corpus_ids[0]):
            chosen = await scheduler.pick(ctx, db, caller, corpus_ids, kind, expert_work)
            if chosen is None:
                return None
            item = (await db.execute(select(Item).where(Item.corpus_id == chosen.corpus_id,
                                                        Item.id == chosen.item_id))).scalar_one()
            assignment = await scheduler.show(db, key, params, caller.id, item, chosen.presentation)
            return {"item": _question(item, assignment, None), "qualification": chosen.qualification}
        # V1's coverage-first order with its target vote count, until scoring or gold exists.
        corpus_id = corpus_ids[0]
        votes = definite_votes(corpus_id)
        count = func.coalesce(votes.c.n, 0)
        item = (await db.execute(
            select(Item).outerjoin(votes, votes.c.item_id == Item.id).outerjoin(Assignment, _mine(caller))
            .where(Item.corpus_id == corpus_id, Item.kind == kind, Item.status == "active", scheduler.ordinary(),
                   or_(Assignment.annotator_id.is_(None),
                       and_(Assignment.current_revision == 0, Assignment.last_shown_at < RESHOW)),
                   count < settings.target_votes)
            .order_by(count, Item.ordinal).limit(1))).scalar_one_or_none()
        if item is None:
            return None
        assignment = await scheduler.show(db, key, params, caller.id, item)
        return {"item": _question(item, assignment, None), "qualification": None}

    @app.get("/api/corpora/{corpus_id}/next")
    async def next_item(corpus_id: UUID, kind: Kind = "pair", expert: bool = True,
                        caller: Caller = Depends(consented), db=Depends(session)):
        limiter.take("read", caller.id)
        async with db.begin():
            await still_present(db, caller)
            await visible_corpus(db, caller, corpus_id, labeling=True)
            served = await serve(db, caller, [corpus_id], kind, expert)
        return served or {"item": None, "qualification": None}

    @app.get("/api/next")
    async def next_any(kind: Kind = "pair", expert: bool = True, caller: Caller = Depends(consented),
                       db=Depends(session)):
        """Any published corpus: the one with the lowest share of resolved items of the kind
        first (ties by publication time), skipping corpora with nothing to serve."""
        limiter.take("read", caller.id)
        async with db.begin():
            await still_present(db, caller)
            corpora = (await db.execute(text("""
                SELECT c.id FROM label_corpus c
                LEFT JOIN label_item_state s ON s.corpus_id = c.id AND s.kind = :k AND NOT s.reserve
                WHERE c.status = 'published' GROUP BY c.id, c.published_at
                HAVING count(s.item_id) > 0
                ORDER BY avg(CASE WHEN s.state = 'resolved' THEN 1.0 ELSE 0.0 END), c.published_at, c.id"""),
                {"k": kind})).scalars().all()
            for corpus_id in corpora:
                served = await serve(db, caller, [corpus_id], kind, expert)
                if served:
                    return served
        return {"item": None, "qualification": None}

    @app.get("/api/corpora/{corpus_id}/items")
    async def my_items(corpus_id: UUID, kind: Kind = "pair",
                       state: Literal["mine_labelled", "mine_unsure"] = "mine_labelled",
                       after: str = Query("", max_length=80, pattern=CURSOR), limit: int = Query(1, ge=1, le=50),
                       caller: Caller = Depends(consented), db=Depends(session)):
        """The caller's own items in the order they were first shown to them. The cursor is
        that showing time and the item id, never the item's position in the corpus."""
        limiter.take("read", caller.id)
        unsure = Judgment.answer == "unsure"
        order = (Assignment.first_shown_at, Item.id)
        async with db.begin():
            await visible_corpus(db, caller, corpus_id, labeling=True)
            query = (select(Item, Assignment, Judgment).join(Assignment, _mine(caller)).join(Judgment, _my_latest(caller))
                     .where(Item.corpus_id == corpus_id, Item.kind == kind, Item.status == "active",
                            unsure if state == "mine_unsure" else ~unsure))
            if after:
                micros, _, item_id = after.partition("~")
                shown = datetime.fromtimestamp(int(micros) / 1_000_000, timezone.utc)
                query = query.where(tuple_(*order) > tuple_(literal(shown), literal(UUID(item_id))))
            rows = (await db.execute(query.order_by(*order).limit(limit + 1))).all()
        items = [{**_question(*row), "cursor": _cursor(row[1])} for row in rows[:limit]]
        return {"items": items, "next_after": items[-1]["cursor"] if len(rows) > limit else None}

    @app.get("/api/corpora/{corpus_id}/items/{item_id}")
    async def item_detail(corpus_id: UUID, item_id: UUID, caller: Caller = Depends(consented),
                          db=Depends(session)):
        async with db.begin():
            await visible_corpus(db, caller, corpus_id, labeling=True)
            row = (await db.execute(
                select(Item, Assignment, Judgment, ItemState.reserve).outerjoin(Assignment, _mine(caller))
                .outerjoin(Judgment, _my_latest(caller))
                .join(ItemState, (ItemState.corpus_id == Item.corpus_id) & (ItemState.item_id == Item.id))
                .where(Item.corpus_id == corpus_id, Item.id == item_id))).one_or_none()
            # A gold-reserve item exists for a person only once it was served to them as a check:
            # otherwise it is "not found" like an unknown id, so ids cannot be probed for membership.
            if row is None or (row.reserve and row.Assignment is None and not caller.curator):
                raise failure(404, "not_found")
            item, assignment, judgment, _ = row
            presentation = None
            if assignment is None or assignment.presentation is None:
                # Never shown to this person: the same keyed rule as a showing, so asking for
                # an item directly cannot reveal a suggestion a showing would hide.
                params, key = await ctx.serving_params(db), await ctx.audit_key(db)
                blind = scheduler.blind_by_rule(key, params, caller.id, corpus_id, item_id, item.kind)
                presentation = "blind" if blind else "shown"
        return _question(item, assignment, judgment, presentation)

    async def admission(db, caller, item):
        """(admitted, admission_group) of an answer (4.9.2). The response never says which:
        no status code distinguishes gold, capacity or quarantine."""
        state = (await db.execute(select(ItemState).where(ItemState.corpus_id == item.corpus_id,
                                                          ItemState.item_id == item.id).with_for_update())).scalar_one()
        epoch = state.epoch
        first = (await db.execute(
            select(Judgment.admitted, Judgment.admission_group).where(
                Judgment.annotator_id == caller.id, Judgment.corpus_id == item.corpus_id, Judgment.item_id == item.id,
                # Epoch 0 holds every answer, V1's (seq NULL) included, as in a run.
                true() if epoch == 0 else func.coalesce(Judgment.seq, 0) > epoch)
            .order_by(func.coalesce(Judgment.seq, 0), Judgment.revision, Judgment.id)
            .limit(1))).first()
        if first is not None:  # a revision inherits its epoch's first answer's decision
            return (True if first.admitted is None else first.admitted), first.admission_group or "low"
        anchor, tier = await scheduler.standing(db, caller.id, item.kind)
        group = "expert" if tier in ("anchor", "established") else "low"
        if caller.id not in await scheduler.eligible_now(db, [caller.id]):
            return False, group  # quarantined, or outside the profiling cohort: kept, not counted
        audit = (await db.execute(select(ItemAudit).where(ItemAudit.corpus_id == item.corpus_id,
                                                          ItemAudit.item_id == item.id))).scalar_one()
        gold = (await db.execute(select(Gold.status).where(Gold.corpus_id == item.corpus_id,
                                                           Gold.item_id == item.id))).scalar_one_or_none()
        if gold in ("active", "retired") or (anchor and (audit.audit_sample or audit.review_sample)):
            return True, group  # gold and the anchors' sampled checks are exempt from the budgets
        params = await ctx.serving_params(db)
        used = await scheduler.counted_now(db, params, item.corpus_id, item.id, epoch,
                                           audit.audit_sample or audit.review_sample, False, without=caller.id)
        caps = corpus_params(params, item.corpus_id)
        return used[group] < caps["votes_expert_cap" if group == "expert" else "votes_low_cap"], group

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
                await still_present(db, caller)
                item = (await db.execute(select(Item).where(Item.corpus_id == corpus_id, Item.id == item_id))).scalar_one_or_none()
                if item is None:
                    raise failure(404, "not_found")
                await visible_corpus(db, caller, corpus_id, labeling=True)
                now = datetime.now(timezone.utc)
                # Only an item served by /next (or the person's own earlier answer) can be answered.
                assignment = (await db.execute(select(Assignment).where(
                    Assignment.annotator_id == caller.id, Assignment.corpus_id == corpus_id,
                    Assignment.item_id == item_id).with_for_update())).scalar_one_or_none()
                if assignment is None or assignment.shown_count < 1:
                    raise failure(409, "not_assigned")
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
                admitted, group = await admission(db, caller, item)
                db.add(Judgment(id=data.request_id, corpus_id=corpus_id, item_id=item_id, annotator_id=caller.id,
                                revision=revision, answer=data.answer, lemma=data.lemma, irregular=data.irregular,
                                item_revision=item.revision, client_version=data.client_version, source="web",
                                elapsed_ms=data.elapsed_ms, created_at=now, admitted=admitted, admission_group=group,
                                presentation=assignment.presentation or "shown"))
                assignment.current_revision, assignment.last_answer_at = revision, now
            return {"annotation_id": str(data.request_id), "revision": revision, "current_revision": revision}
        except IntegrityError as exc:
            raise failure(409, "request_id_conflict") from exc

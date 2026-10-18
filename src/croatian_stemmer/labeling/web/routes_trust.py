"""Curator routes of the trust system: scoring runs and parameters, gold, the trusted
list, adjudication and reopening, dashboard views.

Every route depends on ctx.curator. Each moderation action takes the shared
moderation lock first (moderation_tx) and writes one trust event plus its mirror
update in one transaction, so a run that did not see it cannot publish over it.
"""

import json
from collections import defaultdict
from typing import Literal
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from ..scoring import (CELLS, DEFAULT_PARAMS, answer_class, krippendorff_alpha, observed_agreement, params_sha256,
                       suggested_class, validate_params)
from .common import Caller, failure, scoring_params, trust_event
from .models import (Anchor, Annotator, Corpus, Gold, Item, ItemAudit, ItemPosterior, ItemState, ScoringRun, Setting,
                     TrustedEmail, TrustEvent)
from .requests import (AdjudicateRequest, Candidate, GoldActionRequest, GoldImportRequest, ReasonRequest,
                       RedrawRequest, ReopenRequest, ScoringParamsRequest, ScoringSettingsRequest, TrustedRemoveRequest,
                       TrustedRequest, gold_answer)
from .trusted import email_digest, grant_anchor, normalized_email, revoke_anchors
from .scheduler import live_readiness
from .scoring_run import ScoringBusy, bundle, moderation_tx, run_now, stale


def run_json(run, is_stale=None, full=False):
    data = {"id": str(run.id), "status": run.status, "scoring_version": run.scoring_version,
            "params_sha256": run.params_sha256, "watermark": run.watermark, "as_of_day": run.as_of_day.isoformat(),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
            "triggered_by": str(run.triggered_by) if run.triggered_by else None,
            "n_judgments": run.n_judgments, "n_items": run.n_items, "n_annotators": run.n_annotators,
            "inputs_sha256": run.inputs_sha256, "outputs_sha256": run.outputs_sha256, "pinned": run.pinned,
            "error": run.error, "stale": is_stale}
    if full:
        data.update({"params": run.params, "calibration": run.calibration, "readiness": run.readiness,
                     "previous_run_id": str(run.previous_run_id) if run.previous_run_id else None,
                     "inputs_summary": run.inputs_summary})
    return data


def gold_agrees(item, answer, lemma):
    """Whether gold equals what the visible suggestion implies (computed from the stored
    payload, never taken from a file); None for stem."""
    view = {"kind": item.kind, "proposed_lemma": item.payload.get("proposed_lemma", ""),
            "other_proposed_lemma": item.payload.get("other_proposed_lemma", "")}
    suggestion = suggested_class(view)
    return None if suggestion is None else answer_class(item.kind, answer, lemma) == suggestion


def _diff(old, new, prefix=""):
    """The dotted paths whose values differ between two parameter sets."""
    changed = []
    for key in sorted(set(old) | set(new)):
        a, b = old.get(key), new.get(key)
        if isinstance(a, dict) and isinstance(b, dict):
            changed += _diff(a, b, f"{prefix}{key}.")
        elif a != b:
            changed.append(f"{prefix}{key}")
    return changed


def register(app, ctx):
    session, curator = ctx.session, ctx.curator

    async def event(db, caller, kind, **values):
        return await trust_event(db, kind, actor_id=caller.id, **values)

    # ---- scoring runs ----------------------------------------------------------

    @app.get("/api/admin/scoring/runs")
    async def runs(offset: int = Query(0, ge=0, le=2**31 - 1), caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            rows = (await db.execute(select(ScoringRun).order_by(ScoringRun.started_at.desc(), ScoringRun.id)
                                     .offset(offset).limit(51))).scalars().all()
            stale_flags = [await stale(db, run.watermark) if run.status == "done" else None for run in rows[:50]]
        return {"items": [run_json(run, flag) for run, flag in zip(rows[:50], stale_flags)],
                "next_offset": offset + 50 if len(rows) > 50 else None}

    async def get_run(db, run_id, lock=False):
        query = select(ScoringRun).where(ScoringRun.id == run_id)
        run = (await db.execute(query.with_for_update() if lock else query)).scalar_one_or_none()
        if run is None:
            raise failure(404, "not_found")
        return run

    @app.get("/api/admin/scoring/runs/{run_id}")
    async def one_run(run_id: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            run = await get_run(db, run_id)
            return run_json(run, await stale(db, run.watermark) if run.status == "done" else None, full=True)

    @app.post("/api/admin/scoring/run")
    async def start_run(caller: Caller = Depends(curator)):
        try:
            results = await run_now(ctx, triggered_by=caller.id)
        except ScoringBusy:
            raise failure(409, "scoring_busy") from None
        ctx.forget_settings()
        return {"runs": [{"id": str(run_id), "status": status} for run_id, status in results]}

    async def pin(run_id, caller, db, value):
        async with db.begin():
            run = await get_run(db, run_id, lock=True)
            if run.status != "done":
                raise failure(409, "run_not_done")
            if value and await stale(db, run.watermark):
                raise failure(409, "run_stale")
            run.pinned = value
            await event(db, caller, "run.pinned" if value else "run.unpinned", details={"run_id": str(run.id)})
        return {"id": str(run_id), "pinned": value}

    @app.post("/api/admin/scoring/runs/{run_id}/pin")
    async def pin_run(run_id: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        return await pin(run_id, caller, db, True)

    @app.post("/api/admin/scoring/runs/{run_id}/unpin")
    async def unpin_run(run_id: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        return await pin(run_id, caller, db, False)

    @app.get("/api/admin/scoring/runs/{run_id}/bundle")
    async def run_bundle(run_id: UUID, caller: Caller = Depends(curator)):
        data = await bundle(ctx, run_id)
        if data is None:
            raise failure(404, "not_found")
        return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="run-bundle-{run_id}.json"'})

    # ---- parameters -------------------------------------------------------------

    @app.get("/api/admin/scoring/params")
    async def get_params(caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            params = await scoring_params(db)
        return {"params": params, "params_sha256": params_sha256(params), "defaults": validate_params(DEFAULT_PARAMS)}

    @app.put("/api/admin/scoring/params")
    async def put_params(data: ScoringParamsRequest, caller: Caller = Depends(curator), db=Depends(session)):
        try:
            params = validate_params(data.params)
        except (ValueError, TypeError) as exc:
            raise failure(422, "params_invalid", message=str(exc)) from None
        async with db.begin():
            await moderation_tx(db)
            old = await scoring_params(db)
            await db.execute(update(Setting).where(Setting.key == "scoring_params").values(
                value=params, updated_at=func.now(), updated_by=caller.id))
            await event(db, caller, "params.changed", details={
                "old_sha256": params_sha256(old), "new_sha256": params_sha256(params), "diff": _diff(old, params)})
        ctx.forget_settings()
        return {"params": params, "params_sha256": params_sha256(params)}

    @app.post("/api/admin/scoring/calibration/redraw")
    async def redraw(data: RedrawRequest, caller: Caller = Depends(curator), db=Depends(session)):
        if data.cell not in CELLS[data.kind]:
            raise failure(422, "invalid_cell")
        async with db.begin():
            await moderation_tx(db)
            await event(db, caller, "calibration.redraw_requested", details={"kind": data.kind, "cell": data.cell})
        return {"kind": data.kind, "cell": data.cell, "requested": True}

    @app.get("/api/admin/scoring/settings")
    async def scoring_settings(caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            enabled = (await db.execute(select(Setting.value).where(Setting.key == "scoring_enabled"))).scalar_one_or_none()
        return {"scoring_enabled": enabled is True, "interval_s": ctx.settings.scoring_interval_s}

    @app.put("/api/admin/scoring/settings")
    async def put_scoring_settings(data: ScoringSettingsRequest, caller: Caller = Depends(curator),
                                   db=Depends(session)):
        enabled = data.scoring_enabled
        async with db.begin():
            await db.execute(insert(Setting).values(key="scoring_enabled", value=enabled, updated_at=func.now(),
                                                    updated_by=caller.id)
                             .on_conflict_do_update(index_elements=[Setting.key],
                                                    set_={"value": enabled, "updated_at": func.now(),
                                                          "updated_by": caller.id}))
            await db.execute(text("INSERT INTO label_admin_event (actor_id, kind, target, details) "
                                  "VALUES (:a, 'setting.update', 'scoring_enabled', CAST(:d AS jsonb))"),
                             {"a": caller.id, "d": json.dumps({"value": enabled})})
        return {"scoring_enabled": enabled}


    # ---- gold ---------------------------------------------------------------------

    async def upsert_gold(db, corpus_id, item_id, kind, pool, answer, lemma, source, agrees, event_id):
        await db.execute(insert(Gold).values(
            corpus_id=corpus_id, item_id=item_id, kind=kind, pool=pool, answer=answer, lemma=lemma, source=source,
            suggestion_agrees=agrees, status="active", last_event_id=event_id).on_conflict_do_update(
            index_elements=[Gold.corpus_id, Gold.item_id],
            set_={"pool": pool, "answer": answer, "lemma": lemma, "source": source, "suggestion_agrees": agrees,
                  "status": "active", "last_event_id": event_id}))

    @app.post("/api/admin/gold/import")
    async def import_gold(request: Request, caller: Caller = Depends(curator), db=Depends(session)):
        try:
            data = GoldImportRequest.model_validate_json(await request.body())
        except ValidationError as exc:
            raise failure(422, "invalid_gold") from exc
        keys = list({(row.corpus_id, row.item_id): None for row in data.rows})
        accepted, held_out, unchanged = {}, 0, 0
        async with db.begin():
            await moderation_tx(db)
            params = await scoring_params(db)
            corpora = dict((await db.execute(select(Corpus.id, Corpus.sha256).where(
                Corpus.id.in_({key[0] for key in keys})))).all())
            found = {}
            for start in range(0, len(keys), 1000):
                chunk = keys[start:start + 1000]
                for item, sampled, gold in (await db.execute(
                        select(Item, ItemAudit.audit_sample, Gold)
                        .join(ItemAudit, (ItemAudit.corpus_id == Item.corpus_id) & (ItemAudit.item_id == Item.id))
                        .outerjoin(Gold, (Gold.corpus_id == Item.corpus_id) & (Gold.item_id == Item.id))
                        .where(tuple_(Item.corpus_id, Item.id).in_(chunk)))).all():
                    found[(item.corpus_id, item.id)] = (item, sampled, gold)
            plan = []
            for index, row in enumerate(data.rows):
                key = (row.corpus_id, row.item_id)
                if corpora.get(row.corpus_id) != row.corpus_sha256:
                    raise failure(409, "unknown_item", row=index)
                if key not in found:
                    raise failure(409, "unknown_item", row=index)
                item, sampled, gold = found[key]
                if item.kind != row.kind or item.status != "active":
                    raise failure(409, "unknown_item", row=index)
                if sampled:
                    held_out += 1  # a calibration item never becomes gold (4.4.7)
                    continue
                if gold is not None and gold.status in ("active", "retired"):
                    if (gold.answer, gold.lemma) != (row.answer, row.lemma):
                        raise failure(409, "gold_conflict", row=index)
                    unchanged += 1
                    continue
                plan.append((row, item))
            # Qualification rows fill the kind's qualification pool up to its target; the rest go to audit.
            room = {}
            for kind in ("pair", "lemma", "stem"):
                target = params["readiness"]["stem_qualification_pool" if kind == "stem" else "qualification_pool"]
                have = (await db.execute(select(func.count()).select_from(Gold).where(
                    Gold.kind == kind, Gold.pool == "qualification", Gold.status == "active"))).scalar_one()
                room[kind] = max(0, target - have)
            for row, item in plan:
                pool = row.pool
                if pool == "qualification":
                    if room[row.kind] > 0:
                        room[row.kind] -= 1
                    else:
                        pool = "audit"
                agrees = gold_agrees(item, row.answer, row.lemma)
                event_id = await event(db, caller, "gold.set", corpus_id=item.corpus_id, item_id=item.id, details={
                    "pool": pool, "answer": row.answer, "lemma": row.lemma, "source": row.source,
                    "basis": row.basis, "batch": row.batch, "suggestion_agrees": agrees})
                await upsert_gold(db, item.corpus_id, item.id, item.kind, pool, row.answer, row.lemma, row.source,
                                  agrees, event_id)
                counts = accepted.setdefault(row.kind, {"qualification": 0, "audit": 0})
                counts[pool] += 1
        ctx.forget_settings()
        return {"accepted": accepted, "held_out": held_out, "unchanged": unchanged}

    @app.put("/api/admin/gold/{corpus_id}/{item_id}")
    async def gold_action(corpus_id: UUID, item_id: UUID, data: GoldActionRequest, caller: Caller = Depends(curator),
                          db=Depends(session)):
        async with db.begin():
            await moderation_tx(db)
            row = (await db.execute(select(Item, ItemAudit.audit_sample).join(
                ItemAudit, (ItemAudit.corpus_id == Item.corpus_id) & (ItemAudit.item_id == Item.id))
                .where(Item.corpus_id == corpus_id, Item.id == item_id))).one_or_none()
            if row is None:
                raise failure(404, "unknown_item")
            item, sampled = row
            gold = (await db.execute(select(Gold).where(Gold.corpus_id == corpus_id, Gold.item_id == item_id)
                                     .with_for_update())).scalar_one_or_none()
            disclosed = (await db.execute(select(func.count()).select_from(TrustEvent).where(
                TrustEvent.corpus_id == corpus_id, TrustEvent.item_id == item_id,
                TrustEvent.kind == "gold.disclosed"))).scalar_one() > 0
            where = {"corpus_id": corpus_id, "item_id": item_id}
            if data.action == "set":
                if sampled:
                    raise failure(409, "calibration_item")
                if disclosed:
                    raise failure(409, "gold_disclosed")
                try:
                    gold_answer(item.kind, data.answer, data.lemma)
                except ValueError as exc:
                    raise failure(422, "invalid_gold", message=str(exc)) from None
                agrees = gold_agrees(item, data.answer, data.lemma)
                event_id = await event(db, caller, "gold.set", **where, details={
                    "pool": data.pool, "answer": data.answer, "lemma": data.lemma, "source": "curator",
                    "basis": "curator", "batch": None, "suggestion_agrees": agrees, "reason": data.reason})
                await upsert_gold(db, corpus_id, item_id, item.kind, data.pool, data.answer, data.lemma, "curator",
                                  agrees, event_id)
            else:
                if gold is None:
                    raise failure(404, "not_found")
                if data.action == "reactivate" and disclosed:
                    raise failure(409, "gold_disclosed")
                kind = {"retire": "gold.retired", "reactivate": "gold.reactivated", "retract": "gold.retracted",
                        "disclose": "gold.disclosed"}[data.action]
                event_id = await event(db, caller, kind, **where, details={"reason": data.reason})
                status = {"retire": "retired", "reactivate": "active", "retract": "retracted",
                          "disclose": gold.status}[data.action]
                if data.action == "disclose" and gold.status == "active":
                    # A disclosed answer can no longer test anyone: it stops being served at once.
                    event_id = await event(db, caller, "gold.retired", **where, details={"reason": "disclosed"})
                    status = "retired"
                gold.status, gold.last_event_id = status, event_id
        ctx.forget_settings()
        return {"corpus_id": str(corpus_id), "item_id": str(item_id), "action": data.action}

    @app.get("/api/admin/gold")
    async def list_gold(corpus: UUID | None = None, kind: Literal["pair", "lemma", "stem"] | None = None,
                        pool: Literal["qualification", "audit"] | None = None,
                        status: Literal["active", "retired", "contested", "retracted"] | None = None,
                        offset: int = Query(0, ge=0, le=2**31 - 1), caller: Caller = Depends(curator),
                        db=Depends(session)):
        query = select(Gold, Item.payload).join(Item, (Item.corpus_id == Gold.corpus_id) & (Item.id == Gold.item_id))
        for column, value in ((Gold.corpus_id, corpus), (Gold.kind, kind), (Gold.pool, pool), (Gold.status, status)):
            if value is not None:
                query = query.where(column == value)
        async with db.begin():
            rows = (await db.execute(query.order_by(Gold.kind, Gold.pool, Gold.corpus_id, Gold.item_id)
                                     .offset(offset).limit(201))).all()
            pools = (await db.execute(select(Gold.kind, Gold.pool, Gold.status, Gold.suggestion_agrees, func.count())
                                      .group_by(Gold.kind, Gold.pool, Gold.status, Gold.suggestion_agrees))).all()
        return {"items": [{"corpus_id": str(g.corpus_id), "item_id": str(g.item_id), "kind": g.kind, "pool": g.pool,
                           "answer": g.answer, "lemma": g.lemma, "source": g.source,
                           "suggestion_agrees": g.suggestion_agrees, "status": g.status,
                           "served_count": g.served_count, "word": payload.get("word"),
                           "other_word": payload.get("other_word")} for g, payload in rows[:200]],
                "next_offset": offset + 200 if len(rows) > 200 else None,
                "pools": [{"kind": k, "pool": p, "status": s, "suggestion_agrees": a, "n": n}
                          for k, p, s, a, n in pools]}

    # ---- the trusted list (4.7) ------------------------------------------------------

    @app.get("/api/admin/trusted")
    async def trusted_list(caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            rows = (await db.execute(select(TrustedEmail, Anchor.annotator_id).outerjoin(
                Anchor, Anchor.trusted_id == TrustedEmail.id).order_by(TrustedEmail.id))).all()
        return {"items": [{"id": t.id, "email": t.email, "label": t.label, "added_at": t.added_at.isoformat(),
                           "annotator_id": str(anchor) if anchor else None}
                          for t, anchor in rows if t.removed_at is None],
                "removed": [{"id": t.id, "added_at": t.added_at.isoformat(), "removed_at": t.removed_at.isoformat()}
                            for t, _ in rows if t.removed_at is not None]}

    @app.post("/api/admin/trusted")
    async def trust(data: TrustedRequest, caller: Caller = Depends(curator), db=Depends(session)):
        email = normalized_email(data.email)
        if email is None:
            raise failure(422, "invalid_email")
        digest = email_digest(email)
        async with db.begin():
            await moderation_tx(db)
            if (await db.execute(select(TrustedEmail.id).where(TrustedEmail.email_sha256 == digest,
                                                               TrustedEmail.removed_at.is_(None)))).first():
                raise failure(409, "already_trusted")
            entry = (await db.execute(insert(TrustedEmail).values(email=email, email_sha256=digest, label=data.label,
                                                                  added_by=caller.id).returning(TrustedEmail.id))).scalar_one()
            await event(db, caller, "trusted.added", details={"trusted_id": entry})
            # Someone who already signed in with this verified address becomes an anchor now.
            person = (await db.execute(select(Annotator.id).where(
                Annotator.email == email, Annotator.email_verified, Annotator.status != "erased")
                .with_for_update())).scalar_one_or_none()
            if person is not None:
                await grant_anchor(db, person, entry)
        ctx.forget_settings()
        return {"id": entry}

    @app.delete("/api/admin/trusted/{trusted_id}")
    async def untrust(trusted_id: int, data: TrustedRemoveRequest, caller: Caller = Depends(curator),
                      db=Depends(session)):
        async with db.begin():
            await moderation_tx(db)
            entry = (await db.execute(select(TrustedEmail).where(TrustedEmail.id == trusted_id)
                                      .with_for_update())).scalar_one_or_none()
            if entry is None or entry.removed_at is not None:
                raise failure(404, "not_found")
            entry.removed_at, entry.email, entry.email_sha256, entry.label = func.now(), None, None, None
            await event(db, caller, "trusted.removed", details={"trusted_id": trusted_id, "reason": data.reason})
            await revoke_anchors(db, trusted_id, "trusted.removed", actor_id=caller.id)
        ctx.forget_settings()
        return {"id": trusted_id, "removed": True}

    # ---- adjudication, ambiguity, reopening (4.5.3) ----------------------------------

    async def item_for_decision(db, corpus_id, item_id):
        row = (await db.execute(select(Item, ItemState).join(
            ItemState, (ItemState.corpus_id == Item.corpus_id) & (ItemState.item_id == Item.id))
            .where(Item.corpus_id == corpus_id, Item.id == item_id).with_for_update(of=ItemState))).one_or_none()
        if row is None:
            raise failure(404, "unknown_item")
        return row

    @app.post("/api/admin/items/{corpus_id}/{item_id}/adjudicate")
    async def adjudicate(corpus_id: UUID, item_id: UUID, data: AdjudicateRequest, caller: Caller = Depends(curator),
                         db=Depends(session)):
        async with db.begin():
            await moderation_tx(db)
            item, state = await item_for_decision(db, corpus_id, item_id)
            # The curator settles disputed crowd work; never an item the crowd has not voted on.
            if state.state not in ("contested", "needs_expert", "provisional"):
                raise failure(409, "not_adjudicable", state=state.state)
            try:
                Candidate.model_validate(item.payload).annotation(
                    owner="curator", revision=1, answer=data.answer, lemma=data.lemma,
                    irregular=data.irregular).validate()
                if data.answer == "unsure":
                    raise ValueError
            except ValueError:
                raise failure(422, "invalid_judgment") from None
            await event(db, caller, "item.adjudicated", corpus_id=corpus_id, item_id=item_id, details={
                "answer": data.answer, "lemma": data.lemma, "irregular": data.irregular, "reason": data.reason})
            state.state, state.releasable, state.updated_at = "resolved", True, func.now()
        return {"state": "resolved"}

    @app.post("/api/admin/items/{corpus_id}/{item_id}/ambiguous")
    async def ambiguous(corpus_id: UUID, item_id: UUID, data: ReasonRequest, caller: Caller = Depends(curator),
                        db=Depends(session)):
        async with db.begin():
            await moderation_tx(db)
            _, state = await item_for_decision(db, corpus_id, item_id)
            await event(db, caller, "item.ambiguous", corpus_id=corpus_id, item_id=item_id,
                        details={"reason": data.reason})
            state.state, state.releasable, state.updated_at = "ambiguous", False, func.now()
        return {"state": "ambiguous"}

    @app.post("/api/admin/items/{corpus_id}/{item_id}/reopen")
    async def reopen(corpus_id: UUID, item_id: UUID, data: ReopenRequest, caller: Caller = Depends(curator),
                     db=Depends(session)):
        async with db.begin():
            await moderation_tx(db)
            _, state = await item_for_decision(db, corpus_id, item_id)
            event_id = await event(db, caller, "item.reopened", corpus_id=corpus_id, item_id=item_id,
                                   details={"reason": data.reason, "discard_previous": data.discard_previous})
            # A fresh budget: the epoch is the reopen's journal position.
            state.state, state.releasable, state.n_low, state.n_expert = "open", False, 0, 0
            state.epoch, state.epoch_at, state.epoch_discard, state.updated_at = (
                event_id, func.now(), data.discard_previous, func.now())
        return {"state": "open", "epoch": event_id}

    @app.get("/api/admin/items/queue")
    async def item_queue(state: Literal["contested", "needs_expert", "provisional"] = "contested",
                         corpus: UUID | None = None, kind: Literal["pair", "lemma", "stem"] | None = None,
                         caller: Caller = Depends(curator), db=Depends(session)):
        async with db.begin():
            run_id = (await db.execute(text("SELECT id FROM label_scoring_run WHERE status = 'done' "
                                            "ORDER BY finished_at DESC LIMIT 1"))).scalar()
            query = (select(Item, ItemState, ItemPosterior.classes)
                     .join(ItemState, (ItemState.corpus_id == Item.corpus_id) & (ItemState.item_id == Item.id))
                     .outerjoin(ItemPosterior, (ItemPosterior.run_id == run_id)
                                & (ItemPosterior.corpus_id == Item.corpus_id) & (ItemPosterior.item_id == Item.id))
                     .where(ItemState.state == state))
            if corpus:
                query = query.where(Item.corpus_id == corpus)
            if kind:
                query = query.where(Item.kind == kind)
            rows = (await db.execute(query.order_by(Item.corpus_id, Item.ordinal).limit(200))).all()
            votes = {}
            if rows:
                keys = [(item.corpus_id, item.id) for item, _, _ in rows]
                for corpus_id, item_id, annotator_id, answer, lemma, tier in await db.execute(text("""
                        SELECT DISTINCT ON (j.corpus_id, j.item_id, j.annotator_id) j.corpus_id, j.item_id,
                               j.annotator_id, j.answer, j.lemma, s.tier
                        FROM label_judgment j
                        LEFT JOIN label_annotator_score s ON s.run_id = :r AND s.annotator_id = j.annotator_id
                             AND s.kind = (SELECT kind FROM label_item WHERE corpus_id = j.corpus_id AND id = j.item_id)
                        WHERE (j.corpus_id, j.item_id) IN (SELECT * FROM unnest(CAST(:cs AS uuid[]), CAST(:is AS uuid[])))
                        ORDER BY j.corpus_id, j.item_id, j.annotator_id, j.revision DESC"""),
                        {"r": run_id, "cs": [k[0] for k in keys], "is": [k[1] for k in keys]}):
                    votes.setdefault((corpus_id, item_id), []).append(
                        {"annotator_id": str(annotator_id), "answer": answer, "lemma": lemma, "tier": tier or "new"})
        return {"run_id": str(run_id) if run_id else None, "items": [
            {"corpus_id": str(item.corpus_id), "item_id": str(item.id), "kind": item.kind, "state": s.state,
             "word": item.payload.get("word"), "other_word": item.payload.get("other_word"),
             "proposed_lemma": item.payload.get("proposed_lemma"),
             "other_proposed_lemma": item.payload.get("other_proposed_lemma"),
             "proposed_stem": item.payload.get("proposed_stem"), "context": item.payload.get("context"),
             "classes": classes or [], "votes": votes.get((item.corpus_id, item.id), [])}
            for item, s, classes in rows]}

    # ---- agreement and alerts ---------------------------------------------------------

    @app.get("/api/admin/scoring/iaa")
    async def agreement(corpus: UUID, caller: Caller = Depends(curator), db=Depends(session)):
        """Krippendorff's alpha (nominal) per kind and stratum over the latest definite answers
        of annotators whose votes count, observed agreement, and the anchors' agreement with gold."""
        async with db.begin():
            rows = (await db.execute(text("""
                SELECT DISTINCT ON (j.item_id, j.annotator_id) j.item_id, j.annotator_id, j.answer, j.lemma, i.kind,
                       i.payload ->> 'sampling_stratum' AS stratum
                FROM label_judgment j JOIN label_item i ON i.corpus_id = j.corpus_id AND i.id = j.item_id
                JOIN label_annotator a ON a.id = j.annotator_id
                WHERE j.corpus_id = :c AND a.status NOT IN ('blocked', 'quarantined') AND j.admitted IS NOT FALSE
                ORDER BY j.item_id, j.annotator_id, j.revision DESC"""), {"c": corpus})).all()
            anchor_rows = (await db.execute(text("""
                SELECT DISTINCT ON (j.item_id, j.annotator_id) j.answer, j.lemma, g.answer AS gold_answer,
                       g.lemma AS gold_lemma
                FROM label_judgment j JOIN label_anchor x ON x.annotator_id = j.annotator_id
                JOIN label_gold g ON g.corpus_id = j.corpus_id AND g.item_id = j.item_id
                WHERE j.corpus_id = :c AND j.answer <> 'unsure' AND g.status IN ('active', 'retired')
                ORDER BY j.item_id, j.annotator_id, j.revision"""), {"c": corpus})).all()
        units = defaultdict(lambda: defaultdict(list))
        for row in rows:
            cls = answer_class(row.kind, row.answer, row.lemma)
            if cls is not None:
                units[(row.kind, row.stratum or "")][row.item_id].append(cls)
        result = {}
        for (kind, stratum), items in sorted(units.items()):
            values = list(items.values())
            entry = result.setdefault(kind, {"strata": {}})
            entry["strata"][stratum] = {"alpha": krippendorff_alpha(values), "observed_agreement":
                                        observed_agreement(values), "items": sum(len(v) >= 2 for v in values)}
        for kind in result:
            values = [v for (k, _), items in units.items() if k == kind for v in items.values()]
            result[kind].update({"alpha": krippendorff_alpha(values), "observed_agreement": observed_agreement(values)})
        hits = sum((r.answer, r.lemma) == (r.gold_answer, r.gold_lemma) for r in anchor_rows)
        return {"corpus_id": str(corpus), "kinds": result,
                "anchor_gold": {"seen": len(anchor_rows), "agree": hits,
                                "accuracy": hits / len(anchor_rows) if anchor_rows else None}}

    @app.get("/api/admin/alerts")
    async def alerts(caller: Caller = Depends(curator), db=Depends(session)):
        found = []
        async with db.begin():
            params = await scoring_params(db)
            f = params["flags"]
            burst = (await db.execute(text("""
                SELECT count(*) FROM label_annotator a WHERE a.created_at > now() - interval '7 days' AND (
                  SELECT count(*) FROM label_annotator b WHERE b.created_at BETWEEN a.created_at
                    AND a.created_at + make_interval(mins => :w)) >= :n"""),
                {"w": f["signup_burst_window_min"], "n": f["signup_burst_count"]})).scalar_one()
            if burst:
                found.append({"code": "signup_burst"})
            for kind in ("pair", "lemma", "stem"):
                ready = await live_readiness(db, params, kind)
                audit = sum(ready["pools"]["audit"].values())
                if audit < params["gold_pool_warn"]:
                    found.append({"code": "gold_pool_low", "kind": kind, "audit_pool": audit})
                missing = [name for name in ("qualification", "audit", "promotion") if not ready[name]]
                if missing:
                    found.append({"code": "kind_not_ready", "kind": kind, "missing": missing})
            recent = (await db.execute(text("SELECT status FROM label_scoring_run ORDER BY started_at DESC LIMIT 3"))
                      ).scalars().all()
            if len(recent) == 3 and set(recent) == {"failed"}:
                found.append({"code": "runs_failing"})
            superseded = (await db.execute(text("SELECT count(*) FROM label_scoring_run WHERE status = 'superseded' "
                                                "AND started_at > now() - interval '1 day'"))).scalar_one()
            if superseded:
                found.append({"code": "runs_superseded", "count": superseded})
            due = (await db.execute(text("""
                SELECT a.id FROM label_annotator a WHERE a.status = 'quarantined'
                  AND (SELECT max(e.at) FROM label_admin_event e WHERE e.kind = 'annotator.status'
                       AND e.target = a.id::text) < now() - interval '7 days'"""))).scalars().all()
            found += [{"code": "quarantine_review_due", "annotator_id": str(a)} for a in due]
            weak = (await db.execute(text("""
                SELECT s.annotator_id, s.kind FROM label_annotator_score s
                WHERE s.run_id = (SELECT id FROM label_scoring_run WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1)
                  AND s.tier = 'anchor' AND s.gold_seen > 0 AND s.gold_hits < 0.8 * s.gold_seen"""))).all()
            found += [{"code": "anchor_gold_accuracy", "annotator_id": str(a), "kind": k} for a, k in weak]
            waiting = (await db.execute(text("SELECT count(*) FROM label_erasure_request WHERE keycloak_deleted_at IS "
                                             "NULL AND requested_at < now() - interval '14 days'"))).scalar_one()
            if waiting:
                found.append({"code": "erasures_waiting", "count": waiting})
        return {"items": found}

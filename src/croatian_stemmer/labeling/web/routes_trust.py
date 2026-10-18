"""Curator routes of the trust system: scoring runs and parameters, gold, the trusted
list, adjudication and reopening, dashboard views.

Every route depends on ctx.curator. Each moderation action takes the shared
moderation lock first (moderation_tx) and writes one trust event plus its mirror
update in one transaction, so a run that did not see it cannot publish over it.
"""

import json
from typing import Literal
from uuid import UUID

from fastapi import Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from ..scoring import CELLS, DEFAULT_PARAMS, answer_class, params_sha256, suggested_class, validate_params
from .common import Caller, failure, scoring_params, trust_event
from .models import Corpus, Gold, Item, ItemAudit, ScoringRun, Setting, TrustEvent
from .requests import (GoldActionRequest, GoldImportRequest, RedrawRequest, ScoringParamsRequest,
                       ScoringSettingsRequest, gold_answer)
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

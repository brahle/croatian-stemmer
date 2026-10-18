"""The database side of a scoring run: barrier, loader, publication fence, scheduling.

A run (4.6.4): take a commit-safe watermark (every journal seq at or below it belongs
to a finished transaction), load the journals up to it in one REPEATABLE READ snapshot,
hash them, call the pure scoring.score() in a thread, and publish only if no moderation
event arrived after the watermark. Nothing here UPDATEs or DELETEs a journal row; a run
only appends the events it decided.
"""

import asyncio
import logging
from datetime import date, timezone
from uuid import UUID, uuid4

from sqlalchemy import text

from ..scoring import SCORING_VERSION, inputs_sha256, inputs_summary, params_sha256, score, sha256, validate_params
from .models import JOURNAL_LOCK, MODERATION_LOCK, SCORING_LOCK

log = logging.getLogger("croatian_stemmer.labeling.web.scoring")

# A run's own status changes (automatic quarantines and releases carry its id) never make it stale.
MODERATED_AFTER = text("""
    SELECT EXISTS (SELECT 1 FROM label_admin_event WHERE coalesce(seq, 0) > :w
                   AND label_is_moderation('label_admin_event', kind, NULL, details)
                   AND (CAST(:r AS text) IS NULL OR (details ->> 'run_id') IS DISTINCT FROM CAST(:r AS text)))
        OR EXISTS (SELECT 1 FROM label_trust_event WHERE id > :w
                   AND label_is_moderation('label_trust_event', kind, run_id, details))""")


class ScoringBusy(Exception):
    pass


class TooManyJudgments(Exception):
    pass


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def _str(value):
    return str(value) if value is not None else None


async def moderation_tx(db):
    """First statement of every transaction that writes a moderation event: the shared
    moderation lock, before any row lock, so a publishing run and a moderation writer
    can never deadlock (4.6.5)."""
    await db.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": MODERATION_LOCK})


async def stale(db, watermark, run_id=None) -> bool:
    """A run is stale when a moderation event it did not write exists after its watermark."""
    return bool((await db.execute(MODERATED_AFTER, {"w": watermark, "r": str(run_id) if run_id else None})).scalar_one())


async def barrier(engine, lock_timeout="30s"):
    """(watermark, UTC day): waits until every writer holding the shared journal lock has
    finished, then reads the sequence. Any later allocation is larger."""
    async with engine.connect() as connection:
        async with connection.begin():
            await connection.execute(text(f"SET LOCAL lock_timeout = '{lock_timeout}'"))
            await connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": JOURNAL_LOCK})
            last, called = (await connection.execute(text("SELECT last_value, is_called FROM label_journal_seq"))).one()
            day = (await connection.execute(text("SELECT (now() AT TIME ZONE 'UTC')::date"))).scalar_one()
    return (last if called else 0), day


async def load_inputs(engine, watermark, as_of_day, max_judgments=2_000_000):
    """(params, inputs) from one REPEATABLE READ snapshot: the journals up to the watermark
    (NULL seq counts as 0), item membership at the watermark and the live parameters."""
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="REPEATABLE READ")
        async with connection.begin():
            await connection.execute(text("SET TRANSACTION READ ONLY"))
            w = {"w": watermark}
            params = validate_params((await connection.execute(text(
                "SELECT value FROM label_setting WHERE key = 'scoring_params'"))).scalar_one())
            count = (await connection.execute(text(
                "SELECT count(*) FROM label_judgment WHERE coalesce(seq, 0) <= :w"), w)).scalar_one()
            if count > max_judgments:
                raise TooManyJudgments(f"too_many_judgments: {count} > {max_judgments}")
            items = [{"corpus_id": str(r.corpus_id), "item_id": str(r.item_id), "kind": r.kind,
                      "stratum": r.stratum or "", "proposed_lemma": r.proposed_lemma or "",
                      "other_proposed_lemma": r.other_proposed_lemma or "", "status": r.status,
                      "audit_sample": r.audit_sample, "review_sample": r.review_sample,
                      "audit_rank": r.audit_rank, "seq": r.seq}
                     for r in await connection.execute(text("""
                SELECT a.corpus_id, a.item_id, a.seq, a.audit_sample, a.review_sample, a.audit_rank, i.kind, i.status,
                       i.payload ->> 'sampling_stratum' AS stratum, i.payload ->> 'proposed_lemma' AS proposed_lemma,
                       i.payload ->> 'other_proposed_lemma' AS other_proposed_lemma
                FROM label_item_audit a JOIN label_item i ON i.corpus_id = a.corpus_id AND i.id = a.item_id
                WHERE coalesce(a.seq, 0) <= :w ORDER BY a.corpus_id, a.item_id"""), w)]
            judgments = []
            result = await connection.stream(text("""
                SELECT seq, id, corpus_id, item_id, annotator_id, revision, answer, lemma, irregular, admitted,
                       admission_group, presentation, elapsed_ms, created_at
                FROM label_judgment WHERE coalesce(seq, 0) <= :w ORDER BY coalesce(seq, 0), id"""), w)
            async for chunk in result.partitions(10000):
                judgments.extend({"seq": r.seq, "id": str(r.id), "corpus_id": str(r.corpus_id),
                                  "item_id": str(r.item_id), "annotator_id": str(r.annotator_id),
                                  "revision": r.revision, "answer": r.answer, "lemma": r.lemma,
                                  "irregular": r.irregular, "admitted": r.admitted,
                                  "admission_group": r.admission_group, "presentation": r.presentation,
                                  "elapsed_ms": r.elapsed_ms, "created_at": _iso(r.created_at)} for r in chunk)
            # Locale and UI version are not inputs of a run, so the bundle leaves them out.
            consents = [{"seq": r.seq, "annotator_id": str(r.annotator_id), "document": r.document,
                         "version": r.version, "age_threshold": r.age_threshold}
                        for r in await connection.execute(text(
                            "SELECT seq, annotator_id, document, version, age_threshold FROM label_consent "
                            "WHERE coalesce(seq, 0) <= :w ORDER BY coalesce(seq, 0), id"), w)]
            # Only what scoring reads: the status change and the deciding run, never a reason, a
            # flag list or an erasure request's Keycloak id (these inputs travel in the bundle).
            admin = [{"seq": r.seq, "id": r.id, "at": _iso(r.at), "actor_id": _str(r.actor_id), "kind": r.kind,
                      "target": r.target, "details": {k: v for k, v in r.details.items() if k in ("from", "to", "run_id")}
                      if r.kind == "annotator.status" else {}}
                     for r in await connection.execute(text(
                         "SELECT seq, id, at, actor_id, kind, target, details FROM label_admin_event "
                         "WHERE coalesce(seq, 0) <= :w AND kind IN ('annotator.status', 'erasure.requested') "
                         "ORDER BY coalesce(seq, 0), id"), w)]
            trust = [{"id": r.id, "at": _iso(r.at), "actor_id": _str(r.actor_id), "kind": r.kind,
                      "annotator_id": _str(r.annotator_id), "corpus_id": _str(r.corpus_id),
                      "item_id": _str(r.item_id), "run_id": _str(r.run_id), "details": r.details}
                     for r in await connection.execute(text(
                         "SELECT id, at, actor_id, kind, annotator_id, corpus_id, item_id, run_id, details "
                         "FROM label_trust_event WHERE id <= :w ORDER BY id"), w)]
    inputs = {"watermark": watermark, "as_of_day": as_of_day.isoformat(), "items": items, "judgments": judgments,
              "consents": consents, "admin_events": admin, "trust_events": trust}
    return params, inputs


async def _insert_many(db, statement, rows, size=2000):
    for start in range(0, len(rows), size):
        await db.execute(text(statement), rows[start:start + size])


async def publish(engine, run_id, watermark, outputs) -> str:
    """'done', or 'superseded' when a moderation event arrived after the watermark."""
    import json
    async with engine.connect() as connection:
        async with connection.begin():
            await connection.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MODERATION_LOCK})
            if await stale(connection, watermark):
                await connection.execute(text("UPDATE label_scoring_run SET status = 'superseded', finished_at = now() "
                                              "WHERE id = :r"), {"r": run_id})
                return "superseded"
            r = str(run_id)
            await _insert_many(connection, """
                INSERT INTO label_annotator_score (run_id, annotator_id, kind, tier, base_tier, qualified, alpha0, beta0,
                  gold_seen, gold_hits, disc_seen, disc_hits, wrong_sugg_seen, wrong_sugg_hits, soft_hits, soft_misses,
                  theta_mean, theta_lb_gold, weight, flags, n_definite, n_unsure, n_resolved_agree, n_resolved_total)
                VALUES (:run_id, :annotator_id, :kind, :tier, :base_tier, :qualified, :alpha0, :beta0, :gold_seen,
                  :gold_hits, :disc_seen, :disc_hits, :wrong_sugg_seen, :wrong_sugg_hits, :soft_hits, :soft_misses,
                  :theta_mean, :theta_lb_gold, :weight, CAST(:flags AS jsonb), :n_definite, :n_unsure,
                  :n_resolved_agree, :n_resolved_total)""",
                [{**row, "run_id": r, "flags": json.dumps(row["flags"])} for row in outputs["scores"]])
            await _insert_many(connection, """
                INSERT INTO label_item_posterior (run_id, corpus_id, item_id, kind, cell, classes, confidence, state,
                  releasable, resolution_source, resolved_answer, resolved_lemma, epoch, n_definite, n_low, n_expert,
                  n_unsure, n_annotators, n_anchor_votes, n_established_votes, irregular_votes, gold_status)
                VALUES (:run_id, :corpus_id, :item_id, :kind, :cell, CAST(:classes AS jsonb), :confidence, :state,
                  :releasable, :resolution_source, :resolved_answer, :resolved_lemma, :epoch, :n_definite, :n_low,
                  :n_expert, :n_unsure, :n_annotators, :n_anchor_votes, :n_established_votes, :irregular_votes,
                  :gold_status)""",
                [{**row, "run_id": r, "classes": json.dumps(row["classes"])} for row in outputs["posteriors"]])
            states = outputs["item_states"]
            for start in range(0, len(states), 5000):
                chunk = states[start:start + 5000]
                # The run's columns only; the epoch belongs to the reopen route.
                await connection.execute(text("""
                    UPDATE label_item_state s SET run_id = :run_id, state = v.state, confidence = v.confidence,
                      n_low = v.n_low, n_expert = v.n_expert, priority = v.priority, releasable = v.releasable,
                      updated_at = now()
                    FROM unnest(CAST(:corpora AS uuid[]), CAST(:items AS uuid[]), CAST(:states AS text[]),
                                CAST(:confidences AS float8[]), CAST(:lows AS int[]), CAST(:experts AS int[]),
                                CAST(:priorities AS float8[]), CAST(:releasables AS bool[]))
                      AS v(corpus_id, item_id, state, confidence, n_low, n_expert, priority, releasable)
                    WHERE s.corpus_id = v.corpus_id AND s.item_id = v.item_id"""),
                    {"run_id": r, "corpora": [x["corpus_id"] for x in chunk], "items": [x["item_id"] for x in chunk],
                     "states": [x["state"] for x in chunk], "confidences": [x["confidence"] for x in chunk],
                     "lows": [x["n_low"] for x in chunk], "experts": [x["n_expert"] for x in chunk],
                     "priorities": [x["priority"] for x in chunk], "releasables": [x["releasable"] for x in chunk]})
            # Automatic quarantines and releases apply only if the status is still what the run saw.
            applied = set()
            for change in outputs["status_changes"]:
                done = await connection.execute(text(
                    "UPDATE label_annotator SET status = :to WHERE id = :a AND status = :from"),
                    {"a": change["annotator_id"], "to": change["to"], "from": change["from"]})
                if done.rowcount != 1:
                    continue
                applied.add((change["annotator_id"], change["to"]))
                details = {"from": change["from"], "to": change["to"], "run_id": r}
                if "flags" in change:
                    details["flags"] = change["flags"]
                else:
                    details["reason"] = change["reason"]
                await connection.execute(text(
                    "INSERT INTO label_admin_event (actor_id, kind, target, details) "
                    "VALUES (NULL, 'annotator.status', :t, CAST(:d AS jsonb))"),
                    {"t": change["annotator_id"], "d": json.dumps(details)})
            for event in outputs["events"]:
                if event["kind"] == "annotator.quarantined" and (event["annotator_id"], "quarantined") not in applied:
                    continue
                if event["kind"] == "annotator.cleared" and (event["annotator_id"], "active") not in applied:
                    continue
                event_id = (await connection.execute(text(
                    "INSERT INTO label_trust_event (actor_id, kind, annotator_id, corpus_id, item_id, run_id, details) "
                    "VALUES (NULL, :kind, :annotator, :corpus, :item, :run, CAST(:details AS jsonb)) RETURNING id"),
                    {"kind": event["kind"], "annotator": event["annotator_id"], "corpus": event["corpus_id"],
                     "item": event["item_id"], "run": r, "details": json.dumps(event["details"])})).scalar_one()
                await _mirror_gold(connection, event, event_id)
            previous = (await connection.execute(text(
                "SELECT id FROM label_scoring_run WHERE status = 'done' ORDER BY finished_at DESC, id LIMIT 1"))).scalar()
            counts = outputs["counts"]
            await connection.execute(text("""
                UPDATE label_scoring_run SET status = 'done', finished_at = now(), previous_run_id = :previous,
                  n_judgments = :j, n_items = :i, n_annotators = :a, outputs_sha256 = :o,
                  calibration = CAST(:c AS jsonb), readiness = CAST(:rd AS jsonb) WHERE id = :r"""),
                {"previous": previous, "j": counts["n_judgments"], "i": counts["n_items"], "a": counts["n_annotators"],
                 "o": sha256(outputs), "c": json.dumps(outputs["calibration"]), "rd": json.dumps(outputs["readiness"]),
                 "r": r})
    return "done"


async def _mirror_gold(connection, event, event_id):
    """Keep label_gold (the scheduler's mirror) in step with a gold event the run decided."""
    kind, details = event["kind"], event["details"]
    key = {"c": event["corpus_id"], "i": event["item_id"], "e": event_id}
    if kind == "gold.set":
        await connection.execute(text("""
            INSERT INTO label_gold (corpus_id, item_id, kind, pool, answer, lemma, source, suggestion_agrees, status,
                                    last_event_id)
            SELECT :c, :i, i.kind, :pool, :answer, :lemma, :source, :agrees, 'active', :e
            FROM label_item i WHERE i.corpus_id = :c AND i.id = :i
            ON CONFLICT (corpus_id, item_id) DO UPDATE SET pool = EXCLUDED.pool, answer = EXCLUDED.answer,
              lemma = EXCLUDED.lemma, source = EXCLUDED.source, suggestion_agrees = EXCLUDED.suggestion_agrees,
              status = 'active', last_event_id = EXCLUDED.last_event_id"""),
            {**key, "pool": details["pool"], "answer": details["answer"], "lemma": details["lemma"],
             "source": details["source"], "agrees": details["suggestion_agrees"]})
    elif kind in ("gold.retracted", "gold.contested"):
        await connection.execute(text("UPDATE label_gold SET status = :s, last_event_id = :e "
                                      "WHERE corpus_id = :c AND item_id = :i"),
                                 {**key, "s": kind.split(".")[1]})


async def run_once(ctx, *, triggered_by=None, as_of_day: date | None = None):
    """One run, start to publication. Returns (run_id, status)."""
    settings = ctx.settings
    run_id = uuid4()
    watermark, day = await barrier(ctx.engine)
    day = as_of_day or day
    try:
        params, inputs = await load_inputs(ctx.engine, watermark, day, settings.scoring_max_judgments)
    except Exception as exc:
        await _failed_row(ctx, run_id, watermark, day, triggered_by, exc)
        raise
    summary = inputs_summary(inputs)
    async with ctx.engine.begin() as connection:
        await connection.execute(text("""
            INSERT INTO label_scoring_run (id, scoring_version, params, params_sha256, watermark, as_of_day, started_at,
              status, triggered_by, inputs_sha256, inputs_summary)
            VALUES (:id, :v, CAST(:p AS jsonb), :ps, :w, :d, now(), 'running', :t, :ih, CAST(:s AS jsonb))"""),
            {"id": run_id, "v": SCORING_VERSION, "p": _json(params), "ps": params_sha256(params), "w": watermark,
             "d": day, "t": triggered_by, "ih": inputs_sha256(inputs, summary), "s": _json(summary)})
    try:
        outputs = await asyncio.wait_for(asyncio.to_thread(score, inputs, params), settings.scoring_run_timeout_s)
        if ctx.scoring_pause is not None:  # tests pause here to interleave moderation
            await ctx.scoring_pause(run_id)
        status = await publish(ctx.engine, run_id, watermark, outputs)
    except Exception as exc:
        async with ctx.engine.begin() as connection:
            await connection.execute(text("UPDATE label_scoring_run SET status = 'failed', finished_at = now(), "
                                          "error = :e WHERE id = :id"), {"e": _message(exc), "id": run_id})
        raise
    return run_id, status


def _json(value):
    import json
    return json.dumps(value)


def _message(exc):
    """The error text stored with a failed run: the exception's kind and message, never row contents."""
    text_ = str(exc).splitlines()[0][:300] if str(exc) else ""
    return f"{type(exc).__name__}: {text_}" if text_ else type(exc).__name__


async def _failed_row(ctx, run_id, watermark, day, triggered_by, exc):
    async with ctx.engine.begin() as connection:
        params = (await connection.execute(text("SELECT value FROM label_setting WHERE key = 'scoring_params'"))).scalar_one()
        await connection.execute(text("""
            INSERT INTO label_scoring_run (id, scoring_version, params, params_sha256, watermark, as_of_day, started_at,
              finished_at, status, triggered_by, error)
            VALUES (:id, :v, CAST(:p AS jsonb), :ps, :w, :d, now(), now(), 'failed', :t, :e)"""),
            {"id": run_id, "v": SCORING_VERSION, "p": _json(params), "ps": params_sha256(params), "w": watermark,
             "d": day, "t": triggered_by, "e": _message(exc)})


async def run_now(ctx, *, triggered_by=None, as_of_day=None, wait=False):
    """Run under the scoring lock, rerunning at once after a supersession (at most three in
    a row). ScoringBusy when another run holds the lock (unless `wait`)."""
    async with ctx.engine.connect() as holder:
        if wait:
            await holder.execute(text("SELECT pg_advisory_lock(:k)"), {"k": SCORING_LOCK})
        elif not (await holder.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCORING_LOCK})).scalar_one():
            raise ScoringBusy()
        await holder.commit()
        try:
            results = []
            for _ in range(4):
                run_id, status = await run_once(ctx, triggered_by=triggered_by, as_of_day=as_of_day)
                results.append((run_id, status))
                if status != "superseded":
                    break
            ctx.forget_settings()  # a run can change the gold pools the scheduler caches
            return results
        finally:
            await holder.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCORING_LOCK})
            await holder.commit()


async def scheduled_tick(ctx, as_of_day=None):
    """The lifespan job: skip when scoring is disabled, another run holds the lock, or neither
    the journal nor the UTC day moved since the last done run."""
    async with ctx.engine.connect() as connection:
        enabled = (await connection.execute(text(
            "SELECT value FROM label_setting WHERE key = 'scoring_enabled'"))).scalar_one_or_none()
        if enabled is not True:
            return None
        last = (await connection.execute(text(
            "SELECT watermark, as_of_day FROM label_scoring_run WHERE status = 'done' "
            "ORDER BY finished_at DESC LIMIT 1"))).one_or_none()
        position, called = (await connection.execute(text("SELECT last_value, is_called FROM label_journal_seq"))).one()
        today = as_of_day or (await connection.execute(text("SELECT (now() AT TIME ZONE 'UTC')::date"))).scalar_one()
    if last is not None and last.watermark >= (position if called else 0) and last.as_of_day == today:
        return None
    try:
        return await run_now(ctx, as_of_day=as_of_day)
    except ScoringBusy:
        return None


async def latest_done(db):
    return (await db.execute(text("SELECT id FROM label_scoring_run WHERE status = 'done' "
                                  "ORDER BY finished_at DESC, id LIMIT 1"))).scalar()


async def bundle(ctx, run_id: UUID) -> dict | None:
    """The restricted reproducibility bundle of a run, rebuilt from the journals now: the run
    row and every input up to its watermark (never the audit key)."""
    async with ctx.engine.connect() as connection:
        run = (await connection.execute(text(
            "SELECT id, scoring_version, params, params_sha256, watermark, as_of_day, inputs_sha256, inputs_summary, "
            "outputs_sha256, status FROM label_scoring_run WHERE id = :r"), {"r": run_id})).one_or_none()
    if run is None:
        return None
    _, inputs = await load_inputs(ctx.engine, run.watermark, run.as_of_day, ctx.settings.scoring_max_judgments)
    return {"format": "croatian-stemmer-labeling-run-bundle/1",
            "run": {"id": str(run.id), "scoring_version": run.scoring_version, "params": run.params,
                    "params_sha256": run.params_sha256, "watermark": run.watermark,
                    "as_of_day": run.as_of_day.isoformat(), "inputs_sha256": run.inputs_sha256,
                    "inputs_summary": run.inputs_summary, "outputs_sha256": run.outputs_sha256, "status": run.status},
            "inputs": inputs}


async def run_outputs(ctx, watermark, as_of_day, params, inputs_hash):
    """(outputs, inputs_changed): a run recomputed from the journals at its watermark, for
    the per-vote rows no table keeps. inputs_changed when a later privacy action changed them."""
    _, inputs = await load_inputs(ctx.engine, watermark, as_of_day, ctx.settings.scoring_max_judgments)
    outputs = await asyncio.wait_for(asyncio.to_thread(score, inputs, validate_params(params)),
                                     ctx.settings.scoring_run_timeout_s)
    return outputs, inputs_sha256(inputs) != inputs_hash

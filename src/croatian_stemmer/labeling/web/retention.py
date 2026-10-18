"""Retention (4.13.6): one job at startup and daily, independent of scoring runs, so data
expire with no new runs and right after a restore. Each rule takes the clock as an
argument (the database's when None) so it can be tested.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import text

log = logging.getLogger("croatian_stemmer.labeling.web.retention")
OUTPUT_DAYS = 30  # score and posterior rows after their run
TIMING_DAYS = 90  # elapsed_ms after the answer
SHOWN_DAYS = 30  # unanswered assignments after their last showing


def _before(now, days):
    """(SQL for the cutoff, parameters): the database clock, or `now` in tests."""
    if now is None:
        return f"now() - interval '{int(days)} days'", {}
    return ":cutoff", {"cutoff": now - timedelta(days=days)}


async def expire_outputs(db, now: datetime | None = None, days=OUTPUT_DAYS):
    """Score and posterior rows of runs that finished more than `days` ago, pinned runs
    included; the latest done run is kept while it is the latest. Run rows stay."""
    cutoff, params = _before(now, days)
    removed = 0
    for table in ("label_annotator_score", "label_item_posterior"):
        result = await db.execute(text(f"""
            DELETE FROM {table} WHERE run_id IN (
              SELECT id FROM label_scoring_run WHERE finished_at < {cutoff} AND id IS DISTINCT FROM (
                SELECT id FROM label_scoring_run WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1))"""), params)
        removed += result.rowcount
    return removed


async def expire_timing(db, now: datetime | None = None, days=TIMING_DAYS):
    """Answer timing is kept for the `fast` signal for 90 days (the append-only trigger allows
    exactly this change)."""
    cutoff, params = _before(now, days)
    result = await db.execute(text(f"UPDATE label_judgment SET elapsed_ms = NULL WHERE elapsed_ms IS NOT NULL "
                                   f"AND created_at < {cutoff}"), params)
    return result.rowcount


async def expire_showings(db, now: datetime | None = None, days=SHOWN_DAYS):
    """Unanswered showings are scheduling state only; answered ones stay until erasure."""
    cutoff, params = _before(now, days)
    result = await db.execute(text(f"DELETE FROM label_assignment WHERE current_revision = 0 "
                                   f"AND last_shown_at < {cutoff}"), params)
    return result.rowcount


async def apply_retention(ctx, now: datetime | None = None):
    """Every rule, each in its own transaction. Returns {rule: rows affected}."""
    done = {}
    for name, rule in (("outputs", expire_outputs), ("timing", expire_timing), ("showings", expire_showings)):
        async with ctx.sessions() as db:
            async with db.begin():
                done[name] = await rule(db, now)
    if any(done.values()):
        log.info("retention: %s", ", ".join(f"{name} {count}" for name, count in done.items()))
    return done

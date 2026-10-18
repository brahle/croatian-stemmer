"""Retention (4.13.6): scores and computed item results 30 days after their run (the latest
run kept), answer timing 90 days, unanswered showings 30 days; applied at startup too."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, profiled, score_now

pytestmark = pytest.mark.asyncio


async def counts(api, run_id):
    found = []
    for table in ("label_annotator_score", "label_item_posterior"):
        found.append((await api.sql(f"SELECT count(*) FROM {table} WHERE run_id = :r", r=run_id)).scalar_one())
    return tuple(found)


async def test_rules_on_a_fake_clock(fresh_api):
    from croatian_stemmer.labeling.web.retention import apply_retention
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    await profiled(api, "alice")
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    [(old, _)] = await score_now(api)
    assert (await api.request("POST", f"/api/admin/scoring/runs/{old}/pin", "curator", True)).status_code == 200
    assert (await api.request("POST", answer_path(rows[1]), "alice", json=answer())).status_code == 200
    [(latest, _)] = await score_now(api)
    unanswered = (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/next', "alice")).json()["item"]
    assert unanswered is not None
    ctx = api.app.state.ctx
    now = datetime.now(timezone.utc)
    # Within the periods nothing changes.
    assert await apply_retention(ctx, now=now + timedelta(days=29)) == {"outputs": 0, "timing": 0, "showings": 0}
    # 40 days without runs: older outputs go (the pinned run's included), the latest run's stay.
    done = await apply_retention(ctx, now=now + timedelta(days=40))
    assert done["outputs"] > 0 and done["showings"] == 1 and done["timing"] == 0
    assert await counts(api, old) == (0, 0)
    assert await counts(api, latest) != (0, 0)
    assert (await api.sql("SELECT count(*) FROM label_scoring_run WHERE id = :r", r=old)).scalar_one() == 1
    assert (await api.sql("SELECT count(*) FROM label_assignment WHERE current_revision = 0 AND annotator_id = :a",
                          a=await api.annotator_id("alice"))).scalar_one() == 0
    # 91 days on, answer timing is gone; the answers stay.
    assert (await apply_retention(ctx, now=now + timedelta(days=91)))["timing"] == 2
    timing = (await api.sql("SELECT elapsed_ms, answer FROM label_judgment WHERE annotator_id = :a",
                            a=await api.annotator_id("alice"))).all()
    assert [tuple(t) for t in timing] == [(None, "same"), (None, "same")]


async def test_startup_applies_every_rule(fresh_api):
    """A restored older dump is cleaned at startup, before any run."""
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    alice = await profiled(api, "alice")
    await api.sql("INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular, "
                  "item_revision, client_version, elapsed_ms, created_at) VALUES (:id, :c, :i, :a, 1, 'same', false, 1, "
                  "'0.3.0', 1500, now() - interval '100 days')", id=uuid4(), c=rows[0]["corpus_id"],
                  i=rows[0]["item_id"], a=alice)
    await api.sql("INSERT INTO label_assignment (annotator_id, corpus_id, item_id, first_shown_at, last_shown_at, "
                  "shown_count) VALUES (:a, :c, :i, now() - interval '40 days', now() - interval '40 days', 1)",
                  a=alice, c=rows[1]["corpus_id"], i=rows[1]["item_id"])
    app = api.app
    async with app.router.lifespan_context(app):
        import asyncio
        for _ in range(50):
            await asyncio.sleep(0.1)
            left = (await api.sql("SELECT count(*) FROM label_judgment WHERE elapsed_ms IS NOT NULL AND annotator_id = :a",
                                  a=alice)).scalar_one()
            if left == 0:
                break
    assert left == 0
    assert (await api.sql("SELECT count(*) FROM label_assignment WHERE annotator_id = :a AND current_revision = 0",
                          a=alice)).scalar_one() == 0

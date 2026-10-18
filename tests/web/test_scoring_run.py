"""The scoring run against PostgreSQL: one run publishes scores, posteriors and the queue;
an unchanged journal is skipped; the lock admits one run; a failure leaves the queue alone."""
import asyncio

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, profiled, score_now

pytestmark = pytest.mark.asyncio


async def answered(api, rows, name, value="same"):
    root = f'/api/corpora/{rows[0]["corpus_id"]}'
    item = (await api.request("GET", root + "/next", name)).json()["item"]
    r = await api.request("POST", answer_path(item["candidate"]), name, json=answer(value=value))
    assert r.status_code == 200, r.text
    return item


async def test_a_run_publishes_scores_posteriors_and_the_queue(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    for name in ("alice", "bob"):
        await profiled(api, name)
        await answered(api, rows, name)
    [(run_id, status)] = await score_now(api)
    assert status == "done"
    run = (await api.sql("SELECT status, watermark, n_judgments, inputs_sha256, outputs_sha256, readiness "
                         "FROM label_scoring_run WHERE id = :r", r=run_id)).one()
    assert run.status == "done" and run.n_judgments == 2 and run.inputs_sha256 and run.outputs_sha256
    assert set(run.readiness) == {"pair", "lemma", "stem"}
    scores = (await api.sql("SELECT annotator_id, kind, tier, weight FROM label_annotator_score WHERE run_id = :r",
                            r=run_id)).all()
    assert {(s.kind, s.tier) for s in scores} == {("pair", "new")} and len(scores) == 2
    posteriors = (await api.sql("SELECT classes, state, n_low FROM label_item_posterior WHERE run_id = :r",
                                r=run_id)).all()
    # Coverage first: each person got a different item.
    assert [(p.state, p.n_low, p.classes[0]["votes"]) for p in posteriors] == [("open", 1, 1)] * 2
    queue = (await api.sql("SELECT count(*) FROM label_item_state WHERE run_id = :r", r=run_id)).scalar_one()
    assert queue == len(rows)
    # Through the curator routes.
    listed = (await api.request("GET", "/api/admin/scoring/runs", "curator", True)).json()["items"]
    assert listed[0]["id"] == str(run_id) and listed[0]["stale"] is False
    detail = (await api.request("GET", f"/api/admin/scoring/runs/{run_id}", "curator", True)).json()
    assert detail["calibration"] and detail["params"]["version"] == "2.0"
    assert (await api.request("GET", "/api/admin/scoring/runs", "alice")).status_code == 403


async def test_scheduled_tick_skips_until_enabled_and_when_nothing_changed(fresh_api):
    from croatian_stemmer.labeling.web.scoring_run import scheduled_tick
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    await profiled(api, "alice")
    await answered(api, rows, "alice")
    ctx = api.app.state.ctx
    assert await scheduled_tick(ctx) is None  # scoring_enabled is false after migration
    r = await api.request("PUT", "/api/admin/scoring/settings", "curator", True, json={"scoring_enabled": True})
    assert r.status_code == 200
    first = await scheduled_tick(ctx)
    assert [status for _, status in first] == ["done"]
    assert await scheduled_tick(ctx) is None  # neither the journal nor the day moved
    await answered(api, rows, "alice")
    assert [status for _, status in await scheduled_tick(ctx)] == ["done"]


async def test_one_run_at_a_time_and_failures_leave_the_queue(fresh_api, monkeypatch):
    from croatian_stemmer.labeling.web import scoring_run
    api = await fresh_api()
    rows = await api.imported()
    await profiled(api, "alice")
    await answered(api, rows, "alice")
    ctx = api.app.state.ctx
    held, release = asyncio.Event(), asyncio.Event()

    async def pause(run_id):
        held.set()
        await release.wait()
    ctx.scoring_pause = pause
    task = asyncio.create_task(score_now(api))
    await asyncio.wait_for(held.wait(), 10)
    busy = await api.request("POST", "/api/admin/scoring/run", "curator", True)
    assert busy.status_code == 409 and busy.json()["detail"]["code"] == "scoring_busy"
    release.set()
    assert [status for _, status in await task] == ["done"]
    ctx.scoring_pause = None

    before = (await api.sql("SELECT run_id, state FROM label_item_state ORDER BY item_id")).all()

    def broken(inputs, params):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(scoring_run, "score", broken)
    with pytest.raises(RuntimeError):
        await score_now(api)
    failed = (await api.sql("SELECT status, error FROM label_scoring_run ORDER BY started_at DESC LIMIT 1")).one()
    assert failed.status == "failed" and failed.error == "RuntimeError: synthetic failure"
    assert (await api.sql("SELECT run_id, state FROM label_item_state ORDER BY item_id")).all() == before

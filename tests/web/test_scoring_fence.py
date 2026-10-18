"""Publication fencing (4.6.5): a run never publishes over a moderation event it did not see,
and moderation writers and a publishing run never deadlock."""
import asyncio

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, profiled, score_now, unlimited

pytestmark = pytest.mark.asyncio


async def labelled(api, names, value="same"):
    rows = await api.imported(candidates(pairs=4))
    for name in names:
        await profiled(api, name)
        for row in rows:
            if row["kind"] == "pair":
                r = await api.request("POST", answer_path(row), name, json=answer(value=value))
                assert r.status_code == 200, r.text
    return rows


def once(ctx, action):
    """Pause the next run between scoring and publication while `action` runs."""
    async def pause(run_id):
        ctx.scoring_pause = None
        await action()
    ctx.scoring_pause = pause


async def status(api, name, to, reason="test"):
    r = await api.request("PUT", f"/api/admin/annotators/{await api.annotator_id(name)}/status", "curator", True,
                          json={"status": to, "reason": reason})
    assert r.status_code == 200, r.text


async def counted_voters(api, run_id):
    return (await api.sql("SELECT sum(n_annotators) FROM label_item_posterior WHERE run_id = :r", r=run_id)).scalar_one()


@pytest.mark.parametrize("action", ["block", "clear", "erase", "gold"])
async def test_a_moderation_event_during_a_run_supersedes_it(fresh_api, action):
    api = await fresh_api()
    rows = await labelled(api, ["alice", "bob"])
    ctx = api.app.state.ctx
    if action == "clear":
        await status(api, "bob", "quarantined")
    moves = {"block": lambda: status(api, "bob", "blocked"), "clear": lambda: status(api, "bob", "active"),
             "erase": lambda: api.request("POST", "/api/me/erase", "bob", json={"confirm": "DELETE"}),
             "gold": lambda: api.request("PUT", f'/api/admin/gold/{rows[0]["corpus_id"]}/{rows[0]["item_id"]}',
                                         "curator", True, json={"action": "set", "pool": "audit", "answer": "same",
                                                                "reason": "fence"})}
    once(ctx, moves[action])
    results = await score_now(api)
    assert [status_ for _, status_ in results] == ["superseded", "done"]
    superseded, done = results[0][0], results[1][0]
    assert (await api.sql("SELECT count(*) FROM label_item_posterior WHERE run_id = :r", r=superseded)).scalar_one() == 0
    voters = await counted_voters(api, done)
    if action == "block":
        assert voters == 4  # alice only, on four pairs
    elif action == "clear":
        assert voters == 8
    elif action == "erase":
        assert voters == 8  # the answers live on under the new identifier
    else:
        gold = (await api.sql("SELECT gold_status FROM label_item_posterior WHERE run_id = :r AND item_id = :i",
                              r=done, i=rows[0]["item_id"])).scalar_one_or_none()
        sampled_now = (await api.sql("SELECT audit_sample FROM label_item_audit WHERE item_id = :i",
                                     i=rows[0]["item_id"])).scalar_one()
        assert gold == ("active" if not sampled_now else None)


async def test_a_clear_during_a_run_is_never_overwritten(fresh_api):
    """The run wants to quarantine X (fast and straight); the curator acts on X meanwhile."""
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=35))
    await profiled(api, "x")
    for row in [r for r in rows if r["kind"] == "pair"][:32]:
        r = await api.request("POST", answer_path(row), "x", json=answer(elapsed_ms=200))
        assert r.status_code == 200
    ctx = api.app.state.ctx
    [(first, state)] = await score_now(api)
    assert state == "done"
    assert (await api.sql("SELECT status FROM label_annotator WHERE id = :a", a=await api.annotator_id("x"))).scalar_one() \
        == "quarantined"
    once(ctx, lambda: status(api, "x", "active", "an honest mistake"))
    results = await score_now(api)
    assert [s for _, s in results] == ["superseded", "done"]
    # The clear moved flags_since past every earlier answer: the rerun does not quarantine again.
    assert (await api.sql("SELECT status FROM label_annotator WHERE id = :a", a=await api.annotator_id("x"))).scalar_one() \
        == "active"
    kinds = [r.kind for r in (await api.sql("SELECT kind FROM label_trust_event WHERE annotator_id = :a ORDER BY id",
                                            a=await api.annotator_id("x"))).all()]
    assert kinds[-2:] == ["annotator.quarantined", "annotator.cleared"]


async def test_the_reverse_interleaving_waits_instead_of_deadlocking(fresh_api):
    api = await fresh_api()
    await labelled(api, ["alice", "bob"])
    ctx = api.app.state.ctx
    holding, release = asyncio.Event(), asyncio.Event()

    async def hold(annotator_id):
        holding.set()
        await release.wait()
    ctx.status_pause = hold
    change = asyncio.create_task(status(api, "bob", "blocked"))
    await asyncio.wait_for(holding.wait(), 10)
    ctx.status_pause = None
    run = asyncio.create_task(score_now(api))
    await asyncio.sleep(0.5)
    assert not run.done()  # publication waits for the status change (it holds the shared moderation lock)
    release.set()
    await asyncio.wait_for(change, 10)
    results = await asyncio.wait_for(run, 30)
    assert [s for _, s in results] in (["superseded", "done"], ["done"])
    assert await counted_voters(api, results[-1][0]) == 4


async def test_status_changes_and_publication_never_deadlock(fresh_api):
    api = await fresh_api()
    await labelled(api, ["alice", "bob"])
    for n in range(200):
        to = "quarantined" if n % 2 == 0 else "active"
        results = await asyncio.gather(status(api, "bob", to), score_now(api), return_exceptions=True)
        assert not [r for r in results if isinstance(r, Exception)], results


async def test_a_later_block_makes_a_run_stale_and_its_pin_is_refused(fresh_api):
    api = await fresh_api()
    await labelled(api, ["alice", "bob"])
    [(run_id, _)] = await score_now(api)
    pin = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/pin", "curator", True)
    assert pin.status_code == 200 and pin.json()["pinned"] is True
    await api.request("POST", f"/api/admin/scoring/runs/{run_id}/unpin", "curator", True)
    await status(api, "bob", "blocked")
    detail = (await api.request("GET", f"/api/admin/scoring/runs/{run_id}", "curator", True)).json()
    assert detail["stale"] is True
    refused = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/pin", "curator", True)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "run_stale"

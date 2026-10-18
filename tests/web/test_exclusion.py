"""Retroactive exclusion (4.7.4) and the consensus-gold chain (4.3.5): every run recomputes
from the journals, so a block or a revoked anchor takes effect at the next run."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import (answer, answer_path, candidates, easy_params, later, make_anchor, pair_rows, profiled,
                              promote, score_now, scoring_on, unlimited, wrong_suggestion_gold)

pytestmark = pytest.mark.asyncio


async def tier(api, run_id, name, kind="pair"):
    return (await api.sql("SELECT tier FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a AND kind = :k",
                          r=run_id, a=await api.annotator_id(name), k=kind)).scalar_one()


async def state(api, row):
    return (await api.sql("SELECT state FROM label_item_state WHERE item_id = :i", i=row["item_id"])).scalar_one()


async def status(api, name, to):
    r = await api.request("PUT", f"/api/admin/annotators/{await api.annotator_id(name)}/status", "curator", True,
                          json={"status": to, "reason": "test"})
    assert r.status_code == 200


async def test_blocking_an_established_voter_reopens_their_items(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(60, different_every=0))
    await easy_params(api)
    await make_anchor(api, "owner")
    gold = await wrong_suggestion_gold(api, rows)
    await promote(api, "x", gold)
    [(run_id, _)] = await score_now(api, as_of_day=later())
    assert await tier(api, run_id, "x") == "established"
    free = [r for r in rows if r not in gold]
    item = free[0]
    await profiled(api, "y")
    # y's vote counts as the second one only with some evidence (theta >= 0.70): one known answer.
    assert (await api.request("POST", answer_path(gold[0]), "y", json=answer(value="different"))).status_code == 200
    for name in ("x", "y"):
        assert (await api.request("POST", answer_path(item), name, json=answer())).status_code == 200
    await score_now(api, as_of_day=later())
    assert await state(api, item) in ("resolved", "provisional")
    await status(api, "x", "blocked")
    await score_now(api, as_of_day=later())
    assert await state(api, item) == "open"
    # Served again to a third annotator.
    await scoring_on(api)
    await profiled(api, "z")
    offered = set()
    for _ in range(len(rows) + 20):
        served = (await api.request("GET", f'/api/corpora/{item["corpus_id"]}/next', "z")).json()["item"]
        if served is None:
            break
        offered.add(served["candidate"]["item_id"])
        await api.request("POST", answer_path(served["candidate"]), "z", fetched=False, json=answer(value="different"))
    assert item["item_id"] in offered
    await status(api, "x", "active")
    await score_now(api, as_of_day=later())
    # z's later `different` keeps it from the 0.95 rule now; x's vote counts again either way.
    posterior = (await api.sql("SELECT p.n_annotators FROM label_item_posterior p JOIN label_scoring_run r ON r.id = p.run_id "
                               "WHERE p.item_id = :i ORDER BY r.finished_at DESC LIMIT 1", i=item["item_id"])).scalar_one()
    assert posterior == 3


async def test_revoking_the_anchor_unwinds_consensus_gold(fresh_api):
    """The anchor's seed answers become gold; X is promoted on them and X's vote resolves Y.
    Revoking the anchor invalidates the gold at the next run: X drops, Y returns to open."""
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(60, different_every=0))
    await easy_params(api)
    owner = await make_anchor(api, "owner")
    from labeling_support import unseeded
    seeds = (await unseeded(api, rows))[:12]
    for row in seeds:  # the owner's answer differs from the suggestion (`same`): final gold
        assert (await api.request("POST", answer_path(row), "owner", json=answer(value="different"))).status_code == 200
    [(first, _)] = await score_now(api, as_of_day=later())
    made = (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'gold.set' AND run_id = :r",
                          r=first)).scalar_one()
    assert made == 12
    assert (await api.sql("SELECT count(*) FROM label_gold WHERE source = 'anchor_consensus' AND status = 'active'")
            ).scalar_one() == 12
    await promote(api, "x", seeds)
    [(second, _)] = await score_now(api, as_of_day=later())
    assert await tier(api, second, "x") == "established"
    target = [r for r in rows if r not in seeds][0]
    await profiled(api, "y")
    # y's vote counts as the second one only with some evidence (theta >= 0.70): one known answer.
    assert (await api.request("POST", answer_path(seeds[0]), "y", json=answer(value="different"))).status_code == 200
    for name in ("x", "y"):
        assert (await api.request("POST", answer_path(target), name, json=answer())).status_code == 200
    await score_now(api, as_of_day=later())
    assert await state(api, target) in ("resolved", "provisional")
    # A supporter's own answers on its consensus gold are never observations on it.
    owner_gold = (await api.sql("SELECT gold_seen FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a",
                                r=second, a=owner)).scalar_one()
    assert owner_gold == 0
    entry = (await api.sql("SELECT trusted_id FROM label_anchor WHERE annotator_id = :a", a=owner)).scalar_one()
    await api.request("DELETE", f"/api/admin/trusted/{entry}", "curator", True, json={"reason": "test"})
    [(after, _)] = await score_now(api, as_of_day=later())
    assert (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'gold.retracted' AND run_id = :r",
                          r=after)).scalar_one() == 12
    assert await tier(api, after, "x") != "established"
    assert await state(api, target) == "open"

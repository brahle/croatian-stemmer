"""Curator decisions on items and the completion queue (4.5.2, 4.5.3) through the API."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.scoring import replay
from labeling_support import (answer, answer_path, easy_params, later, make_anchor, pair_rows, profiled, promote,
                              score_now, scoring_on, unlimited, wrong_suggestion_gold)

pytestmark = pytest.mark.asyncio


def item_path(row, action):
    return f'/api/admin/items/{row["corpus_id"]}/{row["item_id"]}/{action}'


async def offered(api, name, corpus, rounds=80):
    """Every item /next offers `name`, answering each as `same`."""
    seen = []
    for _ in range(rounds):
        served = (await api.request("GET", f"/api/corpora/{corpus}/next", name)).json()["item"]
        if served is None:
            break
        seen.append(served["candidate"]["item_id"])
        await api.request("POST", answer_path(served["candidate"]), name, fetched=False, json=answer())
    return seen


async def test_adjudication_rules_and_the_queue(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(8, different_every=0))
    await scoring_on(api)
    contested = rows[0]
    r = await api.request("POST", item_path(contested, "adjudicate"), "curator", True,
                          json={"answer": "same", "reason": "x"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_adjudicable"
    for n in range(5):
        await profiled(api, f"l{n}")
        assert (await api.request("POST", answer_path(contested), f"l{n}", json=answer())).status_code == 200
    await score_now(api)
    assert (await api.sql("SELECT state FROM label_item_state WHERE item_id = :i", i=contested["item_id"])
            ).scalar_one() == "needs_expert"
    queue = (await api.request("GET", "/api/admin/items/queue", "curator", True,
                               params={"state": "needs_expert"})).json()
    entry = next(i for i in queue["items"] if i["item_id"] == contested["item_id"])
    assert len(entry["votes"]) == 5 and entry["classes"][0]["votes"] == 5
    bad = await api.request("POST", item_path(contested, "adjudicate"), "curator", True,
                            json={"answer": "accept", "reason": "x"})
    assert bad.status_code == 422
    r = await api.request("POST", item_path(contested, "adjudicate"), "curator", True,
                          json={"answer": "different", "reason": "guidelines"})
    assert r.status_code == 200
    # Before any run, /next never offers the adjudicated item.
    await profiled(api, "fresh")
    assert contested["item_id"] not in await offered(api, "fresh", contested["corpus_id"])
    # All its voters blocked: the next run keeps the decision with an empty posterior.
    for n in range(5):
        r = await api.request("PUT", f'/api/admin/annotators/{await api.annotator_id(f"l{n}")}/status', "curator",
                              True, json={"status": "blocked", "reason": "x"})
    [(run_id, _)] = await score_now(api)
    row = (await api.sql("SELECT classes, confidence, state, resolution_source, n_definite FROM label_item_posterior "
                         "WHERE run_id = :r AND item_id = :i", r=run_id, i=contested["item_id"])).one()
    assert (row.classes, row.confidence, row.state, row.resolution_source, row.n_definite) == (
        [], None, "resolved", "adjudication", 0)
    mirror = (await api.sql("SELECT state, confidence, releasable FROM label_item_state WHERE item_id = :i",
                            i=contested["item_id"])).one()
    assert tuple(mirror) == ("resolved", None, True)
    bundle = (await api.request("GET", f"/api/admin/scoring/runs/{run_id}/bundle", "curator", True)).json()
    assert replay(bundle)["report"]["outputs_match"]
    # Ambiguous, then reopened.
    vague = rows[1]
    assert (await api.request("POST", item_path(vague, "ambiguous"), "curator", True, json={"reason": "x"})).status_code == 200
    assert (await api.sql("SELECT state FROM label_item_state WHERE item_id = :i", i=vague["item_id"])).scalar_one() \
        == "ambiguous"
    r = await api.request("POST", item_path(vague, "reopen"), "curator", True,
                          json={"reason": "x", "discard_previous": False})
    assert r.status_code == 200 and r.json()["state"] == "open"


async def test_completion_work_stops_once_the_release_rule_holds(fresh_api):
    """An item resolved on two votes is served again until a third vote makes it releasable."""
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(40, different_every=0))
    await easy_params(api)
    await make_anchor(api, "owner")
    gold = await wrong_suggestion_gold(api, rows)
    for name in ("x1", "x2", "x3"):
        await promote(api, name, gold)
    await score_now(api, as_of_day=later())
    target = [r for r in rows if r not in gold][0]
    for name in ("x1", "x2"):
        assert (await api.request("POST", answer_path(target), name, json=answer())).status_code == 200
    await score_now(api, as_of_day=later())
    mirror = (await api.sql("SELECT state, releasable, priority FROM label_item_state WHERE item_id = :i",
                            i=target["item_id"])).one()
    assert mirror.state in ("resolved", "provisional") and not mirror.releasable and mirror.priority == 0.05
    await scoring_on(api)
    assert target["item_id"] in await offered(api, "x3", target["corpus_id"])
    await score_now(api, as_of_day=later())
    assert (await api.sql("SELECT releasable FROM label_item_state WHERE item_id = :i", i=target["item_id"])
            ).scalar_one() is True
    await profiled(api, "x4")
    assert target["item_id"] not in await offered(api, "x4", target["corpus_id"])

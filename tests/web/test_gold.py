"""Gold import, curator actions and the mirror (4.3.4, 4.3.5)."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import candidates, gold_line, sampled, unsampled

pytestmark = pytest.mark.asyncio


async def gold_events(api, row):
    return [(r.kind, r.details) for r in (await api.sql(
        "SELECT kind, details FROM label_trust_event WHERE corpus_id = :c AND item_id = :i ORDER BY id",
        c=row["corpus_id"], i=row["item_id"])).all()]


async def test_import_conflicts_held_out_items_and_the_qualification_quota(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=120))
    pairs = [r for r in rows if r["kind"] == "pair"]
    free, held = await unsampled(api, pairs), await sampled(api, pairs)
    assert held, "a 120-item corpus has calibration-sampled items at a 10 % rate"
    lines = [gold_line(r, pool="qualification") for r in free[:70]] + [gold_line(r) for r in free[70:80]]
    lines += [gold_line(held[0], pool="qualification")]
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})
    assert r.status_code == 200, r.text
    # 60 qualification items fill the pool; the surplus and the audit rows go to audit; the sampled item is held out.
    assert r.json() == {"accepted": {"pair": {"qualification": 60, "audit": 20}}, "held_out": 1, "unchanged": 0}
    mirror = (await api.sql("SELECT pool, status, suggestion_agrees, count(*) AS n FROM label_gold "
                            "GROUP BY pool, status, suggestion_agrees ORDER BY pool")).all()
    assert [tuple(m) for m in mirror] == [("audit", "active", True, 20), ("qualification", "active", True, 60)]
    kind, details = (await gold_events(api, free[0]))[0]
    assert kind == "gold.set" and details["suggestion_agrees"] is True and details["source"] == "hr500k"
    # The same answer again is unchanged; a different answer fails the whole import.
    again = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines[:2]})
    assert again.json()["unchanged"] == 2
    conflict = [gold_line(free[90]), gold_line(free[0], answer="different")]
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": conflict})
    assert r.status_code == 409 and r.json()["detail"] == {"code": "gold_conflict", "row": 1}
    assert await gold_events(api, free[90]) == []
    # Rows that do not match a stored item or corpus are refused.
    for bad in ({**gold_line(free[91]), "corpus_sha256": "f" * 64}, {**gold_line(free[91]), "kind": "stem",
                                                                       "answer": "accept"}):
        r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": [bad]})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "unknown_item"
    for bad in ({**gold_line(free[91]), "answer": "confirmed"}, {**gold_line(free[91]), "source": "curator"}):
        r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": [bad]})
        assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_gold"
    assert (await api.request("POST", "/api/admin/gold/import", "alice", json={"rows": lines})).status_code == 403


async def test_curator_actions_and_disclosure(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=30))
    free = await unsampled(api, [r for r in rows if r["kind"] == "pair"])
    lemma = next(r for r in rows if r["kind"] == "lemma")
    path = lambda r: f'/api/admin/gold/{r["corpus_id"]}/{r["item_id"]}'
    r = await api.request("PUT", path(free[0]), "curator", True,
                          json={"action": "set", "pool": "audit", "answer": "different", "reason": "expert"})
    assert r.status_code == 200
    gold = (await api.sql("SELECT answer, source, suggestion_agrees, status FROM label_gold WHERE item_id = :i",
                          i=free[0]["item_id"])).one()
    # The suggestion implies `same` (equal proposed lemmas): this gold tests what copying cannot answer.
    assert tuple(gold) == ("different", "curator", False, "active")
    lemma_set = await api.request("PUT", path(lemma), "curator", True,
                                  json={"action": "set", "pool": "audit", "answer": "confirmed", "lemma": "KUĆA",
                                        "reason": "x"})
    if lemma["item_id"] in {s["item_id"] for s in await sampled(api, rows)}:
        assert lemma_set.json()["detail"]["code"] == "calibration_item"
    else:
        assert lemma_set.status_code == 200
        assert (await api.sql("SELECT lemma FROM label_gold WHERE item_id = :i", i=lemma["item_id"])).scalar_one() == "kuća"
    for action, status in (("retire", "retired"), ("reactivate", "active"), ("retract", "retracted"),
                           ("set", "active"), ("disclose", "retired")):
        body = {"action": action, "reason": "test", **({"pool": "audit", "answer": "same"} if action == "set" else {})}
        r = await api.request("PUT", path(free[0]), "curator", True, json=body)
        assert r.status_code == 200, (action, r.text)
        assert (await api.sql("SELECT status FROM label_gold WHERE item_id = :i", i=free[0]["item_id"])).scalar_one() == status
    for action in ("reactivate", "set"):
        body = {"action": action, "reason": "again", **({"pool": "audit", "answer": "same"} if action == "set" else {})}
        r = await api.request("PUT", path(free[0]), "curator", True, json=body)
        assert r.status_code == 409 and r.json()["detail"]["code"] == "gold_disclosed"
    kinds = [kind for kind, _ in await gold_events(api, free[0])]
    assert kinds == ["gold.set", "gold.retired", "gold.reactivated", "gold.retracted", "gold.set", "gold.disclosed",
                     "gold.retired"]
    held = await sampled(api, rows)
    if held:
        r = await api.request("PUT", path(held[0]), "curator", True,
                              json={"action": "set", "pool": "audit", "answer": "same", "reason": "x"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "calibration_item"
    listed = (await api.request("GET", "/api/admin/gold", "curator", True, params={"kind": "pair"})).json()
    assert [g["status"] for g in listed["items"]] == ["retired"]


async def test_bulk_retire_is_one_idempotent_transaction_per_list(fresh_api):
    from labeling_support import score_now, scoring_on
    api = await fresh_api()
    first = await api.imported(candidates(pairs=150))
    other = await api.imported(candidates(pairs=10))
    free = await unsampled(api, [r for r in first if r["kind"] == "pair"])
    assert len(free) >= 110  # about 135 of 150 are outside the 10 % calibration sample
    elsewhere = (await unsampled(api, [r for r in other if r["kind"] == "pair"]))[:3]
    old, replacement = free[:70], free[70:110]
    lines = [gold_line(r, pool="qualification") for r in old[:60]] + [gold_line(r) for r in old[60:]]
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})).status_code \
        == 200
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True,
                              json={"rows": [gold_line(r) for r in elsewhere]})).status_code == 200
    retracted = old[-1]
    r = await api.request("PUT", f'/api/admin/gold/{retracted["corpus_id"]}/{retracted["item_id"]}', "curator", True,
                          json={"action": "retract", "reason": "test"})
    assert r.status_code == 200
    ids = [row["item_id"] for row in old] + [old[0]["item_id"], "00000000-0000-0000-0000-000000000001"]
    path = "/api/admin/gold/retire"
    # Only a curator, only with a reason; ids of several corpora need the corpus named.
    assert (await api.request("POST", path, "alice", json={"item_ids": ids, "reason": "x"})).status_code == 403
    assert (await api.request("POST", path, "curator", True, json={"item_ids": ids, "reason": " "})).status_code == 422
    mixed = ids + [elsewhere[0]["item_id"]]
    r = await api.request("POST", path, "curator", True, json={"item_ids": mixed, "reason": "zamjena"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "several_corpora"
    assert (await api.sql("SELECT count(*) FROM label_gold WHERE status = 'retired'")).scalar_one() == 0
    corpus = first[0]["corpus_id"]
    r = await api.request("POST", path, "curator", True,
                          json={"corpus_id": corpus, "item_ids": mixed, "reason": "zamjena"})
    assert r.status_code == 200
    assert r.json() == {"retired": 69, "already_retired": 0, "not_active": 1, "unknown": 2, "corpus_id": corpus}
    # The same events as one retire: a gold.retired with the reason per item, under the journal.
    events = (await api.sql("SELECT item_id, details FROM label_trust_event WHERE kind = 'gold.retired'")).all()
    assert len(events) == 69 and {e.details["reason"] for e in events} == {"zamjena"}
    mirror = {(str(g.item_id), g.status) for g in (await api.sql(
        "SELECT g.item_id, g.status FROM label_gold g JOIN label_trust_event e ON e.id = g.last_event_id "
        "WHERE g.corpus_id = :c", c=corpus)).all()}
    assert mirror == {(row["item_id"], "retired") for row in old[:69]} | {(retracted["item_id"], "retracted")}
    assert (await api.sql("SELECT status FROM label_gold WHERE item_id = :i", i=elsewhere[0]["item_id"])).scalar_one() \
        == "active"
    again = await api.request("POST", path, "curator", True, json={"corpus_id": corpus, "item_ids": ids,
                                                                     "reason": "zamjena"})
    assert again.json()["retired"] == 0 and again.json()["already_retired"] == 69
    # A replacement imported right after: its qualification rows fill the emptied pool again.
    lines = [gold_line(r, pool="qualification") for r in replacement[:30]] + [gold_line(r) for r in replacement[30:]]
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})
    assert r.status_code == 200 and r.json()["accepted"] == {"pair": {"qualification": 30, "audit": 10}}, r.json()
    await scoring_on(api)
    [(run_id, _)] = await score_now(api)
    ready = (await api.sql("SELECT readiness FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()
    # 30 + 0 in qualification, 10 + the 3 of the other corpus in audit: the retired rows count nowhere.
    assert ready["pair"]["pools"] == {"qualification": {"all": 30}, "audit": {"all": 13}, "wrong_suggestion": 0}

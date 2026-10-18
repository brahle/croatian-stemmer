"""The person's view of their trust data (4.10, 4.13.5): the card is simplified and silent
about quarantine; the export is complete, including the quarantine; neither marks
known-answer items still in use."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import (answer, answer_path, candidates, gold_line, later, profiled, score_now, unlimited,
                              unsampled)

pytestmark = pytest.mark.asyncio


async def quarantined_by_a_run(fresh_api):
    """X answers 32 pairs fast and identically: two hard flags, an automatic quarantine."""
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=40))
    await profiled(api, "x")
    for row in [r for r in rows if r["kind"] == "pair"][:32]:
        assert (await api.request("POST", answer_path(row), "x", json=answer(elapsed_ms=300))).status_code == 200
    await score_now(api)
    assert (await api.sql("SELECT status FROM label_annotator WHERE id = :a", a=await api.annotator_id("x"))
            ).scalar_one() == "quarantined"
    return api, rows


async def test_the_card_before_any_run_and_its_bands(fresh_api):
    api = await fresh_api()
    await profiled(api, "alice")
    card = (await api.request("GET", "/api/me/trust", "alice")).json()
    assert card["run"] is None and card["status"] == "active" and card["anchor"] is False
    assert card["explanation_url"] == "/legal/trust.hr"
    from croatian_stemmer.labeling.web.trust_view import band
    assert [band(0.9, 12), band(0.8, 30), band(0.6, 30), band(0.99, 11)] == [
        "visoka", "dobra", "treba_paznje", "nedovoljno_podataka"]


async def test_a_quarantine_is_silent_on_the_card_and_in_me(fresh_api):
    api, rows = await quarantined_by_a_run(fresh_api)
    card = (await api.request("GET", "/api/me/trust", "x")).json()
    assert card["status"] == "active" and card["status_reason"] is None
    assert card["kinds"]["pair"]["tier"] == "new" and card["kinds"]["pair"]["band"] == "nedovoljno_podataka"
    assert card["kinds"]["pair"]["checks_approx"] == 0
    me = (await api.request("GET", "/api/me", "x")).json()
    assert me["status"] == "active" and me["status_reason"] is None and me["trust_url"] == "/api/me/trust"
    # Labeling continues as before.
    item = (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/next', "x")).json()["item"]
    assert item is not None


async def test_the_export_shows_the_quarantine_and_every_signal(fresh_api):
    api, rows = await quarantined_by_a_run(fresh_api)
    trust = (await api.request("GET", "/api/me/export.json", "x")).json()["trust"]
    [run] = trust["runs"]
    pair = run["kinds"]["pair"]
    assert pair["tier"] == "quarantined" and pair["weight"] == 0.0 and pair["theta"] > 0.5
    assert pair["flags"]["fast"]["on"] and pair["flags"]["fast"]["median_ms"] == 300
    assert pair["flags"]["straight"]["on"] and pair["flags"]["straight"]["longest"] >= 12
    kinds = [e["kind"] for e in trust["events"]]
    assert "annotator.status" in kinds and "annotator.quarantined" in kinds
    status = next(e for e in trust["events"] if e["kind"] == "annotator.status")
    assert status["automatic"] and status["details"]["to"] == "quarantined"
    assert set(status["details"]["flags"]) == {"fast", "straight"}
    assert set(trust["meanings"]) >= {"tier", "theta", "weight", "flags", "known_answer_checks"}
    assert "checks on items still in use" in trust["not_included"]


async def test_a_blocked_person_sees_the_reason_and_the_full_export(fresh_api):
    api, rows = await quarantined_by_a_run(fresh_api)
    x = await api.annotator_id("x")
    await api.request("PUT", f"/api/admin/annotators/{x}/status", "curator", True,
                      json={"status": "blocked", "reason": "kopiranje"})
    card = (await api.request("GET", "/api/me/trust", "x")).json()
    assert card["status"] == "blocked" and card["status_reason"] == "kopiranje"
    export = (await api.request("GET", "/api/me/export.json", "x")).json()
    assert export["trust"]["runs"] and any(e["details"].get("reason") == "kopiranje" for e in export["trust"]["events"])


async def test_answers_on_retired_known_answer_items_are_marked_and_disclosed(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=10))
    free = await unsampled(api, [r for r in rows if r["kind"] == "pair"])
    lines = [gold_line(free[0]), gold_line(free[1])]
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})).status_code == 200
    await profiled(api, "alice")
    for row in free[:3]:
        assert (await api.request("POST", answer_path(row), "alice", json=answer())).status_code == 200
    r = await api.request("PUT", f'/api/admin/gold/{free[0]["corpus_id"]}/{free[0]["item_id"]}', "curator", True,
                          json={"action": "retire", "reason": "served"})
    assert r.status_code == 200
    export = (await api.request("GET", "/api/me/export.json", "alice")).json()
    marks = {j["item_id"]: j["checked_against_known_answer"] for j in export["judgments"]}
    assert marks == {free[0]["item_id"]: True, free[1]["item_id"]: False, free[2]["item_id"]: False}
    disclosed = (await api.sql("SELECT item_id::text FROM label_trust_event WHERE kind = 'gold.disclosed'")).scalars().all()
    assert disclosed == [free[0]["item_id"]]
    # A disclosed item can never return to a pool.
    r = await api.request("PUT", f'/api/admin/gold/{free[0]["corpus_id"]}/{free[0]["item_id"]}', "curator", True,
                          json={"action": "reactivate", "reason": "again"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "gold_disclosed"
    # Exporting again discloses nothing new.
    await api.request("GET", "/api/me/export.json", "alice")
    assert (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'gold.disclosed'")).scalar_one() == 1

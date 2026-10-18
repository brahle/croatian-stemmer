"""Determinism and replay (4.6.6): a run is reproduced from its restricted bundle alone, also
after later moderation and output deletion; privacy actions are reported, not hidden."""
import json

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.scoring import replay
from labeling_support import answer, answer_path, candidates, profiled, score_now

pytestmark = pytest.mark.asyncio


async def setup(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=4))
    for name in ("alice", "bob", "carol"):
        await profiled(api, name)
        for n, row in enumerate(r for r in rows if r["kind"] == "pair"):
            value = "same" if (n + len(name)) % 3 else "different"
            assert (await api.request("POST", answer_path(row), name, json=answer(value=value))).status_code == 200
    [(run_id, status)] = await score_now(api)
    assert status == "done"
    return api, rows, run_id


async def bundle_of(api, run_id):
    r = await api.request("GET", f"/api/admin/scoring/runs/{run_id}/bundle", "curator", True)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment;")
    data = r.json()
    assert "audit_key" not in r.text and data["run"]["id"] == str(run_id)
    return data


async def test_the_online_run_and_its_offline_replay_agree(fresh_api, tmp_path, capsys):
    from croatian_stemmer.labeling.__main__ import main
    api, rows, run_id = await setup(fresh_api)
    data = await bundle_of(api, run_id)
    result = replay(data)
    assert result["report"]["inputs_match"] and result["report"]["outputs_match"]
    stored = (await api.sql("SELECT outputs_sha256 FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()
    assert result["report"]["outputs_sha256"] == stored
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps(data))
    main(["score", "--bundle", str(tmp_path), "--output", str(tmp_path / "out.json")])
    report = json.loads(capsys.readouterr().out)
    assert report["outputs_match"] is True and (tmp_path / "out.json").exists()
    assert (await api.request("GET", f"/api/admin/scoring/runs/{run_id}/bundle", "alice")).status_code == 403


async def test_replay_survives_later_moderation_output_deletion_and_imports(fresh_api):
    api, rows, run_id = await setup(fresh_api)
    bob = await api.annotator_id("bob")
    await api.request("PUT", f"/api/admin/annotators/{bob}/status", "curator", True,
                      json={"status": "blocked", "reason": "later"})
    await api.request("PUT", f'/api/admin/gold/{rows[0]["corpus_id"]}/{rows[0]["item_id"]}', "curator", True,
                      json={"action": "set", "pool": "audit", "answer": "different", "reason": "later"})
    await api.imported(candidates(pairs=2))
    row = next(r for r in rows if r["kind"] == "lemma")
    await api.request("POST", answer_path(row), "alice", json=answer(value="confirmed", lemma="kuća"))
    await score_now(api)
    for table in ("label_annotator_score", "label_item_posterior"):
        await api.sql(f"DELETE FROM {table}")
    result = replay(await bundle_of(api, run_id))
    assert result["report"]["inputs_match"] and result["report"]["outputs_match"]


async def test_replay_after_an_erasure_reports_the_changed_inputs(fresh_api):
    api, rows, run_id = await setup(fresh_api)
    assert (await api.request("POST", "/api/me/erase", "bob", json={"confirm": "DELETE"})).status_code == 200
    report = replay(await bundle_of(api, run_id))["report"]
    assert report["inputs_match"] is False and report["outputs_match"] is None
    changed = {c["journal"] for c in report["changed"]}
    assert {"judgments", "consents"} <= changed


async def test_the_bundle_holds_no_reasons_and_no_keycloak_ids(fresh_api):
    api, rows, _ = await setup(fresh_api)
    alice, carol = await api.annotator_id("alice"), await api.annotator_id("carol")
    await api.request("PUT", f"/api/admin/annotators/{alice}/status", "curator", True,
                      json={"status": "blocked", "reason": "tajni-razlog-1"})
    subject = api.identity.subjects["carol"]
    assert (await api.request("POST", "/api/me/erase", "carol", json={"confirm": "DELETE"})).status_code == 200
    [(run_id, _)] = await score_now(api)
    text_ = (await api.request("GET", f"/api/admin/scoring/runs/{run_id}/bundle", "curator", True)).text
    assert "tajni-razlog-1" not in text_ and subject not in text_
    assert replay(json.loads(text_))["report"]["outputs_match"]

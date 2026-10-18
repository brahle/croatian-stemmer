"""Restricted exports of a run and the path to a public release (4.11)."""
import csv
import io
import json

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.release import build, check
from labeling_support import answer, answer_path, pair_rows, profiled, score_now, unlimited

pytestmark = pytest.mark.asyncio


async def adjudicated(fresh_api):
    """Five low votes put an item in needs_expert; the curator adjudicates it."""
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(6, different_every=0))
    target = rows[0]
    for n in range(5):
        await profiled(api, f"p{n}")
        assert (await api.request("POST", answer_path(target), f"p{n}", json=answer())).status_code == 200
    await score_now(api)
    r = await api.request("POST", f'/api/admin/items/{target["corpus_id"]}/{target["item_id"]}/adjudicate', "curator",
                          True, json={"answer": "same", "reason": "settled"})
    assert r.status_code == 200
    [(run_id, _)] = await score_now(api)
    return api, rows, target, run_id


async def test_resolved_exports_and_a_release(fresh_api, tmp_path):
    api, rows, target, run_id = await adjudicated(fresh_api)
    corpus = target["corpus_id"]
    r = await api.request("GET", f"/api/corpora/{corpus}/resolved.tsv", "curator", True)
    assert r.status_code == 200 and r.headers["x-labeling-run-stale"] == "false"
    table = list(csv.DictReader(io.StringIO(r.text), delimiter="\t"))
    row = next(x for x in table if x["item_id"] == target["item_id"])
    assert (row["schema_version"], row["state"], row["resolution_source"], row["resolved_answer"]) == (
        "2", "resolved", "adjudication", "same")
    assert row["run_id"] == str(run_id) and row["word_ref"] == target["word_ref"] and json.loads(row["classes_json"])
    r = await api.request("GET", f"/api/corpora/{corpus}/resolved.jsonl", "curator", True)
    lines = [json.loads(line) for line in r.text.splitlines()]
    assert lines[0]["record"] == "run" and lines[0]["run"]["id"] == str(run_id)
    record = next(x for x in lines[1:] if x["item_id"] == target["item_id"])
    assert len(record["votes"]) == 5 and {"annotator_id", "tier", "weight"} <= set(record["votes"][0])
    assert "created_at" not in json.dumps(record["votes"])
    people = await api.request("GET", "/api/admin/annotators/export.jsonl", "curator", True)
    assert people.status_code == 200 and "@" not in people.text
    for route in (f"/api/corpora/{corpus}/resolved.tsv", f"/api/corpora/{corpus}/resolved.jsonl",
                  "/api/admin/annotators/export.jsonl"):
        assert (await api.request("GET", route, "p0")).status_code == 403
    # Pin, record the release, build it from the export and check it.
    assert (await api.request("POST", f"/api/admin/scoring/runs/{run_id}/pin", "curator", True)).status_code == 200
    released = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True)
    assert released.status_code == 200 and released.json()["disclosed"] == 0
    pinned = await api.request("GET", f"/api/corpora/{corpus}/resolved.jsonl", "curator", True,
                               params={"run_id": str(run_id)})
    (tmp_path / "run.jsonl").write_text(pinned.text, encoding="utf-8")
    (tmp_path / "annotators.jsonl").write_text(people.text, encoding="utf-8")
    build(tmp_path / "run.jsonl", tmp_path / "release")
    labels = (tmp_path / "release" / "labels.tsv").read_text(encoding="utf-8")
    assert target["item_id"] in labels
    assert check(tmp_path / "release", tmp_path / "run.jsonl", tmp_path / "annotators.jsonl")["ok"]
    # A later block makes the run stale: exports say so, and a release is refused.
    p0 = await api.annotator_id("p0")
    await api.request("PUT", f"/api/admin/annotators/{p0}/status", "curator", True,
                      json={"status": "blocked", "reason": "x"})
    r = await api.request("GET", f"/api/corpora/{corpus}/resolved.tsv", "curator", True, params={"run_id": str(run_id)})
    assert r.headers["x-labeling-run-stale"] == "true"
    refused = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "run_stale"


async def test_an_erased_voter_still_counts_in_the_next_release(fresh_api, tmp_path):
    api, rows, target, run_id = await adjudicated(fresh_api)
    assert (await api.request("POST", "/api/me/erase", "p1", json={"confirm": "DELETE"})).status_code == 200
    [(after, _)] = await score_now(api)
    assert (await api.request("POST", f"/api/admin/scoring/runs/{after}/pin", "curator", True)).status_code == 200
    r = await api.request("GET", f'/api/corpora/{target["corpus_id"]}/resolved.jsonl', "curator", True,
                          params={"run_id": str(after)})
    record = next(json.loads(line) for line in r.text.splitlines()[1:] if json.loads(line)["item_id"] == target["item_id"])
    assert len(record["votes"]) == 5  # the erased person's answer counts under the new identifier
    (tmp_path / "run.jsonl").write_text(r.text, encoding="utf-8")
    build(tmp_path / "run.jsonl", tmp_path / "release")
    assert target["item_id"] in (tmp_path / "release" / "labels.tsv").read_text(encoding="utf-8")


async def test_outputs_past_their_retention_are_replayed_instead(fresh_api):
    api, rows, target, run_id = await adjudicated(fresh_api)
    await api.sql("DELETE FROM label_item_posterior WHERE run_id = :r", r=run_id)
    await api.sql("DELETE FROM label_annotator_score WHERE run_id = :r", r=run_id)
    r = await api.request("GET", f'/api/corpora/{target["corpus_id"]}/resolved.tsv', "curator", True,
                          params={"run_id": str(run_id)})
    assert r.status_code == 410 and r.json()["detail"]["code"] == "run_outputs_expired"

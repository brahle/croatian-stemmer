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


async def test_an_item_that_became_an_active_check_after_the_pinned_run_is_never_published(fresh_api, tmp_path):
    """Run R resolves X; the anchor's later answer makes X consensus gold in the next run (a run's
    own decision: R does not go stale). Exporting R must not publish X, release-check must refuse
    it, and recording the release must neither publish nor disclose it."""
    from labeling_support import make_anchor, unseeded
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(10, different_every=0))
    await make_anchor(api, "owner")
    target = (await unseeded(api, rows))[0]
    for n in range(5):
        await profiled(api, f"p{n}")
        assert (await api.request("POST", answer_path(target), f"p{n}", json=answer())).status_code == 200
    await score_now(api)
    r = await api.request("POST", f'/api/admin/items/{target["corpus_id"]}/{target["item_id"]}/adjudicate', "curator",
                          True, json={"answer": "same", "reason": "settled"})
    assert r.status_code == 200
    [(run_id, _)] = await score_now(api)
    assert (await api.request("POST", f"/api/admin/scoring/runs/{run_id}/pin", "curator", True)).status_code == 200
    # The owner's answer differs from the suggestion: the next run makes X an active check.
    assert (await api.request("POST", answer_path(target), "owner", json=answer(value="different"))).status_code == 200
    await score_now(api)
    assert (await api.sql("SELECT status, pool FROM label_gold WHERE item_id = :i", i=target["item_id"])).one() \
        == ("active", "audit")
    detail = (await api.request("GET", f"/api/admin/scoring/runs/{run_id}", "curator", True)).json()
    assert detail["stale"] is False
    export = await api.request("GET", f'/api/corpora/{target["corpus_id"]}/resolved.jsonl', "curator", True,
                               params={"run_id": str(run_id)})
    record = next(json.loads(line) for line in export.text.splitlines()[1:]
                  if json.loads(line)["item_id"] == target["item_id"])
    assert record["gold_status"] is None and record["gold_status_now"] == "active"
    (tmp_path / "run.jsonl").write_text(export.text, encoding="utf-8")
    build(tmp_path / "run.jsonl", tmp_path / "release")
    labels = (tmp_path / "release" / "labels.tsv").read_text(encoding="utf-8")
    assert target["item_id"] not in labels
    # A release that includes it anyway is refused by the check and by the route.
    lines = labels.splitlines()
    header = lines[0].split("\t")
    forged = dict(zip(header, [""] * len(header)), item_id=target["item_id"], resolution_source="adjudication")
    (tmp_path / "release" / "labels.tsv").write_text(labels + "\t".join(forged[h] for h in header) + "\n",
                                                     encoding="utf-8")
    with pytest.raises(ValueError, match="known-answer item still in use"):
        check(tmp_path / "release", tmp_path / "run.jsonl")
    refused = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True,
                                json={"item_ids": [target["item_id"]]})
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "gold_in_use"
    recorded = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True)
    assert recorded.status_code == 200 and recorded.json()["disclosed"] == 0
    assert (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'gold.disclosed'")).scalar_one() == 0


async def test_the_release_route_never_releases_or_discloses_a_reserve_item(fresh_api):
    """A gold-reserve item (its decoy suggestion is wrong on purpose) is never released, so
    recording a release refuses it and never discloses its (even retired) gold."""
    api, rows, target, _ = await adjudicated(fresh_api)
    where = {"c": target["corpus_id"], "i": target["item_id"]}
    await api.sql("UPDATE label_item_state SET reserve = true WHERE corpus_id = :c AND item_id = :i", **where)
    for kind, details in (("gold.set", {"pool": "audit", "answer": "same", "lemma": "", "source": "hr500k",
                                        "basis": "test", "batch": None, "suggestion_agrees": True}),
                          ("gold.retired", {"reason": "served_out"})):
        event = (await api.sql("INSERT INTO label_trust_event (kind, corpus_id, item_id, details) "
                               "VALUES (:k, :c, :i, CAST(:d AS jsonb)) RETURNING id", k=kind,
                               d=json.dumps(details), **where)).scalar_one()
    await api.sql("INSERT INTO label_gold (corpus_id, item_id, kind, pool, answer, lemma, source, suggestion_agrees, "
                  "status, last_event_id) VALUES (:c, :i, 'pair', 'audit', 'same', '', 'hr500k', true, 'retired', :e)",
                  e=event, **where)
    [(run_id, _)] = await score_now(api)
    assert (await api.sql("SELECT state FROM label_item_posterior WHERE run_id = :r AND item_id = :i",
                          r=run_id, i=target["item_id"])).scalar_one() == "resolved"
    assert (await api.request("POST", f"/api/admin/scoring/runs/{run_id}/pin", "curator", True)).status_code == 200
    refused = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True,
                                json={"item_ids": [target["item_id"]]})
    assert refused.status_code == 409 and refused.json()["detail"] == {"code": "reserve_item",
                                                                      "items": [target["item_id"]]}
    recorded = await api.request("POST", f"/api/admin/scoring/runs/{run_id}/release", "curator", True)
    assert recorded.status_code == 200 and recorded.json()["disclosed"] == 0

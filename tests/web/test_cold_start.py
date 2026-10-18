"""The launch from nothing (4.16): default parameters, one anchor, no established annotator,
an empty stem pool and the builder's real split for pair and lemma. Readiness turns on
kind by kind as the anchor's seed answers become gold; nothing is model-resolved before
a calibration cell passes; the anchor's work stays within the 2-3 hours of 4.16.2."""
import json

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.candidates import prepare
from croatian_stemmer.labeling.gold import build
from labeling_support import (answer, answer_path, later, make_anchor, profiled, score_now, scoring_on,
                              synthetic_conllu, unlimited)

pytestmark = [pytest.mark.asyncio, pytest.mark.slow]
WORKLOAD = 365  # the anchor's answers in the table of 4.16.2


async def readiness(api, run_id):
    return (await api.sql("SELECT readiness FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()


async def run_twice(api, **kwargs):
    """A run decides new gold from the anchor's answers; the next one sees it in its pools."""
    await score_now(api, **kwargs)
    [(run_id, _)] = await score_now(api, **kwargs)
    return run_id


async def serve(api, name, corpus, kind, decide, limit):
    """Take what /next serves `name` and answer with decide(served) until `limit` answers or nothing is left."""
    served_ids = []
    for _ in range(limit):
        served = (await api.request("GET", f"/api/corpora/{corpus}/next", name, params={"kind": kind})).json()
        if served["item"] is None:
            break
        candidate = served["item"]["candidate"]
        value, lemma = decide(served)
        r = await api.request("POST", answer_path(candidate), name, fetched=False,
                              json=answer(value=value, lemma=lemma, elapsed_ms=6000))
        assert r.status_code == 200, r.text
        served_ids.append(candidate["item_id"])
    return served_ids


async def test_the_launch(fresh_api, tmp_path):
    api = unlimited(await fresh_api())
    corpus_file = synthetic_conllu(tmp_path / "corpus.conllu", lemmas=200)
    records, _ = prepare(corpus_file, source_uri="urn:test:cold-start", license="CC BY-SA 4.0", pair_count=1500,
                         word_count=500, seed=2)
    (tmp_path / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    lines, receipt = build(corpus_file, tmp_path / "candidates.jsonl")  # default --per-kind 400, qualification=80
    assert {(r["kind"], r["pool"]) for r in lines} == {("pair", "qualification"), ("pair", "audit"),
                                                      ("lemma", "qualification"), ("lemma", "audit")}
    for start in range(0, len(records), 5000):
        r = await api.request("POST", "/api/import", "curator", True,
                              json={"name": "Hladni start", "candidates": records[start:start + 5000]})
        assert r.status_code == 200
    corpus = records[0]["corpus_id"]
    assert (await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True,
                              json={"labels_license": "CC BY-SA 4.0"})).status_code == 200
    imported = (await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})).json()
    assert imported["accepted"]["pair"]["qualification"] == 60 and imported["accepted"]["lemma"]["qualification"] == 60
    assert imported["held_out"] > 0
    owner = await make_anchor(api, "owner")
    await scoring_on(api)
    by_id = {r["item_id"]: r for r in records}
    owner_answers = 0

    [(run_id, _)] = await score_now(api)
    ready = await readiness(api, run_id)
    for kind in ("pair", "lemma"):
        assert ready[kind]["qualification"] and ready[kind]["audit"] and not ready[kind]["promotion"]
        assert not ready[kind]["copy_flag"]
    assert not any(ready["stem"][name] for name in ("qualification", "audit", "promotion"))

    # Stem: the anchor's seed answers fill the qualification pool, then the audit pool, both balanced.
    turn = iter(range(10 ** 6))
    decide_stem = lambda served: (("accept", "reject")[next(turn) % 2], "")
    seeded = await serve(api, "owner", corpus, "stem", decide_stem, 16)
    owner_answers += len(seeded)
    assert len(seeded) == 16 and all(by_id[i]["kind"] == "stem" for i in seeded)
    run_id = await run_twice(api)
    ready = await readiness(api, run_id)
    assert ready["stem"]["qualification"] and not ready["stem"]["audit"]
    seeded = await serve(api, "owner", corpus, "stem", decide_stem, 30)
    owner_answers += len(seeded)
    run_id = await run_twice(api)
    ready = await readiness(api, run_id)
    assert ready["stem"]["audit"] and ready["stem"]["promotion"]
    # No more stem seed work once the pools are full.
    assert (await api.sql("SELECT count(*) FROM label_gold WHERE kind = 'stem'")).scalar_one() == 46

    # Pair: promotion and the copy flag wait for 15 items where the suggestion is wrong.
    def against_suggestion(served):
        row = by_id[served["item"]["candidate"]["item_id"]]
        return ("different" if row["proposed_lemma"] == row["other_proposed_lemma"] else "same"), ""
    seeded = await serve(api, "owner", corpus, "pair", against_suggestion, 15)
    owner_answers += len(seeded)
    run_id = await run_twice(api)
    ready = await readiness(api, run_id)
    assert ready["pair"]["promotion"] and ready["pair"]["copy_flag"]

    # An ordinary contributor passes stem qualification and reaches `established` on the
    # stem hard-item floor (both classes); the gold answers come from the anchor.
    gold = {(r.item_id, r.answer) for r in (await api.sql(
        "SELECT item_id::text, answer FROM label_gold WHERE kind = 'stem' ORDER BY pool DESC, item_id")).all()}
    await profiled(api, "c")
    await profiled(api, "v")
    for item_id, value in sorted(gold):
        assert (await api.request("POST", answer_path(by_id[item_id]), "c", json=answer(value=value))).status_code == 200
    # The second voter passes stem qualification too (a `new` voter's 0.75 ceiling and an
    # established one's 0.86 give 0.9499 on two agreeing votes: just short of the rule).
    qualification = [r.item_id for r in (await api.sql(
        "SELECT item_id::text FROM label_gold WHERE kind = 'stem' AND pool = 'qualification'")).all()]
    for item_id in qualification:
        value = dict(gold)[item_id]
        assert (await api.request("POST", answer_path(by_id[item_id]), "v", json=answer(value=value))).status_code == 200
    stems = [r for r in records if r["kind"] == "stem" and r["item_id"] not in {g for g, _ in gold}]
    sampled = {str(r[0]) for r in (await api.sql(
        "SELECT item_id FROM label_item_audit WHERE corpus_id = :c AND audit_sample", c=corpus)).all()}
    in_sample = [r for r in stems if r["item_id"] in sampled][:30]
    plain = [r for r in stems if r["item_id"] not in sampled]
    assert len(in_sample) == 30
    for n, row in enumerate(plain[:60]):  # enough definite answers, without long runs
        value = ("accept", "reject")[n % 2]
        assert (await api.request("POST", answer_path(row), "c", json=answer(value=value))).status_code == 200
        assert (await api.request("POST", answer_path(row), "v", json=answer(value=value))).status_code == 200
    for n, row in enumerate(in_sample):
        value = ("accept", "reject")[n % 2]
        for name in ("c", "v"):
            assert (await api.request("POST", answer_path(row), name, json=answer(value=value))).status_code == 200
    run_id = await run_twice(api, as_of_day=later())
    tier = (await api.sql("SELECT tier FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a "
                          "AND kind = 'stem'", r=run_id, a=await api.annotator_id("c"))).scalar_one()
    assert tier == "established"
    calibration = (await api.sql("SELECT calibration FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()
    stem_cell = calibration["stem/none"]
    assert stem_cell["n"] == 30 and len(stem_cell["pending"]) == 30 and not stem_cell["passed"]
    states = {r.state for r in (await api.sql(
        "SELECT p.state FROM label_item_posterior p JOIN label_item i ON i.corpus_id = p.corpus_id AND i.id = p.item_id "
        "WHERE p.run_id = :r AND i.kind = 'stem' AND p.resolution_source = 'model'", r=run_id)).all()}
    assert states <= {"provisional"}  # nothing model-resolved before the cell calibrates

    # The anchor's audit queue serves the evaluation set; references agreeing with the crowd calibrate it.
    pending = {tuple(item)[1] for item in stem_cell["pending"]}
    expected = {row["item_id"]: ("accept", "reject")[n % 2] for n, row in enumerate(in_sample)}
    referenced = await serve(api, "owner", corpus, "stem", lambda served: (expected[
        served["item"]["candidate"]["item_id"]], ""), 30)
    owner_answers += len(referenced)
    assert set(referenced) == pending and all(i in sampled for i in referenced)
    run_id = await run_twice(api, as_of_day=later())
    calibration = (await api.sql("SELECT calibration FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()
    assert calibration["stem/none"]["passed"]
    resolved = (await api.sql(
        "SELECT count(*) FROM label_item_posterior p JOIN label_item i ON i.corpus_id = p.corpus_id AND i.id = p.item_id "
        "WHERE p.run_id = :r AND i.kind = 'stem' AND p.state = 'resolved' AND p.resolution_source = 'model'",
        r=run_id)).scalar_one()
    assert resolved >= 50
    # Pair and lemma remain provisional: their cells have not calibrated.
    model = (await api.sql(
        "SELECT p.state FROM label_item_posterior p JOIN label_item i ON i.corpus_id = p.corpus_id AND i.id = p.item_id "
        "WHERE p.run_id = :r AND i.kind <> 'stem' AND p.resolution_source = 'model'", r=run_id)).scalars().all()
    assert "resolved" not in model
    total = (await api.sql("SELECT count(*) FROM label_judgment WHERE annotator_id = :a", a=owner)).scalar_one()
    assert total == owner_answers <= WORKLOAD

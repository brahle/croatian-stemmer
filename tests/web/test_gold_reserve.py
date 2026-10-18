"""Gold-reserve items (prepare --gold-reserve): an additive candidates file for a corpus that
is already imported, gold whose answer differs from the suggestion built from corpus truth,
and reserve items that are never served as ordinary or expert work (0.3.4)."""
import json

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.candidates import is_reserve, prepare
from croatian_stemmer.labeling.gold import build
from labeling_support import answer, answer_path, make_anchor, profiled, score_now, scoring_on, synthetic_conllu, \
    unlimited

pytestmark = pytest.mark.asyncio


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


async def imported(api, rows, name="Rezerva"):
    r = await api.request("POST", "/api/import", "curator", True, json={"name": name, "candidates": rows})
    assert r.status_code == 200, r.text
    return r.json()


async def readiness(api):
    [(run_id, _)] = await score_now(api)
    return (await api.sql("SELECT readiness FROM label_scoring_run WHERE id = :r", r=run_id)).scalar_one()


async def test_a_supplement_fills_the_wrong_suggestion_pools(fresh_api, tmp_path):
    api = unlimited(await fresh_api())
    corpus_file = synthetic_conllu(tmp_path / "corpus.conllu", lemmas=120)
    provenance = dict(source_uri="urn:test:supplement", license="CC BY-SA 4.0")
    records, _ = prepare(corpus_file, **provenance, pair_count=400, word_count=100, seed=2)
    candidates = write(tmp_path / "candidates.jsonl", records)
    assert (await imported(api, records))["added"] == len(records)
    corpus = records[0]["corpus_id"]
    assert (await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True,
                              json={"labels_license": "CC BY-SA 4.0"})).status_code == 200
    first, receipt = build(corpus_file, candidates, per_kind=200)
    assert receipt["coverage"]["kinds"]["pair"]["wrong_suggestion"]["rows"] == 0
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": first})
    assert r.status_code == 200, r.text
    await scoring_on(api)
    await make_anchor(api, "owner")
    ready = await readiness(api)
    assert not ready["pair"]["wrong_suggestion"] and not ready["pair"]["promotion"]

    # The supplement: new item ids of the same corpus, added to it; a repeat import is a no-op.
    extra, _ = prepare(corpus_file, **provenance, pair_count=0, word_count=0, gold_reserve_size=60, supplement=records)
    supplement = write(tmp_path / "extra.jsonl", extra)
    added = await imported(api, extra, name="Dopuna")
    assert added["added"] == len(extra) and added["already_present"] == 0
    again = await imported(api, records + extra)
    assert again["added"] == 0 and again["already_present"] == len(records) + len(extra)
    other = [{**row, "license": "CC BY 4.0"} for row in extra[:1]]
    r = await api.request("POST", "/api/import", "curator", True, json={"name": "x", "candidates": other})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "corpus_provenance_conflict"
    total = (await api.sql("SELECT count(*) FROM label_item WHERE corpus_id = :c", c=corpus)).scalar_one()
    assert total == len(records) + len(extra)

    # A second gold file, built --with the first, on the original candidates plus the supplement.
    second, receipt = build(corpus_file, [candidates, supplement], existing=first, per_kind=100, qualification=0)
    assert not {row["item_id"] for row in second} & {row["item_id"] for row in first}
    wrong = {row["item_id"] for row in second if row["basis"].endswith("_against_suggestion")}
    assert len(wrong) == 60
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": second})
    assert r.status_code == 200, r.text
    stored = {str(row.item_id): row.suggestion_agrees for row in (await api.sql(
        "SELECT item_id, suggestion_agrees FROM label_gold WHERE corpus_id = :c", c=corpus)).all()}
    # The server recomputes agreement from the stored suggestion: exactly the decoys disagree.
    assert {item for item, agrees in stored.items() if agrees is False} == wrong & set(stored)
    # Importing the first file again changes nothing.
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": first})
    assert r.json()["accepted"] == {} and r.json()["unchanged"] + r.json()["held_out"] == len(first)
    ready = await readiness(api)
    for kind in ("pair", "lemma"):
        assert ready[kind]["wrong_suggestion"] and ready[kind]["copy_flag"] and ready[kind]["promotion"], kind


async def test_reserve_items_are_never_ordinary_or_expert_work(fresh_api, tmp_path):
    api = unlimited(await fresh_api())
    corpus_file = synthetic_conllu(tmp_path / "corpus.conllu", lemmas=40)
    records, _ = prepare(corpus_file, source_uri="urn:test:supplement", license="CC BY-SA 4.0", pair_count=30,
                         word_count=10, seed=1, gold_reserve_size=8)
    reserve = {row["item_id"] for row in records if is_reserve(row["sampling_stratum"])}
    assert len(reserve) == 32
    await imported(api, records)
    corpus = records[0]["corpus_id"]
    await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True, json={"labels_license": "CC BY-SA 4.0"})

    async def everything(name, kind, value):
        served = []
        for _ in range(200):
            item = (await api.request("GET", f"/api/corpora/{corpus}/next", name, params={"kind": kind})).json()["item"]
            if item is None:
                return served
            row = item["candidate"]
            assert "sampling_stratum" not in row  # never shown to annotators
            r = await api.request("POST", answer_path(row), name, fetched=False,
                                  json=answer(value=value, lemma="lemaa" if kind == "lemma" else ""))
            assert r.status_code == 200, r.text
            served.append(row["item_id"])
        raise AssertionError("the queue did not end")

    # Before scoring (the V1 order) and with the trust scheduler, for a contributor and an anchor.
    await profiled(api, "alice")
    ordinary = {kind: {r["item_id"] for r in records if r["kind"] == kind and r["item_id"] not in reserve}
                for kind in ("pair", "lemma")}
    assert set(await everything("alice", "pair", "same")) == ordinary["pair"]
    counts = (await api.request("GET", f"/api/corpora/{corpus}/progress", "alice")).json()["kinds"]
    assert counts["pair"]["total"] == 30 and counts["lemma"]["total"] == 10
    await scoring_on(api)
    await score_now(api)
    await profiled(api, "bob")
    assert set(await everything("bob", "lemma", "confirmed")) == ordinary["lemma"]
    await make_anchor(api, "owner")  # the seed queue runs while the suggestion-wrong pool is empty
    assert not set(await everything("owner", "lemma", "confirmed")) & reserve
    assert not set(await everything("owner", "pair", "different")) & reserve


async def test_item_detail_never_returns_an_unserved_reserve_item(fresh_api, tmp_path):
    api = unlimited(await fresh_api())
    corpus_file = synthetic_conllu(tmp_path / "corpus.conllu", lemmas=30)
    records, _ = prepare(corpus_file, source_uri="urn:test:supplement", license="CC BY-SA 4.0", pair_count=10,
                         word_count=4, gold_reserve_size=4)
    await imported(api, records)
    corpus = records[0]["corpus_id"]
    await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True, json={"labels_license": "CC BY-SA 4.0"})
    await profiled(api, "alice")
    reserve = next(r for r in records if is_reserve(r["sampling_stratum"]))
    plain = next(r for r in records if not is_reserve(r["sampling_stratum"]))
    path = lambda r: f'/api/corpora/{corpus}/items/{r["item_id"]}'
    assert (await api.request("GET", path(plain), "alice")).status_code == 200
    missing = await api.request("GET", f"/api/corpora/{corpus}/items/00000000-0000-0000-0000-000000000000", "alice")
    hidden = await api.request("GET", path(reserve), "alice")
    assert hidden.status_code == 404 and hidden.json() == missing.json()
    await api.consent("curator", True)
    assert (await api.request("GET", path(reserve), "curator", True)).status_code == 200
    # Once served (as a check), it is the person's item like any other.
    await api.sql("INSERT INTO label_assignment (annotator_id, corpus_id, item_id, first_shown_at, last_shown_at, "
                  "shown_count, presentation) VALUES (:a, :c, :i, now(), now(), 1, 'shown')",
                  a=await api.annotator_id("alice"), c=corpus, i=reserve["item_id"])
    assert (await api.request("GET", path(reserve), "alice")).status_code == 200


async def test_reserve_items_are_not_open_work_in_counts_or_corpus_order(fresh_api, tmp_path):
    api = unlimited(await fresh_api())
    corpora = []
    for name, lemmas, pairs, reserve in (("x", 30, 2, 10), ("y", 31, 4, 0)):
        path = synthetic_conllu(tmp_path / f"{name}.conllu", lemmas=lemmas)
        rows, _ = prepare(path, source_uri="urn:test:supplement", license="CC BY-SA 4.0", pair_count=pairs,
                          word_count=0, gold_reserve_size=reserve)
        await imported(api, rows, name=name)
        corpus = rows[0]["corpus_id"]
        await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True,
                          json={"labels_license": "CC BY-SA 4.0"})
        ordinary = [r for r in rows if r["kind"] == "pair" and not is_reserve(r["sampling_stratum"])]
        await api.sql("UPDATE label_item_state SET state = 'resolved' WHERE item_id = :i", i=ordinary[0]["item_id"])
        corpora.append((corpus, rows))
    (x, x_rows), (y, _) = corpora
    overview = (await api.request("GET", "/api/admin/overview", "curator", True)).json()
    states = {c["id"]: c["kinds"]["pair"] for c in overview["corpora"]}
    reserve_pairs = sum(r["kind"] == "pair" and is_reserve(r["sampling_stratum"]) for r in x_rows)
    assert states[x] == {"open": 1, "resolved": 1, "reserve": reserve_pairs}
    assert states[y] == {"open": 3, "resolved": 1}
    # /api/next starts with the corpus with the lowest resolved share of real work: y (1/4), not x (1/2).
    await profiled(api, "alice")
    served = (await api.request("GET", "/api/next", "alice", params={"kind": "pair"})).json()
    assert served["item"]["candidate"]["corpus_id"] == y

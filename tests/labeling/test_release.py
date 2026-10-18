"""Public releases (4.11.2): aggregate labels only; release-check fails closed on every leak."""
import json
import math
from datetime import date
from uuid import uuid4

import pytest

from croatian_stemmer.labeling.__main__ import main
from croatian_stemmer.labeling.release import build, check
from croatian_stemmer.labeling.scoring import DEFAULT_PARAMS, model_rule, release_rule, validate_params, weight

PARAMS = validate_params({**DEFAULT_PARAMS, "class_prior": "uniform"})
CORPUS = str(uuid4())
PRIOR = [["same", math.log(0.5)], ["different", math.log(0.5)]]


def item(votes, source="model", state="resolved", gold=None, pool=None, answer=None):
    """A run-export item record. votes: [(tier, answer, theta)]; ids are fresh annotators."""
    rows = [{"annotator_id": str(uuid4()), "tier": tier, "class": value, "weight": weight(theta, 2), "answer": value,
             "lemma": "", "irregular": False, "presentation": "shown", "admitted": True} for tier, value, theta in votes]
    tiers = {v["annotator_id"]: v["tier"] for v in rows}
    triples = [(v["annotator_id"], v["class"], v["weight"]) for v in rows]
    crowd = [t for t, v in zip(triples, rows) if v["tier"] != "anchor"]
    met, winner, probs = model_rule([tuple(p) for p in PRIOR], triples, 2, tiers, PARAMS)
    checked = source == "model"
    # An adjudication is releasable as the curator's decision; other rows need three voters, none pivotal.
    ok = source == "adjudication" or release_rule([tuple(p) for p in PRIOR], triples if checked else crowd, 2, tiers,
                                                  PARAMS)
    item_id = str(uuid4())
    return {"record": "item", "corpus_id": CORPUS, "item_id": item_id, "kind": "pair",
            "candidate": {"word": "kuće", "other_word": "kuća", "upos": "NOUN", "context": "Sintetički primjer.",
                          "other_context": "", "word_ref": "test:1", "other_word_ref": "test:2",
                          "proposed_lemma": "kuća", "other_proposed_lemma": "kuća", "proposed_stem": ""},
            "state": state, "releasable": ok, "resolution_source": source if state == "resolved" else None,
            "cell": "agrees", "resolved_answer": answer or winner, "resolved_lemma": "",
            "confidence": probs[winner] if probs else None, "classes": [], "epoch": 0,
            "n_definite": len(rows), "n_annotators": len(rows), "gold_status": gold, "gold_pool": pool,
            "k": 2, "prior": PRIOR, "votes": rows}


def export(tmp_path, items, pinned=True, stale=False, name="resolved.jsonl"):
    run = {"record": "run", "run": {"id": str(uuid4()), "scoring_version": "2.0", "params": PARAMS,
                                    "params_sha256": "p" * 64, "watermark": 9, "as_of_day": "2026-10-18",
                                    "finished_at": "2026-10-18T10:00:00+00:00", "pinned": pinned, "stale": stale,
                                    "calibration": {"pair/agrees": {"kind": "pair", "cell": "agrees", "n": 30,
                                                                    "correct": 30, "passed": True}},
                                    "inputs_changed": False},
           "corpus": {"id": CORPUS, "name": "Sintetički", "sha256": "a" * 64, "source_uri": "urn:test:release",
                      "license": "CC BY-SA 4.0", "labels_license": "CC BY-SA 4.0"}}
    path = tmp_path / name
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [run, *items]), encoding="utf-8")
    return path


def labels(directory):
    lines = (directory / "labels.tsv").read_text(encoding="utf-8").splitlines()
    header = lines[0].split("\t")
    return [dict(zip(header, line.split("\t"))) for line in lines[1:]]


E = 0.85  # an established voter at θ = 0.85


def fixture_items():
    return {"three": item([("established", "same", E)] * 3),
            "adjudicated": item([("new", "same", 0.75)], source="adjudication", answer="different"),
            "reference": item([("established", "same", 0.999)] * 3 + [("anchor", "different", 0.98)],
                              source="reference", answer="different"),
            "review": item([("established", "same", E)] * 3 + [("anchor", "same", 0.98)], source="review"),
            "two": item([("established", "same", E)] * 2),
            "pivotal": item([("established", "same", 0.95), ("new", "same", 0.75), ("new", "same", 0.75)]),
            "gold": item([("established", "same", E)] * 3, gold="active", pool="audit"),
            "qualification": item([("established", "same", E)] * 3, gold="retired", pool="qualification"),
            "attack": item([("established", "same", E), ("established", "different", E), ("established", "same", 0.95)]),
            "provisional": item([("established", "same", E)] * 3, state="provisional")}


def test_a_release_holds_only_releasable_rows_and_passes_the_check(tmp_path):
    items = fixture_items()
    path = export(tmp_path, list(items.values()))
    out = tmp_path / "release"
    result = build(path, out, released_on=date(2026, 10, 18))
    assert sorted(p.name for p in out.iterdir()) == ["CHECKSUMS", "dataset-card.md", "labels.tsv", "params.json",
                                                    "summary.tsv"]
    rows = {r["item_id"]: r for r in labels(out)}
    expected = {items[k]["item_id"] for k in ("three", "adjudicated", "reference", "review")}
    assert set(rows) == expected and result["rows"] == 4
    # Three agreeing at 0.85: 0.9945, the higher band. A person's decision has no band.
    assert rows[items["three"]["item_id"]]["confidence_band"] == "≥0.99"
    for key, label in (("adjudicated", "different"), ("reference", "different"), ("review", "same")):
        row = rows[items[key]["item_id"]]
        assert row["confidence_band"] == "" and row["resolved_answer"] == label
    assert check(out, path) == {"ok": True, "files": sorted(p.name for p in out.iterdir())}
    every = "".join((out / name).read_text(encoding="utf-8") for name in ("labels.tsv", "summary.tsv",
                                                                          "dataset-card.md", "params.json"))
    for record in items.values():
        for vote in record["votes"]:
            assert vote["annotator_id"] not in every
    assert "contributors to the Croatian stemmer labeling project" in (out / "dataset-card.md").read_text()
    with pytest.raises(FileExistsError):
        build(path, out)


def test_the_counterfactual_of_the_assessment():
    """Three agreeing voters at 0.85 give a row; flipping the third gives no row at all, so a
    holder who knows two votes learns the third: the residual risk the DPIA accepts."""
    agree = item([("established", "same", E)] * 3)
    assert agree["releasable"] and agree["confidence"] == pytest.approx(0.9945, abs=1e-4)
    flipped = item([("established", "same", E)] * 2 + [("established", "different", E)])
    assert not flipped["releasable"] and flipped["confidence"] == pytest.approx(0.85, abs=1e-9)


@pytest.mark.parametrize("leak", ["annotator_column", "email", "active_gold", "two_voters", "pivotal", "band",
                                  "extra_file"])
def test_release_check_fails_closed_on_each_leak(tmp_path, leak):
    items = fixture_items()
    path = export(tmp_path, list(items.values()))
    out = tmp_path / "release"
    build(path, out)
    text = (out / "labels.tsv").read_text(encoding="utf-8")
    lines = text.splitlines()
    header = lines[0].split("\t")

    def append(record, **changes):
        row = dict(zip(header, lines[1].split("\t")))
        row.update({"item_id": record["item_id"], **changes})
        (out / "labels.tsv").write_text(text + "\t".join(row[h] for h in header) + "\n", encoding="utf-8")

    if leak == "annotator_column":
        (out / "labels.tsv").write_text("\n".join(f"{line}\tx" if n else f"{line}\tannotator_id"
                                                  for n, line in enumerate(lines)) + "\n", encoding="utf-8")
    elif leak == "email":
        append(items["three"], resolved_lemma="ana@example.org")
    elif leak == "active_gold":
        append(items["gold"])
    elif leak == "two_voters":
        append(items["two"], resolution_source="model")
    elif leak == "pivotal":
        append(items["pivotal"], resolution_source="model")
    elif leak == "band":
        append(items["review"], resolution_source="review", confidence_band="≥0.99")
    else:
        (out / "votes.tsv").write_text("x\n")
    with pytest.raises(ValueError, match="release check failed"):
        check(out, path)


def test_only_a_pinned_fresh_run_is_released(tmp_path):
    items = list(fixture_items().values())
    for pinned, stale in ((False, False), (True, True)):
        path = export(tmp_path, items, pinned=pinned, stale=stale, name=f"e-{pinned}-{stale}.jsonl")
        with pytest.raises(ValueError, match="pinned run"):
            build(path, tmp_path / f"r-{pinned}-{stale}")


def test_one_added_vote_changes_only_that_item(tmp_path, capsys):
    """Two releases of a sparse fixture before and after one vote differ only in that item's
    first appearance, which happens only once no voter is pivotal."""
    stable = item([("established", "same", E)] * 3)
    before_item = item([("established", "same", E)] * 2)
    after_item = dict(item([("established", "same", E)] * 3), item_id=before_item["item_id"])
    first = export(tmp_path, [stable, before_item], name="before.jsonl")
    second = export(tmp_path, [stable, after_item], name="after.jsonl")
    main(["release", str(first), "--output", str(tmp_path / "one")])
    main(["release", str(second), "--output", str(tmp_path / "two")])
    capsys.readouterr()
    one, two = labels(tmp_path / "one"), labels(tmp_path / "two")
    strip = lambda rows: [{k: v for k, v in r.items() if k != "run_id"} for r in rows]
    assert [r["item_id"] for r in one] == [stable["item_id"]]
    assert sorted(r["item_id"] for r in two) == sorted([stable["item_id"], before_item["item_id"]])
    assert [r for r in strip(two) if r["item_id"] == stable["item_id"]] == strip(one)
    main(["release-check", str(tmp_path / "two"), "--run-export", str(second)])
    assert json.loads(capsys.readouterr().out)["ok"] is True

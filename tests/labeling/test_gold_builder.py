"""The bootstrap gold builder takes only what the corpus settles beyond doubt (4.3.1)."""
import json
import string
from collections import Counter

import pytest

from croatian_stemmer.labeling.__main__ import main
from croatian_stemmer.labeling.candidates import prepare
from croatian_stemmer.labeling.gold import build


SECRET = "a-private-test-seed-0123456789"


def name(n):
    """An alphabetic word for a number (no digits in forms or lemmas)."""
    letters = string.ascii_lowercase
    return "lem" + letters[n // 26] + letters[n % 26]


@pytest.fixture
def corpus(tmp_path):
    """Forty lemmas with five frequent forms each, an ambiguous form and a prefix-related pair."""
    lines, number = [], 0
    def sentence(tokens):
        nonlocal number
        lines.append("# text = " + " ".join(form for form, _, _ in tokens))
        for index, (form, lemma, upos) in enumerate(tokens, 1):
            lines.append(f"{index}\t{form}\t{lemma}\t{upos}")
        lines.append("")
    for n in range(40):
        lemma = name(n)
        for _ in range(6):
            sentence([(lemma + suffix, lemma, "NOUN") for suffix in ("a", "e", "i", "u", "om")])
    for _ in range(6):
        # `kosa` is a form of two lemmas (ambiguous); `kos`/`kosac` are prefix-related lemmas.
        sentence([("kosa", "kosa", "NOUN"), ("kosa", "kos", "NOUN"), ("kosom", "kos", "NOUN"),
                  ("kosca", "kosac", "NOUN"), ("kosu", "kosa", "NOUN")])
    path = tmp_path / "corpus.conllu"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    records, _ = prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=600, word_count=150,
                         seed=3)
    candidates = tmp_path / "candidates.jsonl"
    candidates.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path, candidates, records


def test_only_settled_items_become_gold(corpus):
    path, candidates, records = corpus
    rows, receipt = build(path, candidates, per_kind=100, qualification=30)
    by_id = {r["item_id"]: r for r in records}
    assert rows and receipt["human_judgments"] == 0
    assert {row["kind"] for row in rows} == {"pair", "lemma"}  # never stem
    for row in rows:
        candidate = by_id[row["item_id"]]
        words = {candidate["word"], candidate["other_word"]} - {""}
        # The ambiguous form never becomes gold, in either role.
        assert "kosa" not in words
        if row["answer"] == "different":
            left, right = candidate["proposed_lemma"], candidate["other_proposed_lemma"]
            assert not left.startswith(right) and not right.startswith(left)
        if row["kind"] == "lemma":
            assert row["lemma"] == candidate["proposed_lemma"]
        assert row["source"] == "hr500k" and row["corpus_sha256"] == candidate["corpus_sha256"]
    pairs = Counter(row["answer"] for row in rows if row["kind"] == "pair")
    assert pairs["same"] <= 0.6 * sum(pairs.values())
    pools = Counter((row["kind"], row["pool"]) for row in rows)
    assert pools[("pair", "qualification")] == 30 and pools[("lemma", "qualification")] == 30
    assert receipt["eligible"]["pair/same"] >= pairs["same"]


def test_builder_output_is_byte_identical_and_exclusions_hold(corpus, tmp_path, capsys):
    path, candidates, _ = corpus
    outputs = []
    for n in (1, 2):
        output = tmp_path / f"gold-{n}.jsonl"
        main(["gold", str(path), "--candidates", str(candidates), "--per-kind", "50", "--split", "qualification=20",
              "--seed", SECRET, "--allow-short", "--output", str(output)])
        outputs.append(output.read_bytes())
        receipt = json.loads(capsys.readouterr().out)
    assert outputs[0] == outputs[1] and receipt["batch"]
    with pytest.raises(SystemExit):  # never overwrites an earlier output
        main(["gold", str(path), "--candidates", str(candidates), "--allow-short",
              "--output", str(tmp_path / "gold-1.jsonl")])
    excluded = [json.loads(line)["item_id"] for line in outputs[0].decode().splitlines()[:10]]
    listing = tmp_path / "exclude.txt"
    listing.write_text("\n".join(excluded))
    rows, receipt = build(path, candidates, per_kind=50, qualification=20, exclude=excluded)
    assert not {row["item_id"] for row in rows} & set(excluded)
    assert receipt["exclude"] == sorted(excluded)


def test_candidates_from_another_corpus_are_refused(corpus, tmp_path):
    path, candidates, records = corpus
    other = tmp_path / "other.jsonl"
    other.write_text(json.dumps({**records[0], "corpus_sha256": "f" * 64}) + "\n")
    with pytest.raises(ValueError, match="not prepared from this corpus"):
        build(path, other)


# ---- gold reserve, wrong-suggestion gold, coverage (0.3.4) -------------------------------

from croatian_stemmer.labeling.candidates import RESERVE_STRATA, index_conllu, settled_lemma
from croatian_stemmer.labeling.gold import check, coverage, live_pools, needed


def write(path, rows):
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    return path


def truth(path):
    index = index_conllu(path)
    return lambda form, upos="NOUN": settled_lemma(index.freq, index.lemmas_of, form, upos, 5)


def test_needed_covers_the_calibration_hold_out():
    assert needed(15, 0) == 15 and needed(0, 10) == 0
    assert needed(15, 10) == 22 and needed(60, 10) == 77 and needed(100, 10) == 124
    assert needed(60, 50) > 120


def test_gold_reserve_is_settled_corpus_truth_and_leaves_the_sample_alone(corpus):
    path, _, records = corpus
    kwargs = dict(source_uri="urn:test:gold", license="test fixture", pair_count=600, word_count=150, seed=3,
                  reserve_secret=SECRET)
    with_reserve, receipt = prepare(path, **kwargs, gold_reserve_size=20)
    ordinary = [r for r in with_reserve if not r["sampling_stratum"].startswith("gold_reserve_")]
    records = ordinary  # with a reserve the ordinary sample is drawn from the secret
    assert len(ordinary) == len(prepare(path, **{**kwargs, "reserve_secret": None})[0])
    assert prepare(path, **kwargs, gold_reserve_size=20) == (with_reserve, receipt)
    reserve = with_reserve[len(records):]
    assert Counter(r["sampling_stratum"] for r in reserve) == {stratum: 20 for stratum in RESERVE_STRATA}
    assert receipt["gold_reserve"]["gold_reserve_lemma_decoy"] == 20 and receipt["prepared_lemma_items"] == 150
    assert len({r["item_id"] for r in with_reserve}) == len(with_reserve)
    used = [ref for r in reserve for ref in (r["word_ref"], r["other_word_ref"]) if ref]
    assert len(used) == len(set(used))  # no occurrence twice
    assert not set(used) & {ref for r in records for ref in (r["word_ref"], r["other_word_ref"])}
    assert len(with_reserve) == len(records) + 80
    lemma_of = truth(path)
    for r in reserve:
        assert "kosa" not in (r["word"], r["other_word"])  # ambiguous forms never take part
        left = lemma_of(r["word"])
        assert left is not None
        stratum = r["sampling_stratum"]
        if stratum == "gold_reserve_lemma":
            assert r["proposed_lemma"] == left
        elif stratum == "gold_reserve_lemma_decoy":
            assert r["proposed_lemma"] != left
        else:
            right = lemma_of(r["other_word"])
            shown_same = r["proposed_lemma"] == r["other_proposed_lemma"]
            if stratum == "gold_reserve_pair_decoy_same":
                assert shown_same and left != right
            else:
                assert not shown_same and left == right


def test_a_supplement_adds_only_new_items_of_the_same_corpus(corpus, tmp_path):
    path, _, records = corpus
    extra, receipt = prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=0, word_count=0,
                             gold_reserve_size=10, supplement=records)
    assert len(extra) == 40 and receipt["supplement"] == {"existing_items": len(records), "new_items": 40}
    assert not {r["item_id"] for r in extra} & {r["item_id"] for r in records}
    refs = {ref for r in records for ref in (r["word_ref"], r["other_word_ref"]) if ref}
    assert not refs & {ref for r in extra for ref in (r["word_ref"], r["other_word_ref"]) if ref}
    with pytest.raises(ValueError, match="different corpus or provenance"):
        prepare(path, source_uri="urn:test:other", license="test fixture", pair_count=0, word_count=0,
                gold_reserve_size=10, supplement=records)
    with pytest.raises(ValueError, match="at least one candidate"):
        prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=0, word_count=0)


def test_wrong_suggestion_gold_comes_from_reserve_decoys(corpus, tmp_path):
    path, candidates, records = corpus
    extra, _ = prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=0, word_count=0,
                       gold_reserve_size=30, supplement=records)
    supplement = write(tmp_path / "extra.jsonl", extra)
    rows, receipt = build(path, [candidates, supplement], per_kind=120, qualification=30, wrong=20)
    by_id = {r["item_id"]: r for r in records + extra}
    lemma_of = truth(path)
    wrong = [row for row in rows if row["basis"].endswith("_against_suggestion")]
    assert Counter(row["kind"] for row in wrong) == {"pair": 20, "lemma": 20}
    assert {row["pool"] for row in wrong} == {"audit"}
    # Both directions of a wrong pair suggestion, half each.
    assert Counter(row["answer"] for row in wrong if row["kind"] == "pair") == {"same": 10, "different": 10}
    for row in rows:
        candidate = by_id[row["item_id"]]
        if row["kind"] == "lemma":
            assert row["lemma"] == lemma_of(candidate["word"])  # the corrected lemma, never the decoy
            assert (row in wrong) == (candidate["proposed_lemma"] != row["lemma"])
        else:
            same = lemma_of(candidate["word"]) == lemma_of(candidate["other_word"])
            assert row["answer"] == ("same" if same else "different")
            shown_same = candidate["proposed_lemma"] == candidate["other_proposed_lemma"]
            assert (row in wrong) == (shown_same != same)
    kinds = receipt["coverage"]["kinds"]
    assert kinds["pair"]["wrong_suggestion"]["rows"] == 20 and kinds["stem"]["status"] == "expert_only"
    report = check([write(tmp_path / "gold.jsonl", rows)], [candidates, supplement])
    assert report["kinds"]["lemma"]["wrong_suggestion"]["rows"] == 20 and report["duplicates"] == 0


def test_coverage_report_and_exit_status(corpus, tmp_path, capsys):
    path, candidates, records = corpus
    output = tmp_path / "short.jsonl"
    # Without a reserve no item can disagree with the corpus's own suggestion: exit 3, file written.
    with pytest.raises(SystemExit) as exit_:
        main(["gold", str(path), "--candidates", str(candidates), "--output", str(output)])
    assert exit_.value.code == 3 and output.exists()
    captured = capsys.readouterr()
    receipt = json.loads(captured.out)
    assert receipt["coverage"]["kinds"]["pair"]["wrong_suggestion"]["ok"] is False
    assert "SHORT" in captured.err and "EXPERT ONLY" in captured.err
    main(["gold", str(path), "--candidates", str(candidates), "--allow-short", "--output", str(tmp_path / "ok.jsonl")])
    capsys.readouterr()
    with pytest.raises(SystemExit) as exit_:
        main(["gold-check", str(output), "--candidates", str(candidates)])
    assert exit_.value.code == 3
    assert json.loads(capsys.readouterr().out)["kinds"]["pair"]["status"] == "short"


def test_a_top_up_with_existing_gold_meets_readiness(tmp_path):
    """The live situation: gold without wrong-suggestion items is imported; a supplement and
    a second gold file built `--with` the first fill every pair and lemma pool."""
    lines = []
    for n in range(220):
        lemma = name(n % 676)
        lines.append("# text = " + " ".join(lemma + s for s in ("a", "e", "i", "u", "om")))
        lines += [f"{i}\t{lemma}{s}\t{lemma}\tNOUN" for i, s in enumerate(("a", "e", "i", "u", "om"), 1)]
        lines.append("")
    path = tmp_path / "big.conllu"
    path.write_text("\n".join(lines * 5) + "\n", encoding="utf-8")
    records, _ = prepare(path, source_uri="urn:test:big", license="test fixture", pair_count=2000, word_count=400)
    candidates = write(tmp_path / "candidates.jsonl", records)
    first, receipt = build(path, candidates)
    assert not receipt["coverage"]["ok"]
    old = write(tmp_path / "gold-1.jsonl", first)
    extra, _ = prepare(path, source_uri="urn:test:big", license="test fixture", pair_count=0, word_count=0,
                       gold_reserve_size=100, supplement=records)
    supplement = write(tmp_path / "extra.jsonl", extra)
    out = tmp_path / "gold-2.jsonl"
    main(["gold", str(path), "--candidates", str(candidates), "--candidates", str(supplement), "--with", str(old),
          "--per-kind", "200", "--split", "qualification=0", "--output", str(out)])
    second = [json.loads(line) for line in out.read_text().splitlines()]
    assert not {r["item_id"] for r in second} & {r["item_id"] for r in first}
    assert {r["pool"] for r in second} == {"audit"}
    report = check([old, out], [candidates, supplement])
    assert report["ok"] and report["rows"] == len(first) + len(second)
    # Importing a file twice is harmless (unchanged); two answers for one item are refused.
    assert check([old, old], [candidates])["duplicates"] == len(first)
    flipped = write(tmp_path / "flipped.jsonl", [{**first[0], "answer": "different" if first[0]["answer"] == "same"
                                                  else "same"}] if first[0]["kind"] == "pair" else
                    [{**first[0], "lemma": "drugo"}])
    with pytest.raises(ValueError, match="two different gold answers"):
        check([old, flipped], [candidates])


def test_gold_check_refuses_invalid_lines(corpus, tmp_path):
    path, candidates, records = corpus
    rows, _ = build(path, candidates, per_kind=10, qualification=5)
    good = rows[0]
    for bad, message in (({**good, "item_id": "00000000-0000-0000-0000-000000000000"}, "not in the candidates"),
                         ({**good, "source": "curator"}, "source"),
                         ({**good, "extra": 1}, "fields"),
                         ({**good, "kind": "stem", "answer": "accept", "lemma": ""}, "not in the candidates")):
        with pytest.raises(ValueError, match=message):
            check([write(tmp_path / "bad.jsonl", [bad])], [candidates])


def test_coverage_counts_stem_balance_when_stem_gold_exists():
    rows = [{"kind": "stem", "pool": "qualification", "answer": "accept", "agrees": None}] * 30
    report = coverage(rows)
    assert report["kinds"]["stem"]["status"] == "short"  # every class needs a quarter
    assert not report["ok"]


def test_seeds_are_private_and_never_public_defaults(corpus, tmp_path, capsys):
    """Which items are gold or reserve must not be reproducible from public inputs."""
    path, candidates, records = corpus
    for bad in ("1", "0", 1, "short-seed"):
        with pytest.raises(ValueError, match="private seed"):
            build(path, candidates, seed=bad)
        with pytest.raises(ValueError, match="private seed"):
            prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=0, word_count=0,
                    gold_reserve_size=5, reserve_secret=bad)
    with pytest.raises(SystemExit):
        main(["gold", str(path), "--candidates", str(candidates), "--seed", "1", "--output", str(tmp_path / "g")])
    capsys.readouterr()
    # Without a seed each run draws its own, records it in the receipt and selects differently.
    (a, ra), (b, rb) = build(path, candidates, per_kind=40), build(path, candidates, per_kind=40)
    assert ra["seed"] != rb["seed"] and len(ra["seed"]) == 32
    assert {r["item_id"] for r in a} != {r["item_id"] for r in b}
    assert build(path, candidates, per_kind=40, seed=ra["seed"])[0] == a
    # The reserve, and with it the ordinary sample, follow the secret: the receipt rebuilds them,
    # the public seed does not.
    kwargs = dict(source_uri="urn:test:gold", license="test fixture", pair_count=100, word_count=20, seed=3,
                  gold_reserve_size=5)
    one, receipt = prepare(path, **kwargs)
    assert prepare(path, **kwargs, reserve_secret=receipt["gold_reserve"]["secret"])[0] == one
    public, _ = prepare(path, **{**kwargs, "gold_reserve_size": 0})
    plain = [r for r in one if not r["sampling_stratum"].startswith("gold_reserve_")]
    assert {r["item_id"] for r in plain} != {r["item_id"] for r in public}
    # Every id has the ordinary form (kind, occurrences, stem): it does not tell a reserve item.
    from uuid import NAMESPACE_URL, uuid5
    for r in one:
        identity = json.dumps([r["kind"], r["word_ref"], r["other_word_ref"], r["proposed_stem"]], ensure_ascii=False)
        assert r["item_id"] == str(uuid5(NAMESPACE_URL, r["corpus_id"] + ":" + identity))


def test_a_supplement_never_repeats_an_occurrence(corpus, tmp_path, capsys):
    path, _, records = corpus
    # An ordinary sample with another seed overlaps the earlier file: overlapping rows are dropped.
    extra, receipt = prepare(path, source_uri="urn:test:gold", license="test fixture", pair_count=600,
                             word_count=150, seed=4, supplement=records)
    used = {ref for r in records for ref in (r["word_ref"], r["other_word_ref"]) if ref}
    assert all(not {r["word_ref"], r["other_word_ref"]} & used for r in extra)
    assert receipt["prepared_pairs"] == sum(r["kind"] == "pair" for r in extra)
    # The command defaults to no ordinary items with --supplement.
    earlier = write(tmp_path / "earlier.jsonl", records)
    out = tmp_path / "extra.jsonl"
    main(["prepare", str(path), "--source-uri", "urn:test:gold", "--license", "test fixture", "--gold-reserve", "3",
          "--supplement", str(earlier), "--output", str(out)])
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert len(rows) == 12 and all(r["sampling_stratum"].startswith("gold_reserve_") for r in rows)
    assert len(json.loads(capsys.readouterr().out)["gold_reserve"]["secret"]) == 32


def test_with_rows_are_deduplicated_conflicts_refused_and_live_pools_used(corpus, tmp_path):
    path, candidates, records = corpus
    first, _ = build(path, candidates, per_kind=60, qualification=20)
    _, receipt = build(path, candidates, existing=first + first, per_kind=10)
    assert receipt["existing_rows"] == len(first)
    assert receipt["coverage"]["upper_bound"] is True
    flipped = dict(first[0], answer="different" if first[0]["answer"] == "same" else "same") \
        if first[0]["kind"] == "pair" else dict(first[0], lemma="drugo")
    with pytest.raises(ValueError, match="two different answers"):
        build(path, candidates, existing=first + [flipped])
    # Live pools: what the site has counts as it is; the --with rows do not inflate it.
    overview = {"readiness": {kind: {"pools": {"qualification": {"all": 60}, "audit": {"all": 72},
                                               "wrong_suggestion": 0}} for kind in ("pair", "lemma")}}
    overview["readiness"]["stem"] = {"pools": {"qualification": {}, "audit": {}, "wrong_suggestion": None}}
    live = live_pools(overview)
    _, receipt = build(path, candidates, existing=first, per_kind=10, live=live)
    lemma = receipt["coverage"]["kinds"]["lemma"]
    assert receipt["coverage"]["live"] and not receipt["coverage"]["upper_bound"]
    assert lemma["audit"]["live"] == 72 and lemma["audit"]["needed"] == needed(28, 10)
    assert lemma["qualification"]["needed"] == 0 and lemma["wrong_suggestion"]["ok"] is False
    listing = {"pools": [{"kind": "pair", "pool": "audit", "status": "active", "suggestion_agrees": False, "n": 20},
                         {"kind": "pair", "pool": "audit", "status": "retired", "suggestion_agrees": False, "n": 9}]}
    assert live_pools(listing)["pair"] == {"qualification": {}, "audit": {"all": 20}, "wrong": 20}

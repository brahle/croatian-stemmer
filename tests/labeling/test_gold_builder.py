"""The bootstrap gold builder takes only what the corpus settles beyond doubt (4.3.1)."""
import json
import string
from collections import Counter

import pytest

from croatian_stemmer.labeling.__main__ import main
from croatian_stemmer.labeling.candidates import prepare
from croatian_stemmer.labeling.gold import build


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
              "--output", str(output)])
        outputs.append(output.read_bytes())
        receipt = json.loads(capsys.readouterr().out)
    assert outputs[0] == outputs[1] and receipt["batch"]
    with pytest.raises(SystemExit):  # never overwrites an earlier output
        main(["gold", str(path), "--candidates", str(candidates), "--output", str(tmp_path / "gold-1.jsonl")])
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

"""Candidates from raw Croatian text and Wikipedia dumps (from-text, 0.4.0): cleaning,
sentence splitting, filtering, lexicon suggestions, prepare's strata, provenance."""
import bz2
import io
import json
from collections import Counter
from pathlib import Path

import pytest

from croatian_stemmer.labeling.__main__ import main
from croatian_stemmer.labeling.text import (Documents, croatian, from_text, lexicon, split_sentences,
                                             wikitext_paragraphs)

FIXTURE = Path(__file__).parent / "fixtures" / "synthetic-wiki.xml"

LEXICON = [  # (form, lemma, upos) of a tiny synthetic lexicon
    ("kuća", "kuća", "NOUN"), ("kuće", "kuća", "NOUN"), ("kući", "kuća", "NOUN"), ("kućama", "kuća", "NOUN"),
    ("grad", "grad", "NOUN"), ("gradu", "grad", "NOUN"), ("gradovima", "grad", "NOUN"),
    ("gradili", "graditi", "VERB"), ("gradio", "graditi", "VERB"), ("grade", "graditi", "VERB"),
    ("ljudi", "čovjek", "NOUN"), ("žive", "živjeti", "VERB"), ("živi", "živjeti", "VERB"),
    ("živio", "živjeti", "VERB"), ("rade", "raditi", "VERB"), ("velika", "velik", "ADJ"),
    ("veliko", "velik", "ADJ"), ("kamena", "kamen", "NOUN"), ("drveta", "drvo", "NOUN"),
    ("visoke", "visok", "ADJ"), ("često", "često", "ADV"), ("horvat", "horvat", "PROPN"),
    ("ivan", "ivan", "PROPN"), ("vrt", "vrt", "NOUN"), ("sobe", "soba", "NOUN"), ("soba", "soba", "NOUN"),
    ("danas", "danas", "ADV"), ("ulice", "ulica", "NOUN"), ("naselje", "naselje", "NOUN"),
    ("prve", "prvi", "ADJ"), ("kasnije", "kasno", "ADV"), ("mnogo", "mnogo", "ADV"),
]


@pytest.fixture
def lexicon_file(tmp_path):
    lines = ["# text = Sintetički leksikon."]
    lines += [f"{i}\t{form}\t{lemma}\t{upos}" for i, (form, lemma, upos) in enumerate(LEXICON, 1)]
    path = tmp_path / "lexicon.conllu"
    path.write_text("\n".join(lines) + "\n\n", encoding="utf-8")
    return path


def test_croatian_sentences_split_after_full_stops_but_not_abbreviations_or_initials():
    text = ("Kuće su gradili npr. od kamena. Prvi stanovnik bio je I. Horvat iz grada. "
            "Rođen je 5. svibnja 1950. Studirao je u Zagrebu! Što je to? „Kuća” je riječ…")
    assert split_sentences(text) == [
        "Kuće su gradili npr. od kamena.", "Prvi stanovnik bio je I. Horvat iz grada.",
        "Rođen je 5. svibnja 1950.", "Studirao je u Zagrebu!", "Što je to?", "„Kuća” je riječ…"]


def test_croatian_alphabet_filter():
    assert croatian("kuća") and croatian("đak") and croatian("džep")
    assert not croatian("weekend") and not croatian("café") and not croatian("x") and not croatian("дом")


def test_wikitext_is_reduced_to_running_text():
    text = FIXTURE.read_text(encoding="utf-8")
    start = text.index("<text") + text[text.index("<text"):].index(">") + 1
    import html
    paragraphs = wikitext_paragraphs(html.unescape(text[start:text.index("</text>")]))
    joined = " ".join(paragraphs)
    assert "Kuća je zgrada u kojoj ljudi žive. Velika kuća ima mnogo soba i veliki vrt." in joined
    assert "Stare kuće imaju debele zidove od kamena." in joined  # list markup removed
    for gone in ("Infookvir", "Izmišljeni izvor", "Datoteka", "ogradom", "Povijest", "tablični", "skriveni",
                 "Kategorija", "House", "example.org", "'''", "{{", "[[", "<ref"):
        assert gone not in joined, gone


def test_dump_pages_skip_redirects_other_namespaces_and_disambiguation(tmp_path):
    documents = Documents([str(FIXTURE)])
    pages = list(documents)
    assert [base for base, _ in pages] == ["https://wiki.example.org/w/index.php?oldid=101",
                                           "https://wiki.example.org/w/index.php?oldid=105"]
    assert documents.stats == {"pages": 2, "disambiguation_pages": 1}
    assert documents.wikipedia and documents.site == "https://wiki.example.org"
    # The bz2 stream is read as it is; the corpus hash is the hash of the file's bytes.
    packed = tmp_path / "dump.xml.bz2"
    packed.write_bytes(bz2.compress(FIXTURE.read_bytes()))
    compressed = Documents([str(packed)])
    assert [base for base, _ in compressed] == [base for base, _ in pages]
    import hashlib
    assert compressed.sha256 == hashlib.sha256(packed.read_bytes()).hexdigest()


def test_wikipedia_candidates_carry_licence_attribution_and_lexicon_suggestions(lexicon_file, tmp_path):
    rows, receipt = from_text([str(FIXTURE)], lexicon_paths=[lexicon_file], pair_count=6, word_count=4, seed=1)
    assert receipt["license"] == "CC BY-SA 4.0" and receipt["source_uri"] == "https://dumps.wikimedia.org/hrwiki/"
    assert receipt["format"] == "mediawiki" and receipt["human_judgments"] == 0 and "no ground truth" in receipt["gold"]
    known = {form: (lemma, upos) for form, lemma, upos in LEXICON}
    for row in rows:
        assert row["sampling_stratum"].startswith("text_")
        assert row["word_ref"].startswith("https://wiki.example.org/w/index.php?oldid=")
        assert (row["proposed_lemma"], row["upos"]) == known[row["word"]]
        assert row["word"] not in ("ivan", "horvat")  # names (and PROPN) never become items
        assert row["word"] in row["context"].lower() and "@" not in row["context"]
        assert "Stranica o kućama" not in row["context"]  # an external link's label is no sentence
        assert row["license"] == "CC BY-SA 4.0" and row["candidate_schema_version"] == 1
    assert {r["kind"] for r in rows} == {"pair", "lemma", "stem"}
    assert len({r["item_id"] for r in rows}) == len(rows)
    assert from_text([str(FIXTURE)], lexicon_paths=[lexicon_file], pair_count=6, word_count=4, seed=1) == (rows,
                                                                                                         receipt)


def test_plain_text_needs_provenance_and_filters_names_rare_and_foreign_words(lexicon_file, tmp_path):
    folder = tmp_path / "texts"
    (folder / "a").mkdir(parents=True)
    (folder / "a" / "jedan.txt").write_text(
        "Ljudi žive u gradu i grade kuće. Ljudi u gradu često rade.\n\n"
        "Ivan Horvat je gradio kuće u gradu. Gradio je visoke kuće od kamena. Ivan Horvat živi u kući.\n",
        encoding="utf-8")
    (folder / "dva.txt").write_text("Danas ljudi grade kuće. Ljudi žive u kući s weekend vrtom. "
                                    "Pišite na ime@example.org za kuće.\n", encoding="utf-8")
    (folder / "skip.md").write_text("Ovo se ne čita.", encoding="utf-8")
    with pytest.raises(ValueError, match="source URI and license"):
        from_text([str(folder)], lexicon_paths=[lexicon_file], pair_count=2, word_count=2)
    rows, receipt = from_text([str(folder)], lexicon_paths=[lexicon_file], source_uri="urn:test:text",
                              license="CC BY 4.0", pair_count=4, word_count=3, min_count=2)
    assert receipt["format"] == "text" and receipt["inputs"] == 2 and receipt["files"] == 2
    words = {r["word"] for r in rows} | {r["other_word"] for r in rows} - {""}
    assert words <= {"ljudi", "žive", "gradu", "grade", "kuće", "kući", "gradio"}
    assert receipt["sentences_skipped"] >= 1  # the address sentence never becomes a context
    assert all(r["word_ref"].split("#")[0] in ("a/jedan.txt", "dva.txt") for r in rows)
    assert receipt["tokens_not_croatian_alphabet"] >= 1 and receipt["forms_below_min_count"] >= 1
    # Several inputs: the corpus hash is over their names and hashes, so it is stable.
    again, _ = from_text([str(folder)], lexicon_paths=[lexicon_file], source_uri="urn:test:text",
                         license="CC BY 4.0", pair_count=4, word_count=3)
    assert again == rows


def test_word_items_are_spread_over_frequency_bands(lexicon_file, tmp_path):
    # Distinct sentences (a page's repeated sentences count once).
    text = " ".join([f"Ljudi žive u gradu broj {n}." for n in range(120)]
                    + [f"Kuće su visoke i velika, broj {n}." for n in range(6)]
                    + [f"Grade kuće danas, broj {n}." for n in range(3)])
    path = tmp_path / "t.txt"
    path.write_text(text, encoding="utf-8")
    rows, receipt = from_text([str(path)], lexicon_paths=[lexicon_file], source_uri="urn:test:bands",
                              license="CC0 1.0", pair_count=1, word_count=3)
    bands = Counter(r["sampling_stratum"] for r in rows if r["kind"] == "lemma")
    assert bands == {"text_word_band_100-999": 1, "text_word_band_5-19": 1, "text_word_band_2-4": 1}
    assert receipt["forms_per_band"]["100-999"] >= 1


def test_from_text_command_and_stdin(lexicon_file, tmp_path, capsys, monkeypatch):
    out = tmp_path / "candidates.jsonl"
    main(["from-text", str(FIXTURE), "--lexicon", str(lexicon_file), "--pairs", "4", "--word-items", "2",
          "--source-uri", "https://dumps.wikimedia.org/hrwiki/20261001/", "--output", str(out)])
    receipt = json.loads(capsys.readouterr().out)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert receipt["prepared_pairs"] == sum(r["kind"] == "pair" for r in rows) and rows
    assert {r["source_uri"] for r in rows} == {"https://dumps.wikimedia.org/hrwiki/20261001/"}
    with pytest.raises(SystemExit):  # never overwrites
        main(["from-text", str(FIXTURE), "--lexicon", str(lexicon_file), "--output", str(out)])
    monkeypatch.setattr("sys.stdin", io.TextIOWrapper(io.BytesIO(
        "Ljudi žive u gradu. Ljudi grade kuće u gradu. Ljudi žive u kućama.".encode())))
    main(["from-text", "-", "--lexicon", str(lexicon_file), "--source-uri", "urn:test:stdin", "--license",
          "CC0 1.0", "--pairs", "1", "--word-items", "1", "--output", str(tmp_path / "stdin.jsonl")])
    assert json.loads(capsys.readouterr().out)["inputs"] == 1


def test_lexicon_takes_each_forms_most_frequent_analysis(tmp_path):
    path = tmp_path / "lex.conllu"
    path.write_text("1\tkosa\tkosa\tNOUN\n2\tkosa\tkos\tNOUN\n3\tkosa\tkosa\tNOUN\n\n", encoding="utf-8")
    found, hashes = lexicon([path])
    assert found == {"kosa": ("kosa", "NOUN")} and len(hashes) == 1


def test_mwparserfromhell_parser_when_installed(lexicon_file):
    pytest.importorskip("mwparserfromhell")
    rows, receipt = from_text([str(FIXTURE)], lexicon_paths=[lexicon_file], pair_count=4, word_count=2,
                              parser="mwparserfromhell")
    assert receipt["parser"] == "mwparserfromhell" and rows
    assert all("tablični" not in r["context"] for r in rows)


def test_gold_refuses_raw_text_candidates(lexicon_file, tmp_path):
    from croatian_stemmer.labeling.gold import build
    rows, _ = from_text([str(FIXTURE)], lexicon_paths=[lexicon_file], pair_count=2, word_count=1)
    candidates = tmp_path / "c.jsonl"
    candidates.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(ValueError, match="no ground truth"):
        build(FIXTURE, candidates)

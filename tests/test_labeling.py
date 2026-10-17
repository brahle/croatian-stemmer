"""Human labels and suggestions must remain distinct, auditable targets."""

import importlib.util
import io
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from croatian_stemmer.labeling.candidates import prepare
from croatian_stemmer.labeling.evaluation import evaluate
from croatian_stemmer.labeling.schema import Annotation, FIELDS, load, read_tsv, write_tsv


@pytest.fixture
def annotation():
    return Annotation(corpus_id=str(uuid4()), corpus_sha256="a" * 64,
                      source_uri="urn:test:synthetic-corpus", license="test fixture",
                      item_id=str(uuid4()), annotation_id=str(uuid4()), annotator_id="reader-a",
                      revision=1, annotated_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                      kind="pair", word="kuća", other_word="kuće", answer="same",
                      word_ref="line:2", other_word_ref="line:3", upos="NOUN")


def variation(a, **values):
    return replace(a, annotation_id=str(uuid4()), **values)


def tsv(annotations):
    out = io.StringIO()
    write_tsv(out, annotations)
    return out.getvalue()


def test_tsv_round_trip_preserves_diacritics_and_quoted_context(annotation):
    a = replace(annotation, context='Čija kuća?\t"Njihova."\nDrugi red.')
    assert read_tsv(io.StringIO(tsv([a]))) == [a]


@pytest.mark.parametrize("change", [
    {"schema_version": "2"}, {"provenance": "machine"}, {"corpus_sha256": "short"},
    {"annotator_id": ""}, {"revision": 0}, {"revision": True}, {"license": ""},
    {"annotated_at": datetime(2026, 1, 1)}, {"irregular": "false"}, {"upos": "bad"},
    {"word": "Kuća"}, {"word": "two words"}, {"word_ref": ""},
    {"answer": "accept"}, {"lemma": "kuća"}, {"other_word_ref": ""},
])
def test_invalid_provenance_and_cross_kind_labels_are_refused(annotation, change):
    with pytest.raises(ValueError):
        replace(annotation, **change).validate()


def test_prefill_is_not_a_confirmed_lemma(annotation):
    a = replace(annotation, kind="lemma", other_word="", other_word_ref="",
                answer="unsure", lemma="kuća")
    with pytest.raises(ValueError, match="unsure lemma"):
        a.validate()


def test_export_header_and_rows_are_exact(annotation):
    data = tsv([annotation])
    with pytest.raises(ValueError, match="header"):
        read_tsv(io.StringIO(data.replace("schema_version", "guess", 1)))
    with pytest.raises(ValueError, match="line 3"):
        read_tsv(io.StringIO(data + "1\tpartial\n"))


def test_duplicate_export_rows_and_revisions_do_not_inflate_count(annotation):
    newer = variation(annotation, revision=2, answer="different",
                      annotated_at=annotation.annotated_at + timedelta(seconds=1))
    result = evaluate([newer, annotation, newer], lambda w: "same")
    assert result["coverage"]["raw_export_rows"] == 3
    assert result["coverage"]["unique_annotation_revisions"] == 2
    assert result["coverage"]["resolved_items"] == 1
    assert result["pairs"]["different"] == 1
    assert result["pairs"]["over_stemming_errors"] == 1


def test_latest_unsure_withdraws_previous_definite_label(annotation):
    newer = variation(annotation, revision=2, answer="unsure",
                      annotated_at=annotation.annotated_at + timedelta(seconds=1))
    report = evaluate([annotation, newer], lambda w: w)
    assert report["coverage"]["unsure_items"] == 1
    assert report["pairs"]["accuracy"] is None


@pytest.mark.parametrize("change, message", [
    ({"source_uri": "urn:other"}, "conflicting source"),
    ({"word": "grad"}, "immutable item"),
])
def test_immutable_corpus_and_item_identity(annotation, change, message):
    with pytest.raises(ValueError, match=message):
        evaluate([annotation, variation(annotation, annotator_id="reader-b", **change)], lambda w: w)


def test_annotation_id_cannot_be_reused_with_another_answer(annotation):
    with pytest.raises(ValueError, match="annotation id reused"):
        evaluate([annotation, replace(annotation, answer="different")], lambda w: w)


def test_duplicate_revision_and_backdated_revisions_are_refused(annotation):
    with pytest.raises(ValueError, match="duplicate annotator revision"):
        evaluate([annotation, variation(annotation)], lambda w: w)
    older = variation(annotation, revision=2, annotated_at=annotation.annotated_at - timedelta(seconds=1))
    with pytest.raises(ValueError, match="backwards"):
        evaluate([annotation, older], lambda w: w)


def test_conflicting_annotators_do_not_become_majority_gold(annotation):
    rows = [annotation, variation(annotation, annotator_id="reader-b", answer="different"),
            variation(annotation, annotator_id="reader-c")]
    report = evaluate(rows, lambda w: "same")
    assert report["coverage"]["conflicting_items"] == 1
    assert report["coverage"]["resolved_items"] == 0
    assert report["coverage"]["observed_agreement"] == 0
    assert report["pairs"]["accuracy"] is None


def test_two_reader_requirement_counts_only_definite_distinct_readers(annotation):
    uncertain = variation(annotation, annotator_id="reader-b", answer="unsure")
    report = evaluate([annotation, uncertain], lambda w: "same", min_annotators=2)
    assert report["coverage"]["insufficient_items"] == 1
    agreed = variation(annotation, annotator_id="reader-b")
    report = evaluate([annotation, agreed], lambda w: "same", min_annotators=2)
    assert report["pairs"]["same"] == 1
    assert report["coverage"]["observed_agreement"] == 1


def test_pair_metrics_have_separate_positive_and_negative_denominators(annotation):
    same_error = variation(annotation, item_id=str(uuid4()), word="mačka", other_word="mačke")
    different_error = variation(annotation, item_id=str(uuid4()), word="grad", other_word="grada", answer="different")
    report = evaluate([annotation, same_error, different_error],
                      lambda w: {"kuća": "kuć", "kuće": "kuć", "mačka": "a", "mačke": "b", "grad": "grad", "grada": "grad"}[w])
    assert report["pairs"]["under_stemming_rate"] == .5
    assert report["pairs"]["over_stemming_rate"] == 1
    assert report["pairs"]["accuracy"] == pytest.approx(1 / 3)


def test_lemma_grouping_is_not_exact_stem_to_dictionary_form(annotation):
    a = replace(annotation, kind="lemma", other_word="", other_word_ref="", answer="confirmed", lemma="kuća")
    b = variation(a, item_id=str(uuid4()), word="kuće", word_ref="line:3")
    report = evaluate([a, b], lambda w: "kuć")
    assert report["lemmas"]["group_consistency"] == 1
    assert report["pairs"]["accuracy"] is None


def test_lemma_groups_do_not_cross_corpus_or_pos_boundaries(annotation):
    a = replace(annotation, kind="lemma", other_word="", other_word_ref="", answer="confirmed", lemma="kuća")
    b = variation(a, item_id=str(uuid4()), word="kuće", corpus_id=str(uuid4()))
    c = variation(a, item_id=str(uuid4()), word="kuće", upos="VERB")
    report = evaluate([a, b, c], lambda w: "kuć")
    assert report["lemmas"]["multi_form_groups"] == 0
    assert report["lemmas"]["group_consistency"] is None


def test_changed_stem_output_is_unknown_not_automatically_accepted(annotation):
    a = replace(annotation, kind="stem", other_word="", other_word_ref="", answer="reject", proposed_stem="kuć")
    report = evaluate([a], lambda w: "kuć")
    assert report["stems"]["acceptance_rate"] == 0
    changed = evaluate([a], lambda w: "kuća")
    assert changed["stems"]["changed_outputs_need_relabeling"] == 1
    assert changed["stems"]["acceptance_rate"] is None


def test_empty_labels_do_not_report_zero_error_or_perfect_accuracy():
    report = evaluate([], lambda w: w)
    assert report["pairs"]["under_stemming_rate"] is None
    assert report["pairs"]["accuracy"] is None


def test_load_records_digest_of_exact_parsed_bytes(tmp_path, annotation):
    path = tmp_path / "labels.tsv"
    path.write_text(tsv([annotation]), encoding="utf-8")
    labels, receipts = load([path])
    assert labels == [annotation]
    assert len(receipts[0]["sha256"]) == 64


def test_candidate_preparation_is_deterministic_and_never_human_gold(tmp_path):
    source = tmp_path / "source.conllu"
    source.write_text('# text = Kuća ima kuće.\n1\tKuća\tkuća\tNOUN\n2\tkuće\tkuća\tNOUN\n3\tgrad\tgrad\tNOUN\n4\tgrada\tgrad\tNOUN\n', encoding="utf-8")
    kwargs = dict(source_uri="urn:test:corpus", license="test fixture", pair_count=4, word_count=2, seed=13)
    records, receipt = prepare(source, **kwargs)
    assert prepare(source, **kwargs) == (records, receipt)
    assert receipt["human_judgments"] == 0
    assert {r["kind"] for r in records} == {"pair", "lemma", "stem"}
    assert all("annotation_id" not in r and "answer" not in r for r in records)
    assert all(r["word_ref"].startswith("line:") for r in records)
    assert records[0]["context"] == "Kuća ima kuće."
    assert receipt["prepared_pairs"] == 4


def module(name):
    path = Path(__file__).resolve().parents[1] / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_both_evaluators_accept_export_without_hr500k(tmp_path, annotation, capsys):
    path = tmp_path / "labels.tsv"
    path.write_text(tsv([annotation]))
    module("evaluate").main(["--labels", str(path), "--labels-only"])
    assert '"same": 1' in capsys.readouterr().out
    module("evaluate_score").main(["--labels", str(path), "--labels-only"])
    result = json.loads(capsys.readouterr().out)
    assert result["human_labels"]["pairs"]["same"] == 1
    assert "score" not in result and "passed_guardrails" not in result


def test_human_metrics_do_not_change_legacy_autoresearch_score(tmp_path, annotation, capsys, monkeypatch):
    scorer = module("evaluate_score")
    monkeypatch.setattr(scorer, "load_corpus", lambda: [("kuća", "kuća", "NOUN"), ("kuće", "kuća", "NOUN")])
    scorer.main([])
    baseline = json.loads(capsys.readouterr().out)
    path = tmp_path / "labels.tsv"
    path.write_text(tsv([annotation]))
    scorer.main(["--labels", str(path)])
    with_human = json.loads(capsys.readouterr().out)
    assert with_human.pop("human_labels")["pairs"]["same"] == 1
    assert with_human == baseline


def test_conllu_plus_declared_column_order_is_honored(tmp_path):
    source = tmp_path / 'reordered.conllup'
    source.write_text('# global.columns = ID UPOS LEMMA FORM\n1\tNOUN\tkuća\tKuće\n')
    records, receipt = prepare(source, source_uri='urn:test:reordered', license='test fixture', pair_count=0, word_count=1)
    assert records[0]['word'] == 'kuće'
    assert records[0]['proposed_lemma'] == 'kuća'
    assert records[0]['upos'] == 'NOUN'
    assert receipt['human_judgments'] == 0


@pytest.mark.parametrize('header', ['ID FORM FORM UPOS', 'ID FORM UPOS'])
def test_ambiguous_or_incomplete_declared_columns_are_refused(tmp_path, header):
    source = tmp_path / 'bad.conllup'
    source.write_text('# global.columns = ' + header + '\n1\tkuća\tkuća\tNOUN\n')
    with pytest.raises(ValueError, match='header'):
        prepare(source, source_uri='urn:test:bad', license='test fixture', pair_count=0, word_count=1)

# Human-label evaluation and candidate preparation

The labeling app's data contract supports three separate judgments: whether two
forms have the same lemma, an explicitly confirmed dictionary lemma, and
acceptability of a concrete proposed stem. No kind is silently converted to
another. The authenticated web app that collects them is described in
[labeling-web.md](labeling-web.md).

## Prepare suggestions

Install the package and supply an existing CoNLL-U/CoNLL-U Plus file. Declared
`global.columns` order is honored; without it, the standard ID/FORM/LEMMA/UPOS
positions apply. Nonalphabetic forms, multiword/range tokens, missing lemmas
and missing POS are excluded. All corpus lemmas remain suggestions.

```sh
croatian-stemmer-labels prepare path/to/corpus.conllu \
  --source-uri https://example.org/corpus-record --license 'SOURCE-LICENSE' \
  --pairs 10000 --word-items 1000 --seed 0 --output candidates.jsonl
```

The command requires source/license provenance, reads rather than modifies the
corpus, refuses to overwrite the output, and prints a preparation receipt.
Candidate JSONL has its own versioned schema and no answer, annotator, or human
annotation identifier. Same-lemma suggestions, stem-collision suggestions and
random different-lemma suggestions are sampling strata, not gold labels. Review
both source contexts; a corpus suggestion can be wrong. Candidate sampling does
not estimate a language-wide error rate.

The local hr500k 2.0 file was verified against the MD5 published by
[CLARIN.SI](https://www.clarin.si/repository/xmlui/handle/11356/1792). It is authored
by Nikola Ljubešić and Tanja Samardžić and licensed CC BY-SA 4.0. The real
preparation run produced 10,000 pair candidates and 1,000 candidates for each of
lemma/stem review from 67,245 unique form/lemma/POS suggestions. It produced
**zero new human judgments**. No corpus text or candidate file is committed to
this repository.

## Evaluate exported judgments

```sh
croatian-stemmer-labels evaluate judgments.tsv
python evaluate.py --labels judgments.tsv
python evaluate_score.py --labels judgments.tsv
# When hr500k is unavailable:
python evaluate_score.py --labels judgments.tsv --labels-only
# Require two definite, agreeing annotators:
croatian-stemmer-labels evaluate judgments.tsv --min-annotators 2
```

Repeat `--labels` on the existing evaluators, or pass several TSV paths to the
package command. Human metrics are reported separately from the unchanged
hr500k benchmark and score/guardrails. Labels-only output contains no substitute
autoresearch score. Input receipts hash the exact bytes parsed.

Exports are UTF-8 TSV with the exact v1 header defined in
`croatian_stemmer.labeling.schema.FIELDS`. Corpus/item/annotation identifiers,
corpus SHA-256, source URI, license, source locations, annotator identity,
revision and timezone-aware timestamp are required. Contexts can contain quoted
tabs and newlines. Identifiers and content must remain consistent across rows.
Candidate-prefill provenance is refused by the annotation reader.

In exports from the labeling web app, `annotator_id` is a random pseudonymous
UUID per participant, not a login name or email; it stays the same across that
person's revisions and is kept when they erase their account. Judgments of
blocked participants are left out unless the curator asks for them.

Pair answers are `same`, `different`, or `unsure`. Lemma answers are `confirmed`
with the actual lemma, or `unsure` with no confirmed lemma. Stem answers are
`accept`, `reject`, or `unsure` for a concrete `proposed_stem`. `irregular` is a
separate 0/1 flag; it does not manufacture a lemma or pair answer.

Only the latest revision per item/annotator is considered. Duplicate copies of
an export do not inflate counts. Disagreements remain unresolved, including
when a majority agrees. An unsure answer contributes no definite vote; a latest
unsure revision withdraws that annotator's earlier label. Agreement reports only
items with at least two definite readers. An empty denominator is unknown/null,
not a zero error rate.

Pair metrics measure under-/over-stemming against the explicit human relation.
Lemma grouping is within corpus and POS and excludes ambiguous spellings that
have different confirmed lemmas in different contexts. It does not require a
stem to equal a dictionary lemma. A stem acceptability judgment applies only
when the current output matches the proposed stem; changed outputs need new
judgments and cannot be counted as automatic improvements.

The 10,000-label milestone is about actual new human pair judgments, with
revision/conflict/abstention coverage reported. Preparing 10,000 candidates or
passing synthetic test fixtures does not satisfy it.

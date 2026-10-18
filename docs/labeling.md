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

`--gold-reserve N` (default 0) adds a gold reserve: N items for each of four reserve
strata, built only to become known-answer items, from forms the corpus settles (the
`gold` rule below: one lemma for the form and POS, at least `--min-freq` occurrences,
default 5; nouns, verbs, adjectives and adverbs only). `gold_reserve_lemma` items show
the corpus lemma. The three decoy strata show a suggestion the corpus contradicts, on
purpose, because an item whose suggestion is the corpus's own lemma can never have a
known answer that differs from its suggestion: `gold_reserve_lemma_decoy` shows the
lemma of another word with the same stem, or else the form itself, as the lemma;
`gold_reserve_pair_decoy_same` shows two forms of different lemmas (forms the stemmer
merges first, then forms sharing their first four letters) with one lemma for both;
`gold_reserve_pair_decoy_different` shows two forms of one lemma with a decoy lemma on
one of them. No reserve item reuses an occurrence another item uses (a form may come
back in another sentence), and every item id has the same form (kind, occurrences, stem),
so an id does not tell a reserve item. The reserve is drawn from a private secret
(`--reserve-secret`, at least 16 characters; drawn at random when omitted and printed only
in the receipt); in a run with a reserve the ordinary sample is drawn from the secret too,
because a sample anyone can reproduce from the public corpus and the documented `--seed`
would reveal the reserve as its complement. **Keep the receipt private** (outside the
repository, never published): with it anyone could rebuild the reserve. The web app never serves a reserve
item as ordinary or expert work (only as a known-answer check once it is gold), leaves
reserve items out of progress counts, and `release` never publishes one, so the decoys
neither bias the crowd sample nor reach a release. Reserve items that do not become
gold (for example those in the calibration sample) are never shown; the rest stay
available for later top-ups when checks are served out or disclosed.

To add a reserve to a corpus that is already imported, prepare a supplement: only new
item ids of the same corpus, never reusing an occurrence of the earlier file (an ordinary
item that would is left out), and refused unless the corpus hash, source URI and licence
are the same. With `--supplement`, `--pairs` and `--word-items` default to 0:

```sh
croatian-stemmer-labels prepare path/to/corpus.conllu \
  --source-uri https://example.org/corpus-record --license 'SOURCE-LICENSE' \
  --gold-reserve 200 --supplement candidates.jsonl \
  --output candidates-extra.jsonl > candidates-extra.receipt.json  # private
```

Import it like any candidates file: the import adds new items to an existing corpus with
the same provenance, reports existing ids as `already_present` and leaves them unchanged,
and refuses a different hash, source or licence (409 `corpus_provenance_conflict`) or a
changed question under an existing id (409 `immutable_item_conflict`).

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
person's revisions. When they erase their account, their judgments move to a new
random id that nothing links to the old one (times cut to the day, no timing).
Judgments of blocked participants are left out unless the curator asks for them.
These exports are unweighted; the trust-weighted labels are in the separate
`resolved.tsv`/`resolved.jsonl` exports (schema version 2, see
[labeling-web.md](labeling-web.md)), which `evaluate` does not read.

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

## Trust system commands (0.3.0)

Four commands support the trust-weighted labeling of 0.3.0. The model they serve is
described in [trust.md](trust.md), the web side in [labeling-web.md](labeling-web.md).
Each command refuses to overwrite its output, prints a JSON report on standard output
and exits non-zero with a message on any error.

### Build known-answer items

```sh
croatian-stemmer-labels gold path/to/corpus.conllu --candidates candidates.jsonl \
  [--candidates candidates-extra.jsonl] [--with gold-1.jsonl] \
  --min-freq 5 --per-kind 400 --split qualification=80 --wrong-suggestion 30 \
  [--seed PRIVATE] [--exclude used-ids.txt] [--live overview.json] [--params params.json] \
  [--allow-short] --output gold.jsonl > gold.receipt.json  # private
```

The defaults are the values shown. The selection is seeded by a private seed (`--seed`,
at least 16 characters; drawn at random when omitted and recorded only in the receipt):
with a public seed anyone could rebuild which items are known answers from the public
corpus and the documented options, and answer exactly those with care. Keep the receipt
private. The candidates must be the files the corpus was
imported from (repeat `--candidates` for a supplement): every row's `corpus_sha256` must
equal the corpus's, and the corpus must not change while the command reads it. A candidate
becomes a known-answer item only when the corpus settles it beyond doubt: every form shown
occurs at least `--min-freq` times with its lemma and POS, and each form has one lemma for
its POS. The answer is that corpus truth, whatever the item suggests: a `pair` is `same`
when the two settled lemmas are equal and `different` when they differ and are not
variants (one a prefix of the other, or equal without diacritics); a `lemma` item is
`confirmed` with the corpus lemma. `stem` items are never produced (below).

An ordinary candidate shows the corpus's own lemmas, so its known answer always agrees
with the suggestion. Gold that differs from the suggestion, which the `copy` flag and the
promotion floor need (`readiness.wrong_suggestion_pool`, 15 per kind), therefore comes
from the gold-reserve decoys of `prepare --gold-reserve`: `--wrong-suggestion` such items
per kind (default 30; for `pair` half shown `same` with answer `different` and half the
other way), always in the audit pool, with a basis ending in `_against_suggestion`. The
rest of `--per-kind` agrees with the suggestion, at most 60 % `same` for `pair`; the first
N of those per kind (`--split qualification=N`) go to the qualification pool and the rest
to the audit pool. `--exclude` takes a file of item ids, one per line, never to use.
`--with` takes gold files already imported: their items are not used again (a repeated
item counts once; one with two different answers is refused) and they count in the
coverage, which is how a top-up is built. Identical inputs, options and seed give
identical bytes. The receipt names the batch id, input hashes, options, eligible counts
(`/against_suggestion` for decoys), counts per kind, pool, answer and basis, and the
coverage, and states `human_judgments: 0`.

Coverage: on standard error the command prints, per kind and pool, the rows the import
would put in each pool (the import fills qualification to its target and sends the rest
to audit), the rows needed and the readiness target. A pool is covered when it still
meets its target after the import holds out the calibration sample (`audit_sample_rate`,
10 %) with probability at least 0.999; for the defaults that is 77 qualification rows
for 60, 133 more rows for the audit pool of 100 and 22 suggestion-wrong rows for 15. The
targets come from `DEFAULT_PARAMS`, or from `--params` (a parameter set as the dashboard
shows it). **When a `pair` or `lemma` pool is short the command still writes the file
but exits with status 3** (`--allow-short` exits 0); `stem` is reported as `EXPERT ONLY`
and never fails the command. The live pools stay authoritative: the hold-out is decided
per item by a keyed hash the builder cannot see, and gold can since have been retired,
contested or served out. Without `--live`, rows from `--with` files count as if all
were imported and still active, and the report says it is an **upper bound**. With
`--live FILE` (the JSON of `GET /api/admin/overview`, which the dashboard's "Pregled" tab
loads, or of `GET /api/admin/gold`) the site's active pools count as they are, the
`--with` rows only exclude their items, and the new rows must fill what is missing; the
table then has a `live` column.

Stem known answers cannot come from a lemmatised corpus. A stem is acceptable when every
usual form of its lemma reduces to it and no word of another meaning does (the
guidelines); a corpus records lemmas, not which forms a stem may merge, and it holds
neither every form of a lemma nor a judgement of which different lemmas are related in
meaning (stem alternations such as *ruka*/*ruci* and derivations such as *rad*/*raditi*
make any rule over lemmas unsound). Stem gold comes from the trusted list: the anchors'
answers on the stem seed queue become `anchor_consensus` gold (16 qualification items,
then 30 audit items, each class at least a quarter), or the curator sets it per item.

### Check a gold file

```sh
croatian-stemmer-labels gold-check gold-1.jsonl [gold-2.jsonl ...] \
  --candidates candidates.jsonl [--candidates candidates-extra.jsonl] [--live overview.json] \
  [--params params.json]
```

It reads the gold files in import order and fails (exit 2, with the line) on a line the
web import would refuse or whose item is not in the candidates, and on an item with two
different answers (the import's `gold_conflict`); a repeated identical line counts as
`duplicates` (the import's `unchanged`). It recomputes each row's agreement with the
suggestion as the server does, prints the coverage report described above and exits 3
when a `pair` or `lemma` pool is short.

Import the files in the curator dashboard ("Zlatni primjeri"), in order. The import skips
items that belong to the calibration sample (reported as `held_out`), fills each kind's
qualification pool up to 60 and puts any surplus in the audit pool. Re-importing a line
with the same answer is reported as `unchanged`; a different answer for an item that
already has valid gold fails the whole import (409 `gold_conflict`).

### Replay a scoring run

```sh
croatian-stemmer-labels score --bundle run-bundle.json --output outputs.json
```

`--bundle` is a run's restricted bundle as downloaded from "Bodovanje" (or a directory
holding `bundle.json`). The command recomputes the run with the same pure scoring
module, with no database and no secret key, writes the canonical outputs and prints
`run_id`, `inputs_sha256`, `inputs_match`, `outputs_sha256` and `outputs_match`. If a
later privacy action changed the run's inputs (an erasure, the 90-day timing retention,
a redaction), `inputs_match` is false, `changed` lists each journal whose hash differs
with its row counts then and now, and `outputs_match` is null rather than a false
mismatch. The bundle contains pseudonymous behavioural data: keep it local and delete it
within 30 days, and at once when an erasure is completed for a pseudonym it contains.

### Build a public release

```sh
croatian-stemmer-labels release resolved-CORPUS.jsonl --output release-DIR
```

The input is the run export "Izračun za izdanje (JSONL)" of one corpus
(`resolved.jsonl`). The run must be pinned and not stale, and the output directory must
not exist. The directory receives exactly `labels.tsv`, `summary.tsv`,
`dataset-card.md`, `params.json` and `CHECKSUMS`. `labels.tsv` has one row per item that
is `resolved` and releasable at the run, leaving out qualification items and audit
known-answer items still in use; a confidence band (`≥0.99` or `0.95-0.99`) appears only
on model resolutions, never on a person's decision (`adjudication`, `reference`,
`review`). `summary.tsv` has item counts per kind and state, calibration per cell and
Krippendorff's alpha. Nothing is per vote or per contributor: no annotator ids, vote
counts, tiers, weights, flags, events or timestamps other than the release date. The
command prints the number of rows, items and the run id.

### Check a release

```sh
croatian-stemmer-labels release-check release-DIR --run-export resolved-CORPUS.jsonl \
  --annotators annotators.jsonl
```

It fails closed, listing every problem, unless: the file set equals the allowlist; each
TSV's columns equal its allowlist and no column name contains `annotator`, `email`,
`created`, `elapsed`, `tier`, `weight`, `count`, `votes` or `flag`; no value contains `@`
or equals an annotator id from the run export (and from the curator's annotators
export, with `--annotators`, which is recommended); no row is a known-answer item still
in use; every `model`, `reference` or `review` row has at least three distinct counted
crowd voters (anchors' votes do not count) and no pivotal one; and only model
rows carry a band. On success it prints `{"ok": true, "files": [...]}`.

### Release procedure

1. In "Bodovanje", pin a fresh run (a stale run cannot be pinned).
2. Download "Izračun za izdanje (JSONL)" for each corpus, and the annotators export of
   the same run.
3. Press "Zabilježi izdanje" for the run. This records every known-answer item among
   the released rows as disclosed, so later answers on it no longer count as evidence of
   skill. Known-answer items in use now (any qualification item, an active check, also
   one a later run created) are never released: the run export carries each item's
   current gold status (`gold_status_now`), `release` leaves such items out and
   `release-check` refuses them. `POST /api/admin/scoring/runs/{id}/release` with
   `{"item_ids": [...]}` (the release's labels.tsv) refuses them too (409 `gold_in_use`).
4. Run `croatian-stemmer-labels release` per corpus, then `release-check` on each
   directory.
5. Publish the checked directories as a GitHub release of
   [github.com/brahle/croatian-stemmer](https://github.com/brahle/croatian-stemmer),
   and nowhere else. Releases are never rewritten.
6. Delete the downloaded exports within 30 days (the release directories hold no
   personal data).

# Croatian Stemmer

A rule-based stemmer for Croatian, available as a Python library and as a PostgreSQL text search dictionary. Both implementations produce identical stems.

It starts from the Ljubešić–Pandžić stemmer ("Simple stemmer for Croatian v0.1", 2012), which refines the algorithm from Ljubešić, Boras & Kubelka (2007). On top of that it adds extra suffix rules and post-processing for comparatives, jotation and fleeting *a*. These additions were tuned against the hr500k corpus and checked on a separate held-out corpus; see [Evaluation](#evaluation).

## Python

Requires Python 3.10 or newer.

```bash
pip install croatian-stemmer
```

```python
from croatian_stemmer import stem, stem_text

stem("gradovima")   # "grad"
stem("kuće")        # "kuć"
stem("lijepog")     # "lijep"
stem("metara")      # "metr"   (fleeting a)
stem("najvećih")    # "već"    (superlative prefix)

stem_text("Veliki grad ima lijepe kuće")
# ["velik", "grad", "im", "lijep", "kuć"]

stem_text("Ja sam bio u gradu")
# ["ja", "u", "grad"]   (stop words "sam" and "bio" are dropped)
```

`stem()` stems any single word. `stem_text()` tokenizes, lowercases and stems running text, dropping the 67 stop words: forms of the auxiliaries and modals *biti*, *htjeti*, *željeti*, *morati*, *trebati* and *moći*. Passing a stop word to `stem()` returns it unchanged (`stem("sam") == "sam"`).

### Command line

```bash
croatian-stemmer kuća grada lijepog        # word<TAB>stem per line
echo "gradovima" | croatian-stemmer        # one word per line on stdin
echo "Ja sam bio u gradu" | croatian-stemmer -t   # free text: ja u grad
```

## PostgreSQL extension

`pg/` contains a PGXS extension, `dict_croatian_stem`, tested on PostgreSQL 15, 16, 17 and 18. The stemmer is plain C with no dependencies. Its rule tables are generated from the Python rules by `gen_rules_c.py`, and the test suite checks that the C and Python stems match.

### Build and install

Requires the server development headers (`postgresql-server-dev-NN` on Debian/Ubuntu).

```bash
cd pg/
make USE_PGXS=1
sudo make USE_PGXS=1 install
```

To build and run the regression tests in Docker against several versions:

```bash
cd pg/
./docker-test.sh          # PG 15, 16, 17, 18
./docker-test.sh 17 18    # chosen versions
```

### Usage

The extension is marked `trusted = true`, like contrib's `unaccent`, so once it is installed on the server any user with CREATE privilege on a database, such as its owner, can run `CREATE EXTENSION dict_croatian_stem` without superuser. If you do not want that, delete the `trusted` line from `dict_croatian_stem.control` before installing.

```sql
CREATE EXTENSION dict_croatian_stem;
-- Creates the croatian_stem dictionary, the croatian_stem_template
-- template, and the croatian text search configuration.

SELECT to_tsvector('croatian', 'Veliki grad ima lijepe kuće');
-- 'grad':2 'im':3 'kuć':5 'lijep':4 'velik':1

SELECT to_tsvector('croatian', 'Lijepe kuće u velikom gradu')
    @@ to_tsquery('croatian', 'kuća & grad');
-- t

SELECT ts_lexize('croatian_stem', 'gradovima');   -- {grad}
SELECT ts_lexize('croatian_stem', 'sam');         -- {}  (stop word)
```

The dictionary always drops the built-in stop words. To drop more, create a dictionary from the template with your own list in `$SHAREDIR/tsearch_data/<name>.stop`:

```sql
CREATE TEXT SEARCH DICTIONARY my_croatian_stem (
    TEMPLATE = croatian_stem_template,
    StopWords = my_croatian
);
```

## How it works

1. **Stop words.** The 67 auxiliary and modal forms are returned unchanged.
2. **Superlatives.** A leading *naj-* is peeled off, so *najveći*, *veći* and *velik* can meet.
3. **Transformations.** 159 suffix rewrites undo consonant alternations (palatalization, sibilarization, jotation) and fleeting *a*.
4. **Suffix stripping.** 81 ordered rules, each a stem pattern plus a set of suffixes. The first rule that leaves a stem with a vowel and more than one character wins. Syllabic *r* (*trg*, *krv*, *prst*) counts as a vowel.
5. **Verbs.** The thematic vowel is dropped the same way in every form, so *raditi*, *radim*, *radila* and *radi* all give *rad*, and *vidjeti*, *vidio* and *vidi* give *vid*. *-ovati*/*-ivati* verbs and their *-uj-* present share a stem (*djelovati*, *djeluje* → *djeliv*), and the *-ići* compounds keep their *đ* (*došao*, *dođe* → *dođ*).
6. **Participles.** Passive participles lose *-en*, *-an*, *-iran* or *-nut* and undo the root alternation, so they meet their verb (*objavljen* → *objav*, *korišten* → *korist*, *organiziran* → *organizir*).
7. **Clean-up.** Fleeting *a* (*posao*/*posla*, *postupak*/*postupka*, *kupac*/*kupca*, *metar*/*metra*), the *-ov-*/*-ev-* plural extension and comparative *-ij* are normalized so related forms share a stem.

## Evaluation

The rules were tuned on [hr500k](https://www.clarin.si/repository/xmlui/handle/11356/1792) (CLARIN.SI, CC BY-SA 4.0; 427,270 word tokens with gold lemmas and parts of speech), so hr500k numbers are in-sample. The held-out check is [ParlaMint-HR 4.1](http://hdl.handle.net/11356/1911) (CLARIN.SI, CC BY 4.0): Croatian parliamentary debates from 2003 to 2022, 85.4 million word tokens, lemmatized and tagged automatically by CLASSLA-Stanza. None of it was looked at during tuning.

The 67 stop words are left out of the scoring, since `stem()` returns them unchanged and text search drops them.

| Metric | v0.1, hr500k | This stemmer, hr500k | v0.1, ParlaMint-HR | This stemmer, ParlaMint-HR |
|---|---|---|---|---|
| Form-level consistency (forms that get their lemma's majority stem) | 78.4% | 94.3% | 76.3% | 94.4% |
| The same, weighted by how often each form occurs | 82.8% | 91.9% | 82.9% | 91.3% |
| Lemma consistency (multi-form lemmas whose forms all share one stem) | 58.6% | 87.4% | 57.2% | 87.3% |
| Over-stemming (stems shared by 2+ lemmas) | 8.6% | 11.7% | 16.2% | 19.8% |
| Lemma consistency for nouns / adjectives / verbs | 66.7 / 75.5 / 20.9% | 91.3 / 94.8 / 82.3% | 61.9 / 73.5 / 16.8% | 90.4 / 93.0 / 78.8% |

The v0.1 hr500k figures (78.4% form-level consistency, 8.6% over-stemming) differ slightly from [docs/evaluation.md](https://github.com/brahle/croatian-stemmer/blob/main/docs/evaluation.md) (78.3%, 8.7%) because the stop words are now left out of the scoring.

The gains over v0.1 hold on the held-out corpus, so the rules generalize rather than fit hr500k. Much of the added over-stemming is a verb meeting its own noun or participle (*dokaz*/*dokazati*, *određen*/*odrediti*), which the corpora lemmatize separately but which is usually what search wants. Over-stemming grows with vocabulary size (ParlaMint has six times as many distinct form/lemma pairs as hr500k), so compare it between stemmers on the same corpus, not across corpora. An evaluation against human judgments is in progress; see [docs/labeling.md](https://github.com/brahle/croatian-stemmer/blob/main/docs/labeling.md).

An earlier version also carried a hand-built lexicon of about 3,800 verb and adjective forms chosen from hr500k failures. It raised hr500k verb consistency from 28.3% to 36.3% but ParlaMint-HR verb consistency only from 22.8% to 23.1% (both measured with the stop words included), so it was removed.

To reproduce, download `hr500k.conllup` into `data/` and run:

```bash
python evaluate.py          # full hr500k report
python evaluate_score.py    # the composite score used during tuning

# held-out: stream ParlaMint-HR.ana.tgz from the link above
tar -xzOf ParlaMint-HR.ana.tgz '*.conllu' | python evaluate_score.py --corpus -
```

[docs/evaluation.md](https://github.com/brahle/croatian-stemmer/blob/main/docs/evaluation.md) is the detailed report for the v0.1 baseline.

### How the rules were tuned

The rules were tuned by an automated agent working in a loop. [AUTORESEARCH.md](https://github.com/brahle/croatian-stemmer/blob/main/AUTORESEARCH.md) is the brief it was given, and [results.tsv](https://github.com/brahle/croatian-stemmer/blob/main/results.tsv) is its experiment log, one row per experiment. The loop only ever saw hr500k; ParlaMint-HR was the held-out check, run between loops. Per-word lists (lexicons, exception tables, extra stop words) are banned, so every change is a general rule or algorithm change.

## Development

```bash
pip install -e ".[dev]"
pytest                      # Python tests, plus C/Python parity if a C compiler is present
python gen_rules_c.py       # regenerate pg/croatian_stemmer_rules.h after editing rules.py
```

CI regenerates the C rule header and fails if it differs from the committed one.

## Repository layout

```
src/croatian_stemmer/      Python package (stemmer.py, rules.py, CLI)
src/croatian_stemmer/labeling/  optional human-labeling tools and web app
tests/                     pytest suite, including C/Python parity
pg/                        PostgreSQL extension, C stemmer and regression tests
gen_rules_c.py             generates pg/croatian_stemmer_rules.h from rules.py
evaluate.py, evaluate_score.py   corpus evaluation
AUTORESEARCH.md            brief for the automated rule-tuning agent
results.tsv                tuning experiment log, one row per experiment
docs/                      research notes, evaluation reports, labeling guides
build.sh                   builds and pushes the labeling app image
Dockerfile.web             container image for the labeling app
migrations/, alembic.ini   labeling app database migrations (Alembic)
scripts/                   labeling app asset build and test runner
package.json               labeling app JS dependencies (Keycloak adapter, Playwright)
requirements-web.txt       hashed, pinned dependencies for the labeling container
```

The labeling app (a public, multi-user site: Keycloak/Google sign-in, consent gate, shared curator-published corpora, judgment forms, exports) is optional and is not needed to use the stemmer. It runs from a checkout (`pip install -e ".[web]"`) or the container built from `Dockerfile.web`, not from the PyPI package, which ships only the offline `croatian-stemmer-labels` tools. See [docs/labeling-web.md](https://github.com/brahle/croatian-stemmer/blob/main/docs/labeling-web.md).

## References

- Ljubešić, N., Boras, D., & Kubelka, O. (2007). Retrieving Information in Croatian: Building a Simple and Efficient Rule-Based Stemmer. In *INFuture2007: Digital Information and Heritage*, 313–320. Zagreb.
- Ljubešić, N., & Pandžić, I. (2012). Simple stemmer for Croatian v0.1. http://nlp.ffzg.hr/resources/tools/stemmer-for-croatian/
- Ljubešić, N., et al. hr500k, a reference training corpus of Croatian, v2.0. CLARIN.SI. http://hdl.handle.net/11356/1792

## License

GNU Lesser General Public License v3.0 or later; see [COPYING.LESSER](https://github.com/brahle/croatian-stemmer/blob/main/COPYING.LESSER) and [COPYING](https://github.com/brahle/croatian-stemmer/blob/main/COPYING). The stop list, transformations and suffix rules come from "Simple stemmer for Croatian v0.1", Copyright 2012 Nikola Ljubešić and Ivan Pandžić, also LGPL-3.0-or-later.

The hr500k corpus is not included. It is licensed CC BY-SA 4.0 by its authors.

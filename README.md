# Croatian Stemmer

A rule-based stemmer for Croatian, available as a Python library and as a PostgreSQL text search dictionary. Both implementations produce identical stems.

It starts from the Ljubešić–Pandžić stemmer ("Simple stemmer for Croatian v0.1", 2012), which refines the algorithm from Ljubešić, Boras & Kubelka (2007). On top of that it adds extra suffix rules, post-processing for comparatives, jotation and fleeting *a*, and a lexicon of about 3,800 inflected forms that maps irregular paradigms to one stem per lemma. These additions were tuned against the hr500k corpus; see [Evaluation](#evaluation) for what that means for the numbers.

## Python

Requires Python 3.10 or newer.

```bash
pip install git+https://github.com/brahle/croatian-stemmer
```

```python
from croatian_stemmer import stem, stem_text

stem("gradovima")   # "grad"
stem("kuće")        # "kuć"
stem("lijepog")     # "lijep"
stem("metara")      # "metr"   (fleeting a)
stem("najvećih")    # "već"    (superlative prefix)
stem("saznali")     # "saznat" (lexicon: every form of saznati)

stem_text("Veliki grad ima lijepe kuće")
# ["velik", "grad", "imat", "lijep", "kuć"]

stem_text("Ja sam bio u gradu")
# ["ja", "u", "grad"]   (stop words "sam" and "bio" are dropped)
```

`stem()` stems any single word. `stem_text()` tokenizes, lowercases and stems running text, dropping the 67 stop words: forms of the auxiliaries and modals *biti*, *htjeti*, *željeti*, *morati*, *trebati* and *moći*. Passing a stop word to `stem()` returns its lemma's stem (`stem("sam") == "bit"`).

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

```sql
CREATE EXTENSION dict_croatian_stem;
-- Creates the croatian_stem dictionary, the croatian_stem_template
-- template, and the croatian text search configuration.

SELECT to_tsvector('croatian', 'Veliki grad ima lijepe kuće');
-- 'grad':2 'imat':3 'kuć':5 'lijep':4 'velik':1

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

1. **Lexicon.** Forms listed in the lexicon return their lemma's canonical stem. This covers suppletive and irregular paradigms (*biti*, *htjeti*, *ići*, *dati*, …) and a few hundred frequent verbs.
2. **Superlatives.** A leading *naj-* is peeled off, so *najveći*, *veći* and *velik* can meet.
3. **Transformations.** 132 suffix rewrites undo consonant alternations (palatalization, sibilarization, jotation) and fleeting *a*.
4. **Suffix stripping.** 75 ordered rules, each a stem pattern plus a set of suffixes. The first rule that leaves a stem with a vowel and more than one character wins. Syllabic *r* (*trg*, *krv*, *prst*) counts as a vowel.
5. **Clean-up.** The *-ov-*/*-ev-* plural extension, comparative *-ij*, jotation and short palatalized stems are normalized so related forms share a stem.

## Evaluation

Measured on [hr500k](https://www.clarin.si/repository/xmlui/handle/11356/1792) (CLARIN.SI, CC BY-SA 4.0): 427,270 word tokens with gold lemmas and parts of speech.

| Metric | v0.1 rules | This stemmer |
|---|---|---|
| Form-level consistency (forms that get their lemma's majority stem) | 78.3% | 87.7% |
| Lemma consistency (multi-form lemmas whose forms all share one stem) | 58.6% | 74.5% |
| Over-stemming (stems shared by 2+ lemmas) | 8.7% | 10.2% |
| Nouns / adjectives / verbs, form-level | 66.7% / 75.5% / 20.9% | 85.9% / 93.8% / 36.3% |

The extra rules, the lexicon and the post-processing were all chosen by measuring against this same corpus (see [AUTORESEARCH.md](AUTORESEARCH.md) and [results.tsv](results.tsv)), so the right-hand column is an in-sample number and overstates accuracy on unseen text. Most of the verb gain comes from the lexicon: with only the stop words in the lexicon, verbs score 28.3% and form-level consistency is 86.2%. A held-out evaluation against human judgments is in progress; `src/croatian_stemmer/labeling` and [docs/labeling.md](docs/labeling.md) describe it.

To reproduce, download `hr500k.conllup` into `data/` and run:

```bash
python evaluate.py          # full report
python evaluate_score.py    # the composite score used during tuning
```

[docs/evaluation.md](docs/evaluation.md) is the detailed report for the v0.1 baseline.

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
evaluate.py, evaluate_score.py   hr500k evaluation
docs/                      research notes and evaluation reports
```

The labeling app (Keycloak login, judgment forms, TSV export) is optional and is not needed to use the stemmer. See [docs/labeling-web.md](docs/labeling-web.md).

## References

- Ljubešić, N., Boras, D., & Kubelka, O. (2007). Retrieving Information in Croatian: Building a Simple and Efficient Rule-Based Stemmer. In *INFuture2007: Digital Information and Heritage*, 313–320. Zagreb.
- Ljubešić, N., & Pandžić, I. (2012). Simple stemmer for Croatian v0.1. http://nlp.ffzg.hr/resources/tools/stemmer-for-croatian/
- Ljubešić, N., et al. hr500k, a reference training corpus of Croatian, v2.0. CLARIN.SI. http://hdl.handle.net/11356/1792

## License

GNU Lesser General Public License v3.0 or later; see [COPYING.LESSER](COPYING.LESSER) and [COPYING](COPYING). The stop list, transformations and suffix rules come from "Simple stemmer for Croatian v0.1", Copyright 2012 Nikola Ljubešić and Ivan Pandžić, also LGPL-3.0-or-later.

The hr500k corpus is not included. It is licensed CC BY-SA 4.0 by its authors.

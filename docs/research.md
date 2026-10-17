# Research: Croatian Stemmer for PostgreSQL

## 1. The Ljubesic-Pandzic Stemming Algorithm

### Original Paper

**Title:** "Retrieving Information in Croatian: Building a Simple and Efficient Rule-Based Stemmer"
**Authors:** Nikola Ljubesic, Damir Boras, Ozren Kubelka (2007)
**Published in:** *Digital Information and Heritage*, pp. 313-320, Department for Information Sciences, Faculty of Philosophy, Zagreb.

The implementation is commonly attributed to Nikola Ljubesic and Ivan Pandzic (co-author on the code, while the paper has Boras and Kubelka).

**Performance (from paper):**
- F1 = 97.82% (without adjective rules), 97.64% (with adjective rules)
- Evaluated on lemmatized newspaper corpus: precision 0.986, recall 0.961 (F1 0.973) for adjectives/nouns
- Overall: precision 0.98, recall 0.92 (F1 0.947)
- Optimized via steepest ascent hill climbing on a corpus sample + morphological lexicon + 1,000 most frequent Croatian nouns

**Related paper:** "Building a Croatian language stemmer" -- available on [hrcak.srce.hr](https://hrcak.srce.hr/clanak/220922)

### Algorithm Overview

Three phases:

**Phase 1: Stop word check**
~50 stop words (forms of "biti"/to be, modal verbs: zelim, moram, trebam, mogu, and conjugations). Matched words returned unchanged.

**Phase 2: Morphophonological transformations**
~130 suffix transformations handling consonant alternations during Croatian inflection:
- Palatalization: `lozi` -> `loga` (g->z)
- Sibilarization: `vojci` -> `vojka` (k->c)
- Jotation: `oscu` -> `osti` (instrumental of -ost nouns)
- Fleeting-a: `metara` -> `metra`, `centar` -> `centra`
- Others: `izam` -> `izma`

Applied before suffix stripping to normalize the stem.

**Phase 3: Suffix stripping via regex**
~70 paired regex rules, each with:
- `word_start`: regex matching the stem (e.g., `.+(s|s)k`, `.+an`, `.+in`)
- `word_end`: pipe-delimited suffixes, longest-first

Compiled into `^(word_start)(word_end)$`. First match wins if:
1. Stem contains a vowel (including syllabic R -- Croatian: "trg", "krv", "prst")
2. Stem is longer than 1 character

Rules cover: noun declension (7 cases x 2 numbers), adjective declension (definite/indefinite, comparison), verb conjugation (present, aorist, imperfect, imperative, participles), and some derivational suffixes.

## 2. Existing Implementations

### Java (most complete)
- **vukbatanovic/SCStemmers** -- https://github.com/vukbatanovic/SCStemmers
  - 4 stemmers including Ljubesic-Pandzic, GPL-3.0, Weka plugin + CLI
  - Well-documented, cite: Batanovic et al. (2016), LREC 2016

### Python
- **rpetar/SCStemmers** -- https://github.com/rpetar/SCStemmers
  - Direct port of the Java version, contains `ljubesic_pandzic_stemmer.py` + `constants.py` with all rules
  - **Most useful reference for understanding the algorithm in Python**
- **dmarsic/StemmerHr** -- https://github.com/dmarsic/StemmerHr (LGPL-3.0)
  - Independent implementation, API: `StemmerHr().stem('price')` -> `'pric'`
- **luismsgomes/croatian_stemmer** -- https://github.com/luismsgomes/croatian_stemmer (minimal)

### C (with PostgreSQL extension)
- **ivoras/hrstemc** -- https://github.com/ivoras/hrstemc
  - C library implementing the Ljubesic stemmer
  - **Includes a PostgreSQL dictionary extension** (PLpgSQL component)
  - Uses external `rules.txt` and `transformations.txt` files + PCRE for regex
  - Key function: `hrstemc_korjenuj()`

### Other
- **mfolnovic/croatian-stemmer** -- Scala
- **denisristic/elasticsearch-croatian-stemmer** -- Java, Elasticsearch plugin
- **TarikOmanovic/postgres-croatian-stemmer** -- C, abandoned (2 commits, no docs)

## 3. hr500k Corpus

**Full title:** "hr500k -- A Reference Training Corpus of Croatian"
**Authors:** Nikola Ljubesic, Zeljko Agic, et al. (CLASSLA / ReLDI Centre Belgrade)

### Specifications
- ~500,000 tokens (901 documents, 24,763 sentences, 499,635 tokens)
- Manually annotated with:
  - Tokenization and sentence segmentation
  - Morphosyntactic tagging (MULTEXT-East V5 tagset) and **lemmatization** (full corpus)
  - Named entities (full corpus)
  - Dependency syntax per Universal Dependencies v2 (~40%)
  - Multi-word expressions (subset)
  - Semantic role labels (~20%)

### Download
- **CLARIN.SI v2.0 (2023):** https://www.clarin.si/repository/xmlui/handle/11356/1792
- **CLARIN.SI v1.0:** https://www.clarin.si/repository/xmlui/handle/11356/1183
- **Hugging Face:** https://huggingface.co/datasets/classla/hr500k (configs: `ner`, `ud`, `upos`)

**Format:** CoNLL-U-Plus (.conllup), also Parquet on HuggingFace
**License:** CC BY-SA 4.0

### Evaluation Strategy
The corpus contains lemmas for every token. Evaluate the stemmer by checking:
- **Consistency:** tokens sharing a lemma should map to the same stem
- **Discrimination:** tokens with different lemmas should map to different stems
- Train/dev/test splits already defined
- Load via: `load_dataset("classla/hr500k", "upos")`

## 4. PostgreSQL Integration Options

### Option A: Custom PGXS Extension (recommended)
Write a C extension implementing the Ljubesic-Pandzic algorithm as a text search dictionary template. The rules are compact (~130 transformations + ~70 regex patterns) and can be embedded in C.

**Prior art:** `ivoras/hrstemc` already does this but uses PCRE (external dependency). We can avoid PCRE by implementing the patterns directly in C.

### Option B: Hunspell Dictionary
PostgreSQL supports Hunspell via `CREATE TEXT SEARCH DICTIONARY ... TEMPLATE = ispell`. Croatian Hunspell files (`hr_HR.aff`, `hr_HR.dic`) are available in:
- LibreOffice dictionaries: https://github.com/LibreOffice/dictionaries (hr_HR/)
- spideyfusion/elasticsearch-croatian (diacritics-stripped variant)

**Tradeoffs:** Hunspell gives lemmatization (better than stemming) but is slower and requires maintaining the dictionary file.

### Option C: Snowball Integration
Write the stemmer in Snowball language and compile to C. PostgreSQL already uses Snowball for its built-in stemmers. This would be the most "native" integration path but requires learning the Snowball language.

## 5. Recommended Approach

1. **Start with Python** -- port from `rpetar/SCStemmers` or `dmarsic/StemmerHr`, clean up, add tests
2. **Evaluate on hr500k** -- verify correctness before committing to C port
3. **PGXS extension in C** -- embed rules directly (no PCRE dependency), register as text search dictionary
4. **Consider Snowball** -- if we want upstream PostgreSQL contribution potential

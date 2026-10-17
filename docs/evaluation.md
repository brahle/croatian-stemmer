# Evaluation: Croatian Stemmer on hr500k Corpus

> This report describes the v0.1 baseline, before the rule additions were tuned
> against hr500k. The README has the current numbers, including a held-out
> evaluation on ParlaMint-HR.

**Date:** 2026-04-11
**Corpus:** hr500k v2.0 (CLARIN.SI), 427,270 word tokens, 65,685 unique form-lemma pairs
**Stemmer:** Ljubešić-Pandžić algorithm, Python port v0.1.0

## Summary Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Lemma consistency | 58.6% | Of lemmas with 2+ forms, % where all forms get the same stem |
| Form-level consistency | 78.3% | % of individual word forms assigned to the majority stem for their lemma |
| Over-stemming rate | 8.7% | % of unique stems that conflate 2+ different lemmas |
| Avg chars removed | 0.74 | Average suffix length stripped |
| Unchanged token ratio | 39.8% | Tokens returned without modification |

## Interpretation

**Consistency (under-stemming):** 58.6% of lemmas with multiple observed forms are fully consistently stemmed. At the form level, 78.3% of tokens end up in the correct majority group. The stemmer struggles with:
- **Comparative/superlative adjectives** — forms with "ij" suffixes (e.g., stariji/najstariji) split from the base form
- **Irregular verbs** — "biti" (43 forms) splits into 38 different stems
- **Suppletive forms** — "dobar/bolji/najbolji" cannot be unified by suffix stripping

**Discrimination (over-stemming):** 91.3% of unique stems map to exactly one lemma. The 8.7% over-stemming mostly involves very short stems (2-3 chars) where distinct short words collapse.

## Consistency by Part of Speech

| POS | Tokens | Lemmas (2+) | Consistent | Rate |
|-----|--------|-------------|------------|------|
| PROPN | 22,063 | 1,457 | 1,162 | 79.8% |
| ADJ | 52,126 | 3,222 | 2,432 | 75.5% |
| NOUN | 111,144 | 5,345 | 3,566 | 66.7% |
| X | 4,371 | 57 | 36 | 63.2% |
| ADP | 44,602 | 4 | 2 | 50.0% |
| ADV | 25,460 | 103 | 43 | 41.7% |
| VERB | 48,197 | 2,119 | 443 | 20.9% |
| DET | 21,085 | 41 | 7 | 17.1% |
| PRON | 19,026 | 21 | 1 | 4.8% |
| AUX | 31,139 | 13 | 0 | 0.0% |

**Key observations:**
- **Nouns (66.7%) and adjectives (75.5%)** perform well — the algorithm was specifically optimized for these in the original paper (reported F1 0.973 for nouns/adjectives)
- **Proper nouns (79.8%)** are mostly consistent since they have limited declension
- **Verbs (20.9%)** are the weakest category — Croatian verb morphology is complex with many conjugation patterns, and the stemmer was not optimized for verbs
- **Pronouns/determiners** are very inconsistent due to suppletive forms

## Over-stemming Analysis

Top conflating stems (stems that merge different lemmas):

| Stem | Lemmas conflated | Examples |
|------|----------------:|----------|
| mi | 11 | ja, mi, mija, mije, mila, mile... |
| je | 10 | biti, jej, jeju, jel, jela... |
| si | 9 | biti, sebe, sijati, sila, sim... |
| rad | 7 | rad, rada, rade, radi, raditi, rado |
| on | 7 | on, ona, onaj, one, oni, ono |

Most over-stemming occurs with 2-3 character stems where unrelated short words collapse.

## Comparison to Published Results

The original paper (Ljubešić et al., 2007) reported:
- **Precision 0.986, Recall 0.961 (F1 0.973)** for adjectives/nouns on a newspaper corpus
- **Overall precision 0.98, recall 0.92 (F1 0.947)**

Our evaluation uses different metrics (consistency/discrimination rather than precision/recall against lemmatization), but the results are broadly consistent:
- Nouns and adjectives perform best (66.7% and 75.5% full consistency)
- The algorithm was explicitly not optimized for verbs, and our 20.9% verb consistency confirms this

## Known Limitations

1. **No comparative/superlative handling** — "velik/veći/najveći" split because the "ij" comparative suffix interacts poorly with the suffix rules
2. **Suppletive forms untouched** — "dobar/bolji", "loš/gori" cannot be unified by any suffix-stripping algorithm
3. **Verb conjugation weakness** — Croatian has complex verb morphology that this algorithm only partially covers
4. **Short words vulnerable** — words under 4 characters often over-stem

## Recommendations for PostgreSQL Extension

For information retrieval (the primary use case):
- The stemmer is adequate for **nouns and adjectives**, which carry most search-relevant content
- Verbs and function words are less critical for IR since they're often stop-words
- Consider pairing the stemmer with a Croatian stop word list in the PG text search configuration
- The 8.7% over-stemming rate is acceptable for IR (slight recall improvement at minimal precision cost)

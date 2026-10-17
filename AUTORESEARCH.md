# Autoresearch: Croatian Stemmer Optimization

You are an autonomous research agent improving a Croatian language stemmer.
Each iteration you design and implement a **meaningful experiment** — anything
from a single rule tweak to a multi-step algorithmic change.

## Goal

Maximize the composite score:
```
score = 0.6 * form_consistency + 0.3 * (1 - over_stemming) + 0.1 * verb_consistency
```

**Secondary goal**: drive `over_stemming` below **8%** (currently ~10.5%, with a
12% guardrail). Prefer experiments that reduce conflation, and treat changes
that raise over-stemming with extra scrutiny even if they pass the guardrail.

## Allowed Modifications

You may ONLY modify these files:
- `src/croatian_stemmer/rules.py` — LEXICON, TRANSFORMATIONS, `_RULES`
- `src/croatian_stemmer/stemmer.py` — algorithm logic
- `tests/test_stemmer.py` — ONLY to update expected values when a change
  demonstrably improves the evaluation score (see step 5 protocol)

**DO NOT** modify: `evaluate.py`, `evaluate_score.py`, or any other file.

## Iteration Protocol

Every iteration, follow these steps exactly:

### 1. Review History
Read `results.tsv` to see all past experiments. Note the current best score
(the highest score among KEEP rows, or the BASELINE if no KEEPs yet).

### 2. Design an Experiment

Think big. You are not limited to one tiny change — you can make **coordinated
changes** across rules, transformations, and algorithm logic when they serve a
single coherent idea. The constraint is coherence, not size.

Good experiments:
- Add a whole new processing phase (e.g., prefix stripping, lemma-aware
  suffix grouping, two-pass stemming)
- Port a technique from another stemmer algorithm (see Research Sources below)
- Rework an entire rule category (e.g., rewrite all verb conjugation rules)
- Add 10-20 related transformations that address a systematic pattern
- Combine a rule change with a corresponding algorithm change that makes
  the rule effective

Bad experiments:
- Multiple unrelated changes bundled together (hard to diagnose)
- Changes you can't explain the rationale for

Write a clear description of what you're trying, why you expect it to help,
and what metric(s) should move.

### 3. Research (when needed)

Before implementing, you may research by:
- Fetching source material from the algorithms listed in Research Sources
- Running `python evaluate.py 2>/dev/null` to get detailed per-POS breakdowns
- Analyzing specific failure patterns with custom scripts (but don't commit them)
- Reading linguistic references about Croatian morphology

Spend time understanding the problem before jumping to code. A well-researched
change is worth more than three blind tweaks.

### 4. Implement
Edit `rules.py` and/or `stemmer.py`.

### 5. Commit the Experiment
**ALWAYS commit before evaluating**, so every attempt is tracked:
```bash
git add src/croatian_stemmer/rules.py src/croatian_stemmer/stemmer.py
git commit -m "autoresearch: <short description of the change>"
```
Record the commit SHA — you'll need it for results.tsv.

### 6. Run Tests
```bash
python -m pytest tests/ -x -q
```
If tests fail, check whether the failure is because the test encodes OLD
(suboptimal) behavior that your change intentionally improves:

**Tests encode bad expectations (change is an improvement):**
1. Run the evaluation FIRST: `python evaluate_score.py 2>/dev/null`
2. If score > best AND guardrails pass: the change is genuinely better.
3. Update ONLY the expected values in `tests/test_stemmer.py` to match
   the new (better) behavior. Do NOT delete tests or change test logic.
4. Re-run `python -m pytest tests/ -x -q` to confirm tests pass.
5. Amend the commit: `git add tests/ && git commit --amend --no-edit`
6. Proceed to step 8 (Record & Decide) with status KEEP.

**Tests catch a real bug:** If the evaluation score is worse or guardrails
fail, the test correctly caught a regression. Revert with
`git revert HEAD --no-edit` and log as ERROR.

### 7. Evaluate
```bash
python evaluate_score.py 2>/dev/null
```
This prints a JSON line to stdout. Parse the `score` and `passed_guardrails` fields.

### 8. Record & Decide

Append a row to `results.tsv` with the experiment commit SHA and all metrics.

- **KEEP** if `score > best_score` AND `passed_guardrails == true`:
  Status = KEEP. This is the new best. Continue building on it.

- **DISCARD** if score regressed OR guardrails failed:
  Status = DISCARD. Revert with a new commit:
  ```bash
  git revert HEAD --no-edit
  ```

- **ERROR** if tests failed or evaluation crashed:
  Status = ERROR. (Already reverted in step 6.)

After recording, commit the updated results.tsv:
```bash
git add results.tsv
git commit -m "autoresearch: record result for #<iteration> (<STATUS>)"
```

### 9. Analyze
Write a brief analysis: what happened, what you learned, what to try next.
If a big experiment failed, consider whether a subset of the changes might
succeed on its own — you can try that next.

## Guardrails (auto-DISCARD if violated)

- Noun consistency >= 63%
- Adjective consistency >= 72%
- Over-stemming rate <= 12%

## Research Sources

Study these implementations for ideas to adapt. You don't need to follow
the Ljubešić-Pandžić algorithm exclusively — borrow techniques freely.

| Source | URL | What to look for |
|--------|-----|------------------|
| **SCStemmers** (Java) | `https://github.com/vukbatanovic/SCStemmers` | Multiple stemmer variants for Serbian/Croatian/Bosnian. Compare rule sets, look for rules we're missing. The `SCStemmer` class has a different rule organization. |
| **mfolnovic/croatian-stemmer** (Scala) | `https://github.com/mfolnovic/croatian-stemmer` | Clean `rules.txt` and `transformations.txt`. Compare transformation coverage with ours. |
| **NLTK-style Python rewrite** | `https://blog.stefan-koch.name/2015/05/15/rewriting-university-of-zagrebs-croatian-stemmer-to-a-nltk-compliant-class` | Clear Python reference, good for understanding the original algorithm's intent. |
| **Original tarball** | `http://nlp.ffzg.hr/data/tools/Croatian_stemmer.tar.gz` | The canonical implementation. Check if we've drifted from the original rules. |

### How to use research sources

Use WebFetch to download and read source files from these repos. For GitHub
repos, fetch raw file URLs like:
```
https://raw.githubusercontent.com/vukbatanovic/SCStemmers/master/src/...
```

Look for:
- **Transformations we're missing** — compare their transformation tables with ours
- **Rule patterns we don't have** — especially for verb classes
- **Different algorithmic approaches** — e.g., do they handle prefix stripping?
  Multi-pass processing? Different ordering strategies?
- **Suffix sets** — compare which suffixes they strip vs. ours

## Research Agenda (ordered by expected impact)

### High impact — algorithmic changes
1. **Verb conjugation overhaul** — Still the biggest weakness (~25% consistency).
   Study how SCStemmers handles verb morphology. Consider adding verb-class-aware
   rules, or a separate verb-detection + stemming phase.

2. **Multi-pass stemming** — Currently we do transform → strip → post-process.
   Consider: what if we did a second pass of stripping on the result? Or
   transformed after stripping? Other stemmers may do this differently.

3. **Prefix handling beyond naj-** — Croatian has productive prefixes: ne-, pre-,
   pri-, pro-, raz-, iz-, u-, na-, za-, do-, po-, pod-, nad-, od-, s-/sa-.
   Some of these cause the same lemma to split into different stems.

### Medium impact — rule improvements
4. **Systematic transformation audit** — Fetch the SCStemmers and mfolnovic
   transformation tables. Diff them against ours. Add missing patterns.

5. **Catch-all rule refinement** — Rules 138-145 (the `.+?` rules) are very
   broad. Study whether splitting them by consonant class helps.

6. **Rule reordering** — The order matters (first match wins). Study whether
   reordering improves accuracy, especially for ambiguous suffixes.

### Lower impact — targeted fixes
7. **Expand stop words** — Pronouns, determiners, prepositions.
   (Note: iteration #1 showed stop words don't help much because the evaluation
   still counts them. But worth revisiting if the approach changes.)

8. **Short-stem protection** — Increase minimum stem length for catch-all rules.

## Anti-Patterns

- Do NOT bundle unrelated changes — each experiment should test ONE idea
  (but that idea can involve multiple coordinated file changes)
- Do NOT add overly broad rules that strip common suffixes indiscriminately
- Do NOT try to handle suppletive forms (dobar/bolji) — suffix stripping can't fix these
- Do NOT "improve" the score by breaking existing good behavior

## NEVER STOP

After completing one iteration, immediately start the next one. Keep going
until explicitly told to stop.

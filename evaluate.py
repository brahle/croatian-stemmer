"""Evaluate the Croatian stemmer against the hr500k corpus.

Metrics:
1. Under-stemming index (UI): fraction of same-lemma pairs that get different stems
   (lower is better — means the stemmer groups related forms together)
2. Over-stemming index (OI): fraction of different-lemma pairs that get the same stem
   (lower is better — means the stemmer doesn't conflate unrelated words)
3. Stemmer strength: average number of characters removed per word

Reference: Paice (1994) "An evaluation method for stemming algorithms"
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from croatian_stemmer import stem
from evaluate_score import EXCLUDED_FORMS

CORPUS_PATH = Path(__file__).parent / "data" / "hr500k.conllup"


def load_hr500k() -> list[tuple[str, str, str]]:
    """Load hr500k corpus, return list of (token, lemma, upos) tuples."""
    print("Loading hr500k corpus...")
    pairs = []
    with open(CORPUS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            token_id, form, lemma, upos = parts[0], parts[1], parts[2], parts[3]
            # Skip multiword tokens (e.g., "1-2") and non-alphabetic
            if "-" in token_id or "." in token_id:
                continue
            if not form.isalpha():
                continue
            # The v0.1 stop words are returned unchanged and dropped from
            # text; see evaluate_score.py.
            if form.lower() in EXCLUDED_FORMS:
                continue
            pairs.append((form.lower(), lemma.lower(), upos))

    print(f"  Loaded {len(pairs)} word tokens ({len(set(p[:2] for p in pairs))} unique form-lemma pairs)")
    return pairs


def evaluate_consistency(pairs: list[tuple[str, str, str]]):
    """Measure how consistently the stemmer groups words with the same lemma."""
    # Group tokens by lemma
    lemma_to_tokens: dict[str, set[str]] = defaultdict(set)
    for token, lemma, _ in pairs:
        lemma_to_tokens[lemma].add(token)

    total_lemmas = 0
    consistent_lemmas = 0
    total_forms = 0
    consistently_stemmed_forms = 0
    stem_distribution: dict[int, int] = defaultdict(int)

    inconsistent_examples: list[tuple[str, dict[str, str]]] = []

    for lemma, tokens in lemma_to_tokens.items():
        if len(tokens) < 2:
            continue

        stems = {token: stem(token) for token in tokens}
        unique_stems = set(stems.values())

        total_lemmas += 1
        total_forms += len(tokens)
        stem_distribution[len(unique_stems)] += 1

        if len(unique_stems) == 1:
            consistent_lemmas += 1
            consistently_stemmed_forms += len(tokens)
        else:
            stem_counts = Counter(stems.values())
            most_common_count = stem_counts.most_common(1)[0][1]
            consistently_stemmed_forms += most_common_count
            if len(tokens) >= 4 and len(unique_stems) >= 3:
                inconsistent_examples.append((lemma, stems))

    consistency_rate = consistent_lemmas / total_lemmas if total_lemmas else 0
    form_consistency = consistently_stemmed_forms / total_forms if total_forms else 0

    print(f"\n=== Consistency (Under-stemming) ===")
    print(f"  Lemmas with 2+ forms: {total_lemmas}")
    print(f"  Fully consistent lemmas: {consistent_lemmas} ({consistency_rate:.1%})")
    print(f"  Form-level consistency: {form_consistency:.1%}")
    print(f"  Stem count distribution:")
    for n_stems in sorted(stem_distribution):
        count = stem_distribution[n_stems]
        print(f"    {n_stems} stem(s): {count} lemmas ({count/total_lemmas:.1%})")

    # Show some inconsistent examples
    inconsistent_examples.sort(key=lambda x: -len(x[1]))
    print(f"\n  Sample inconsistent lemmas:")
    for lemma, stems in inconsistent_examples[:10]:
        by_stem: dict[str, list[str]] = defaultdict(list)
        for token, s in stems.items():
            by_stem[s].append(token)
        groups = sorted(by_stem.items(), key=lambda x: -len(x[1]))
        parts = [f"'{s}':[{','.join(sorted(ts)[:3])}{'...' if len(ts) > 3 else ''}]" for s, ts in groups[:3]]
        print(f"    '{lemma}' ({len(stems)} forms, {len(set(stems.values()))} stems): {'; '.join(parts)}")

    return consistency_rate, form_consistency


def evaluate_discrimination(pairs: list[tuple[str, str, str]]):
    """Measure how well the stemmer keeps different lemmas apart."""
    stem_to_lemmas: dict[str, set[str]] = defaultdict(set)
    for token, lemma, _ in pairs:
        s = stem(token)
        stem_to_lemmas[s].add(lemma)

    conflating_stems = {s: lemmas for s, lemmas in stem_to_lemmas.items() if len(lemmas) > 1}
    total_stems = len(stem_to_lemmas)
    conflating_count = len(conflating_stems)

    print(f"\n=== Discrimination (Over-stemming) ===")
    print(f"  Unique stems: {total_stems}")
    print(f"  Stems mapping to 1 lemma: {total_stems - conflating_count} ({(total_stems - conflating_count)/total_stems:.1%})")
    print(f"  Stems conflating 2+ lemmas: {conflating_count} ({conflating_count/total_stems:.1%})")

    worst = sorted(conflating_stems.items(), key=lambda x: -len(x[1]))[:15]
    print(f"\n  Top conflating stems:")
    for s, lemmas in worst:
        lemma_sample = sorted(lemmas)[:6]
        extra = f" (+{len(lemmas)-6} more)" if len(lemmas) > 6 else ""
        print(f"    '{s}' -> {len(lemmas)} lemmas: {', '.join(lemma_sample)}{extra}")

    return conflating_count / total_stems if total_stems else 0


def evaluate_by_pos(pairs: list[tuple[str, str, str]]):
    """Break down consistency by part of speech."""
    pos_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for token, lemma, upos in pairs:
        pos_groups[upos].append((token, lemma))

    print(f"\n=== Consistency by POS ===")
    print(f"  {'POS':<8} {'Tokens':>8} {'Lemmas':>8} {'Consistent':>12} {'Rate':>8}")
    print(f"  {'-'*48}")

    pos_results = {}
    for upos in sorted(pos_groups, key=lambda p: -len(pos_groups[p])):
        pos_pairs = pos_groups[upos]
        lemma_to_tokens: dict[str, set[str]] = defaultdict(set)
        for token, lemma in pos_pairs:
            lemma_to_tokens[lemma].add(token)

        total = 0
        consistent = 0
        for lemma, tokens in lemma_to_tokens.items():
            if len(tokens) < 2:
                continue
            total += 1
            stems = {stem(t) for t in tokens}
            if len(stems) == 1:
                consistent += 1

        rate = consistent / total if total else 0
        pos_results[upos] = rate
        print(f"  {upos:<8} {len(pos_pairs):>8} {len(lemma_to_tokens):>8} {consistent:>12} {rate:>7.1%}")

    return pos_results


def evaluate_strength(pairs: list[tuple[str, str, str]]):
    """Measure stemmer strength — average reduction in word length."""
    total_removed = 0
    total_chars = 0
    unchanged = 0
    total = 0

    for token, _, _ in pairs:
        s = stem(token)
        removed = len(token) - len(s)
        total_removed += max(removed, 0)
        total_chars += len(token)
        total += 1
        if s == token:
            unchanged += 1

    avg_removed = total_removed / total if total else 0
    avg_reduction = total_removed / total_chars if total_chars else 0

    print(f"\n=== Stemmer Strength ===")
    print(f"  Total tokens: {total}")
    print(f"  Unchanged tokens: {unchanged} ({unchanged/total:.1%})")
    print(f"  Avg chars removed: {avg_removed:.2f}")
    print(f"  Avg reduction ratio: {avg_reduction:.1%}")

    return avg_removed, unchanged / total


def show_examples(pairs: list[tuple[str, str, str]], n: int = 20):
    """Show sample stemming results for lemmas with many forms."""
    lemma_to_tokens: dict[str, set[str]] = defaultdict(set)
    for token, lemma, _ in pairs:
        lemma_to_tokens[lemma].add(token)

    interesting = sorted(
        ((l, t) for l, t in lemma_to_tokens.items() if len(t) >= 4),
        key=lambda x: -len(x[1]),
    )[:n]

    print(f"\n=== Sample Results (top {n} lemmas by form count) ===")
    for lemma, tokens in interesting:
        sorted_tokens = sorted(tokens)[:8]
        stemmed = [(t, stem(t)) for t in sorted_tokens]
        stems = set(s for _, s in stemmed)
        marker = "OK" if len(stems) == 1 else f"SPLIT({len(stems)})"
        forms_str = ", ".join(f"{t}->{s}" for t, s in stemmed)
        extra = f" (+{len(tokens)-8} more forms)" if len(tokens) > 8 else ""
        print(f"  [{marker:>8}] '{lemma}' ({len(tokens)} forms): {forms_str}{extra}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", action="append", type=Path, default=[],
                        help="human annotation TSV; repeat for multiple exports")
    parser.add_argument("--labels-only", action="store_true",
                        help="evaluate labels without reading hr500k")
    parser.add_argument("--min-annotators", type=int, default=1)
    args = parser.parse_args(argv)
    if args.labels_only and not args.labels:
        parser.error("--labels-only requires --labels")
    if args.labels:
        from croatian_stemmer.labeling.evaluation import evaluate
        from croatian_stemmer.labeling.schema import load

        try:
            annotations, sources = load(args.labels)
            report = evaluate(annotations, stem, min_annotators=args.min_annotators)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        report["inputs"] = sources
        print("\n=== Human judgments (separate from corpus benchmark) ===")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.labels_only:
        return
    pairs = load_hr500k()

    print(f"\n{'='*60}")
    print(f"  Croatian Stemmer Evaluation on hr500k")
    print(f"{'='*60}")

    consistency, form_consistency = evaluate_consistency(pairs)
    over_stemming = evaluate_discrimination(pairs)
    evaluate_by_pos(pairs)
    avg_removed, unchanged_ratio = evaluate_strength(pairs)
    show_examples(pairs)

    print(f"\n{'='*60}")
    print(f"  Summary")
    print(f"{'='*60}")
    print(f"  Lemma consistency:      {consistency:.1%}")
    print(f"  Form-level consistency: {form_consistency:.1%}")
    print(f"  Over-stemming rate:     {over_stemming:.1%}")
    print(f"  Avg chars removed:      {avg_removed:.2f}")
    print(f"  Unchanged token ratio:  {unchanged_ratio:.1%}")


if __name__ == "__main__":
    main()

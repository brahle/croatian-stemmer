"""Machine-readable evaluation for the autoresearch loop.

Outputs a single JSON line to stdout with all metrics.
Human-readable summary goes to stderr.
Exit code 0 = success, 1 = broken code (import/syntax error).
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CORPUS_PATH = Path(__file__).parent / "data" / "hr500k.conllup"

# Guardrails — auto-discard if violated
NOUN_FLOOR = 0.63
ADJ_FLOOR = 0.72
OVER_STEMMING_CEILING = 0.12

# Composite score weights
W_FORM = 0.6
W_DISC = 0.3
W_VERB = 0.1


def load_corpus() -> list[tuple[str, str, str]]:
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
            if "-" in token_id or "." in token_id:
                continue
            if not form.isalpha():
                continue
            pairs.append((form.lower(), lemma.lower(), upos))
    return pairs


def compute_metrics(pairs, stem_fn):
    # --- Form-level consistency ---
    lemma_to_tokens: dict[str, set[str]] = defaultdict(set)
    for token, lemma, _ in pairs:
        lemma_to_tokens[lemma].add(token)

    total_forms = 0
    consistently_stemmed = 0
    for lemma, tokens in lemma_to_tokens.items():
        if len(tokens) < 2:
            continue
        stems = {t: stem_fn(t) for t in tokens}
        total_forms += len(tokens)
        stem_counts = Counter(stems.values())
        consistently_stemmed += stem_counts.most_common(1)[0][1]

    form_consistency = consistently_stemmed / total_forms if total_forms else 0

    # --- Over-stemming ---
    stem_to_lemmas: dict[str, set[str]] = defaultdict(set)
    for token, lemma, _ in pairs:
        stem_to_lemmas[stem_fn(token)].add(lemma)
    total_stems = len(stem_to_lemmas)
    conflating = sum(1 for lemmas in stem_to_lemmas.values() if len(lemmas) > 1)
    over_stemming = conflating / total_stems if total_stems else 0

    # --- Per-POS consistency ---
    pos_groups: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for token, lemma, upos in pairs:
        pos_groups[upos].append((token, lemma))

    def pos_consistency(upos: str) -> float:
        if upos not in pos_groups:
            return 0.0
        lt: dict[str, set[str]] = defaultdict(set)
        for token, lemma in pos_groups[upos]:
            lt[lemma].add(token)
        total = 0
        consistent = 0
        for lemma, tokens in lt.items():
            if len(tokens) < 2:
                continue
            total += 1
            if len({stem_fn(t) for t in tokens}) == 1:
                consistent += 1
        return consistent / total if total else 0.0

    noun_consistency = pos_consistency("NOUN")
    adj_consistency = pos_consistency("ADJ")
    verb_consistency = pos_consistency("VERB")

    return {
        "form_consistency": form_consistency,
        "over_stemming": over_stemming,
        "noun_consistency": noun_consistency,
        "adj_consistency": adj_consistency,
        "verb_consistency": verb_consistency,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", action="append", type=Path, default=[])
    parser.add_argument("--labels-only", action="store_true")
    parser.add_argument("--min-annotators", type=int, default=1)
    args = parser.parse_args(argv)
    if args.labels_only and not args.labels:
        parser.error("--labels-only requires --labels")
    # Import stemmer — catch syntax/import errors
    try:
        from croatian_stemmer import stem
    except Exception as e:
        json.dump({"error": f"import_failed: {e}"}, sys.stdout)
        print(file=sys.stdout)
        sys.exit(1)

    human_report = None
    if args.labels:
        from croatian_stemmer.labeling.evaluation import evaluate
        from croatian_stemmer.labeling.schema import load

        try:
            annotations, sources = load(args.labels)
            human_report = evaluate(annotations, stem, min_annotators=args.min_annotators)
        except (OSError, ValueError) as exc:
            parser.error(str(exc))
        human_report["inputs"] = sources
    if args.labels_only:
        print(json.dumps({"human_labels": human_report}, ensure_ascii=False))
        return

    print("Loading corpus...", file=sys.stderr)
    pairs = load_corpus()
    print(f"  {len(pairs)} tokens loaded", file=sys.stderr)

    print("Evaluating...", file=sys.stderr)
    metrics = compute_metrics(pairs, stem)

    # Composite score
    score = (
        W_FORM * metrics["form_consistency"]
        + W_DISC * (1 - metrics["over_stemming"])
        + W_VERB * metrics["verb_consistency"]
    )

    # Guardrails
    passed = (
        metrics["noun_consistency"] >= NOUN_FLOOR
        and metrics["adj_consistency"] >= ADJ_FLOOR
        and metrics["over_stemming"] <= OVER_STEMMING_CEILING
    )

    result = {
        "score": round(score, 6),
        "form_consistency": round(metrics["form_consistency"], 4),
        "over_stemming": round(metrics["over_stemming"], 4),
        "verb_consistency": round(metrics["verb_consistency"], 4),
        "noun_consistency": round(metrics["noun_consistency"], 4),
        "adj_consistency": round(metrics["adj_consistency"], 4),
        "passed_guardrails": passed,
    }
    if human_report is not None:
        result["human_labels"] = human_report

    # Human summary on stderr
    print(f"\n  Score:             {result['score']:.4f}", file=sys.stderr)
    print(f"  Form consistency:  {result['form_consistency']:.1%}", file=sys.stderr)
    print(f"  Over-stemming:     {result['over_stemming']:.1%}", file=sys.stderr)
    print(f"  Verb consistency:  {result['verb_consistency']:.1%}", file=sys.stderr)
    print(f"  Noun consistency:  {result['noun_consistency']:.1%}", file=sys.stderr)
    print(f"  Adj consistency:   {result['adj_consistency']:.1%}", file=sys.stderr)
    print(f"  Guardrails:        {'PASS' if passed else 'FAIL'}", file=sys.stderr)

    # Machine-readable JSON on stdout
    json.dump(result, sys.stdout)
    print(file=sys.stdout)


if __name__ == "__main__":
    main()

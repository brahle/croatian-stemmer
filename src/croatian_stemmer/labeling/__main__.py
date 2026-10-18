"""Offline candidate preparation, human-label evaluation, gold building, replay of a
scoring run from its restricted bundle, and public releases."""

import argparse
import json
import sys
from pathlib import Path

from croatian_stemmer import stem

from .candidates import prepare
from .evaluation import evaluate
from .schema import load


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidates = commands.add_parser("prepare", help="prepare suggestions from an existing CoNLL-U corpus")
    candidates.add_argument("corpus", type=Path)
    candidates.add_argument("--source-uri", required=True)
    candidates.add_argument("--license", required=True)
    candidates.add_argument("--pairs", type=int, default=10000)
    candidates.add_argument("--word-items", type=int, default=1000)
    candidates.add_argument("--seed", type=int, default=0)
    candidates.add_argument("--output", required=True, type=Path)
    scoring = commands.add_parser("evaluate", help="score versioned human annotation TSVs")
    scoring.add_argument("labels", nargs="+", type=Path)
    scoring.add_argument("--min-annotators", type=int, default=1)
    gold = commands.add_parser("gold", help="build bootstrap gold where the corpus is unambiguous")
    gold.add_argument("corpus", type=Path)
    gold.add_argument("--candidates", required=True, type=Path)
    gold.add_argument("--min-freq", type=int, default=5)
    gold.add_argument("--per-kind", type=int, default=400)
    gold.add_argument("--seed", type=int, default=1)
    gold.add_argument("--split", default="qualification=80", help="qualification=N: the first N per kind")
    gold.add_argument("--exclude", type=Path, help="file of item ids (one per line) never to use")
    gold.add_argument("--output", required=True, type=Path)
    replay_ = commands.add_parser("score", help="replay a scoring run from its restricted bundle")
    replay_.add_argument("--bundle", required=True, type=Path, help="the run's bundle JSON (or a directory holding bundle.json)")
    replay_.add_argument("--output", required=True, type=Path, help="where to write the recomputed outputs (JSON)")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            records, receipt = prepare(args.corpus, source_uri=args.source_uri, license=args.license,
                                       pair_count=args.pairs, word_count=args.word_items, seed=args.seed)
            # Never overwrite either the caller's source or an existing export.
            with args.output.open("x", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            json.dump(receipt, sys.stdout, ensure_ascii=False)
        elif args.command == "gold":
            from .gold import build
            name, _, value = args.split.partition("=")
            if name != "qualification" or not value.isdigit():
                raise ValueError("--split must be qualification=N")
            exclude = args.exclude.read_text(encoding="utf-8").split() if args.exclude else ()
            rows, receipt = build(args.corpus, args.candidates, min_freq=args.min_freq, per_kind=args.per_kind,
                                  seed=args.seed, qualification=int(value), exclude=exclude)
            with args.output.open("x", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            json.dump(receipt, sys.stdout, ensure_ascii=False)
        elif args.command == "score":
            from .scoring import canonical, replay
            path = args.bundle / "bundle.json" if args.bundle.is_dir() else args.bundle
            result = replay(json.loads(path.read_text(encoding="utf-8")))
            with args.output.open("xb") as handle:
                handle.write(canonical(result["outputs"]))
            json.dump(result["report"], sys.stdout, ensure_ascii=False)
        else:
            labels, sources = load(args.labels)
            report = evaluate(labels, stem, min_annotators=args.min_annotators)
            report["inputs"] = sources
            json.dump(report, sys.stdout, ensure_ascii=False)
        print()
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()

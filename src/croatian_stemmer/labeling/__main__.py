"""Offline candidate preparation and human-label evaluation."""

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

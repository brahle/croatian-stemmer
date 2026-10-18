"""Offline candidate preparation (from CoNLL-U corpora or raw text), human-label
evaluation, gold building and checking,
replay of a scoring run from its restricted bundle, and public releases."""

import argparse
import json
import sys
from pathlib import Path

from croatian_stemmer import stem

from .candidates import prepare, read_candidates
from .evaluation import evaluate
from .schema import load


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidates = commands.add_parser("prepare", help="prepare suggestions from an existing CoNLL-U corpus")
    candidates.add_argument("corpus", type=Path)
    candidates.add_argument("--source-uri", required=True)
    candidates.add_argument("--license", required=True)
    candidates.add_argument("--pairs", type=int, help="default 10000, or 0 with --supplement")
    candidates.add_argument("--word-items", type=int, help="default 1000, or 0 with --supplement")
    candidates.add_argument("--seed", type=int, default=0)
    candidates.add_argument("--gold-reserve", type=int, default=0, metavar="N",
                            help="N items per gold-reserve stratum, built to become gold from corpus truth")
    candidates.add_argument("--min-freq", type=int, default=5, help="settled-form frequency for the gold reserve")
    candidates.add_argument("--reserve-secret", help="private seed of the gold reserve (at least 16 characters); "
                                                     "drawn at random when omitted and printed only in the receipt")
    candidates.add_argument("--supplement", type=Path, metavar="CANDIDATES",
                            help="an earlier candidates file of this corpus: output only new items, never "
                                 "reusing its occurrences")
    candidates.add_argument("--output", required=True, type=Path)
    text_ = commands.add_parser("from-text", help="prepare suggestions from raw text or a MediaWiki XML dump")
    text_.add_argument("inputs", nargs="+", help="text files, directories of .txt files, - for standard input, "
                                                 "or a MediaWiki dump (.xml or .xml.bz2)")
    text_.add_argument("--lexicon", required=True, type=Path, action="append",
                       help="a lemmatised CoNLL-U corpus giving each form's lemma and POS suggestion; repeatable")
    text_.add_argument("--source-uri", help="required for plain text; for a dump, default "
                                            "https://dumps.wikimedia.org/<dbname>/ (give the dated dump URL)")
    text_.add_argument("--license", help="required for plain text; for a dump, default CC BY-SA 4.0")
    text_.add_argument("--format", choices=("auto", "text", "mediawiki"), default="auto")
    text_.add_argument("--parser", choices=("builtin", "mwparserfromhell"), default="builtin",
                       help="wikitext parser; mwparserfromhell needs the `wiki` extra")
    text_.add_argument("--pairs", type=int, default=10000)
    text_.add_argument("--word-items", type=int, default=1000)
    text_.add_argument("--min-count", type=int, default=2, help="occurrences a form needs in the text")
    text_.add_argument("--max-pages", type=int, help="stop after this many dump articles (a trial run)")
    text_.add_argument("--seed", type=int, default=0)
    text_.add_argument("--output", required=True, type=Path)
    scoring = commands.add_parser("evaluate", help="score versioned human annotation TSVs")
    scoring.add_argument("labels", nargs="+", type=Path)
    scoring.add_argument("--min-annotators", type=int, default=1)
    gold = commands.add_parser("gold", help="build bootstrap gold where the corpus is unambiguous")
    gold.add_argument("corpus", type=Path)
    gold.add_argument("--candidates", required=True, type=Path, action="append",
                      help="the imported candidates file; repeat for its supplements")
    gold.add_argument("--min-freq", type=int, default=5)
    gold.add_argument("--per-kind", type=int, default=400)
    gold.add_argument("--seed", help="private seed (at least 16 characters); drawn at random when omitted and "
                                     "printed only in the receipt, which must stay private")
    gold.add_argument("--split", default="qualification=80", help="qualification=N: the first N per kind")
    gold.add_argument("--wrong-suggestion", type=int, default=30, metavar="N",
                      help="suggestion-wrong audit items per kind (from gold-reserve decoys)")
    gold.add_argument("--exclude", type=Path, help="file of item ids (one per line) never to use")
    gold.add_argument("--with", dest="existing", type=Path, action="append", default=[], metavar="GOLD",
                      help="gold already imported: its items are not used again and it counts in the coverage")
    gold.add_argument("--params", type=Path, help="scoring parameters (JSON) to check readiness against")
    gold.add_argument("--live", type=Path, help="the site's active pools: JSON of /api/admin/overview or "
                                               "/api/admin/gold")
    gold.add_argument("--allow-short", action="store_true", help="exit 0 even when a pool falls short")
    gold.add_argument("--output", required=True, type=Path)
    gold_check = commands.add_parser("gold-check", help="check gold files against their candidates and readiness")
    gold_check.add_argument("gold", nargs="+", type=Path, help="gold files, in import order")
    gold_check.add_argument("--candidates", required=True, type=Path, action="append")
    gold_check.add_argument("--params", type=Path, help="scoring parameters (JSON) to check readiness against")
    gold_check.add_argument("--live", type=Path, help="the site's active pools: JSON of /api/admin/overview or "
                                                     "/api/admin/gold")
    replay_ = commands.add_parser("score", help="replay a scoring run from its restricted bundle")
    replay_.add_argument("--bundle", required=True, type=Path, help="the run's bundle JSON (or a directory holding bundle.json)")
    replay_.add_argument("--output", required=True, type=Path, help="where to write the recomputed outputs (JSON)")
    release_ = commands.add_parser("release", help="build a public release from a pinned run's resolved.jsonl")
    release_.add_argument("run_export", type=Path)
    release_.add_argument("--output", required=True, type=Path)
    check_ = commands.add_parser("release-check", help="fail unless a release directory holds only aggregate labels")
    check_.add_argument("directory", type=Path)
    check_.add_argument("--run-export", required=True, type=Path)
    check_.add_argument("--annotators", type=Path, help="the curator's annotators/export.jsonl, to check ids too")
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            supplement = read_candidates(args.supplement) if args.supplement else ()
            default_pairs, default_words = (0, 0) if args.supplement else (10000, 1000)
            records, receipt = prepare(args.corpus, source_uri=args.source_uri, license=args.license,
                                       pair_count=default_pairs if args.pairs is None else args.pairs,
                                       word_count=default_words if args.word_items is None else args.word_items,
                                       seed=args.seed, gold_reserve_size=args.gold_reserve, min_freq=args.min_freq,
                                       supplement=supplement, reserve_secret=args.reserve_secret)
            # Never overwrite either the caller's source or an existing export.
            with args.output.open("x", encoding="utf-8") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            json.dump(receipt, sys.stdout, ensure_ascii=False)
        elif args.command == "from-text":
            from .text import from_text
            wikipedia = {"auto": None, "text": False, "mediawiki": True}[args.format]
            # Open the output first: never overwrite, and fail before a long run.
            with args.output.open("x", encoding="utf-8") as handle:
                try:
                    records, receipt = from_text(args.inputs, lexicon_paths=args.lexicon, source_uri=args.source_uri,
                                                 license=args.license, pair_count=args.pairs,
                                                 word_count=args.word_items, seed=args.seed,
                                                 min_count=args.min_count, wikipedia=wikipedia, parser=args.parser,
                                                 max_pages=args.max_pages)
                except BaseException:
                    handle.close()
                    args.output.unlink()
                    raise
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            json.dump(receipt, sys.stdout, ensure_ascii=False)
        elif args.command == "gold":
            from .gold import build, coverage_table, live_pools, read_gold
            name, _, value = args.split.partition("=")
            if name != "qualification" or not value.isdigit():
                raise ValueError("--split must be qualification=N")
            exclude = args.exclude.read_text(encoding="utf-8").split() if args.exclude else ()
            existing = [row for path in args.existing for row in read_gold(path)]
            params = json.loads(args.params.read_text(encoding="utf-8")) if args.params else None
            live = live_pools(json.loads(args.live.read_text(encoding="utf-8"))) if args.live else None
            rows, receipt = build(args.corpus, args.candidates, min_freq=args.min_freq, per_kind=args.per_kind,
                                  seed=args.seed, qualification=int(value), wrong=args.wrong_suggestion,
                                  exclude=exclude, existing=existing, params=params, live=live)
            with args.output.open("x", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            json.dump(receipt, sys.stdout, ensure_ascii=False)
            print()
            print(coverage_table(receipt["coverage"]), file=sys.stderr)
            if not receipt["coverage"]["ok"] and not args.allow_short:
                sys.exit(3)
            return
        elif args.command == "gold-check":
            from .gold import check, coverage_table, live_pools
            params = json.loads(args.params.read_text(encoding="utf-8")) if args.params else None
            live = live_pools(json.loads(args.live.read_text(encoding="utf-8"))) if args.live else None
            report = check(args.gold, args.candidates, params, live=live)
            json.dump(report, sys.stdout, ensure_ascii=False)
            print()
            print(coverage_table(report), file=sys.stderr)
            if not report["ok"]:
                sys.exit(3)
            return
        elif args.command == "release":
            from .release import build as build_release
            json.dump(build_release(args.run_export, args.output), sys.stdout, ensure_ascii=False)
        elif args.command == "release-check":
            from .release import check
            json.dump(check(args.directory, args.run_export, args.annotators), sys.stdout, ensure_ascii=False)
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

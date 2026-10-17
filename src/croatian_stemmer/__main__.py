"""CLI interface for the Croatian stemmer."""

import argparse
import sys

from .stemmer import stem, stem_text


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Croatian stemmer (Ljubešić-Pandžić algorithm)"
    )
    parser.add_argument(
        "words",
        nargs="*",
        help="Words to stem. If omitted, reads from stdin (one word per line).",
    )
    parser.add_argument(
        "-t", "--text",
        action="store_true",
        help="Treat input as free text (tokenize, skip stop words).",
    )
    args = parser.parse_args()

    if args.words:
        if args.text:
            print(" ".join(stem_text(" ".join(args.words))))
        else:
            for word in args.words:
                print(f"{word}\t{stem(word)}")
    else:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            if args.text:
                print(" ".join(stem_text(line)))
            else:
                print(f"{line}\t{stem(line)}")


if __name__ == "__main__":
    main()

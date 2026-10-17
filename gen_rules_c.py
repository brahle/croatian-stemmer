"""Generate C source data from Python stemmer rules.

Produces pg/croatian_stemmer_rules.h with all rule data embedded as C arrays.

Pattern handling
----------------
The Python rules use a small regex grammar for the stem pattern:
    pattern := '.+' | '.+?' | head atom+
    head    := '.+' | '.*' | '.*' class '.*' | class '+'
    atom    := literal-char | class | '(' alt ('|' alt)* ')'
    class   := '[' chars ']' | '[^' chars ']'
    alt     := atom*           (i.e. an alternation arm is itself a sequence)

The atoms after the head form the stem ending. Alternations are expanded as
a Cartesian product into a list of endings; character classes stay in the
endings as one-codepoint `[...]`/`[^...]` atoms, which the C matcher tests
like the regex does (a negated class matches any other codepoint, Croatian
letter or not).

The head is the part of the stem before the ending:
    .+          any codepoints, at least one            (HEAD_ANY, min_extra 1)
    .*          any codepoints, possibly none           (HEAD_ANY, min_extra 0)
    .*[cls].*   at least one codepoint in the class     (HEAD_SOME)
    [cls]+      one or more codepoints, all in the class (HEAD_ALL)
Rules with a lazy `.+?` stem are flagged: the stemmer treats them as
catch-alls.
"""

import re
import sys
from itertools import product

sys.path.insert(0, "src")

from croatian_stemmer.rules import (
    STOP_WORDS,
    TRANSFORMATIONS,
    _RULES,
)


def c_string(s: str) -> str:
    """Escape a string for C source."""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


# ---------------------------------------------------------------------------
#  Stem-pattern expansion
# ---------------------------------------------------------------------------

def _split_alternation(body: str) -> list[str]:
    """Split a top-level alternation at '|' (respecting nested parens)."""
    arms: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(body):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            arms.append(body[start:i])
            start = i + 1
    arms.append(body[start:])
    return arms


def _read_atom(pat: str, i: int) -> tuple[list[str], int]:
    """Parse one atom at pat[i] and return (options, next_i).

    `options` is the set of ending strings this atom may produce; a
    character class is kept whole as one `[...]` atom.
    """
    c = pat[i]

    if c == "[":
        end = pat.index("]", i)
        return [_check_class(pat[i:end + 1], pat)], end + 1

    if c == "(":
        depth = 1
        j = i + 1
        while j < len(pat) and depth > 0:
            if pat[j] == "(":
                depth += 1
            elif pat[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        if depth != 0:
            raise ValueError(f"unbalanced paren in {pat!r}")
        body = pat[i + 1:j]
        options: list[str] = []
        for arm in _split_alternation(body):
            options.extend(_expand_sequence(arm))
        return options, j + 1

    return [c], i + 1


def _check_class(cls: str, pat: str) -> str:
    """Validate a `[...]`/`[^...]` class: plain letters only, no ranges."""
    body = cls[1:-1]
    if body.startswith("^"):
        body = body[1:]
    if not body or any(ch in "-^[]\\" for ch in body):
        raise ValueError(f"unsupported char class {cls!r} in {pat!r}")
    return cls


def _expand_sequence(seq: str) -> list[str]:
    """Expand a sequence of atoms into the list of literals it produces."""
    i = 0
    per_atom: list[list[str]] = []
    while i < len(seq):
        options, i = _read_atom(seq, i)
        per_atom.append(options)
    if not per_atom:
        return [""]
    return ["".join(combo) for combo in product(*per_atom)]


HEAD_ANY, HEAD_ALL, HEAD_SOME = 0, 1, 2


class StemPattern:
    """A parsed stem pattern: its kind, endings and head constraint."""

    def __init__(self, kind: str, endings: list[str], min_extra: int,
                 head_mode: int = HEAD_ANY, head_class: str | None = None):
        self.kind = kind            # "any" | "any_nongreedy" | "ends_with"
        self.endings = endings
        self.min_extra = min_extra  # codepoints required before the ending
        self.head_mode = head_mode
        self.head_class = head_class


def expand_stem_pattern(pattern: str) -> StemPattern:
    """Parse a rule's stem pattern (see the module docstring)."""
    if pattern == ".+":
        return StemPattern("any", [], 1)
    if pattern == ".+?":
        return StemPattern("any_nongreedy", [], 1)

    head_mode, head_class = HEAD_ANY, None
    if m := re.match(r"\.\*(\[[^\]]+\])\.\*", pattern):
        head_mode, head_class, min_extra = HEAD_SOME, m.group(1), 1
    elif m := re.match(r"(\[[^\]]+\])\+", pattern):
        head_mode, head_class, min_extra = HEAD_ALL, m.group(1), 1
    elif m := re.match(r"\.\+", pattern):
        min_extra = 1
    elif m := re.match(r"\.\*", pattern):
        min_extra = 0
    else:
        raise ValueError(f"unsupported pattern {pattern!r}")
    if head_class is not None:
        _check_class(head_class, pattern)

    body = pattern[m.end():]
    if not body or any(ch in body for ch in "?*+.{}"):
        raise ValueError(f"unsupported quantifier in {pattern!r}")

    endings = sorted(set(_expand_sequence(body)))
    return StemPattern("ends_with", endings, min_extra, head_mode, head_class)


# ---------------------------------------------------------------------------
#  Header emission
# ---------------------------------------------------------------------------

def main() -> None:
    lines: list[str] = []
    lines.append("/* AUTO-GENERATED by gen_rules_c.py — do not edit */")
    lines.append("#ifndef CROATIAN_STEMMER_RULES_H")
    lines.append("#define CROATIAN_STEMMER_RULES_H")
    lines.append("")
    lines.append("#include <stddef.h> /* for NULL */")
    lines.append("")

    # Sorted by UTF-8 bytes so the C side can binary-search with strcmp.
    sorted_forms = sorted(STOP_WORDS, key=lambda w: w.encode("utf-8"))
    lines.append(f"#define N_STOP_WORDS {len(sorted_forms)}")
    lines.append("static const char *const stop_words[] = {")
    for form in sorted_forms:
        lines.append(f"    {c_string(form)},")
    lines.append("};")
    lines.append("")

    sorted_transforms = sorted(TRANSFORMATIONS.items(), key=lambda x: -len(x[0]))
    lines.append(f"#define N_TRANSFORMS {len(sorted_transforms)}")
    lines.append("typedef struct { const char *from; int from_len; const char *to; } Transform;")
    lines.append("static const Transform transforms[] = {")
    for frm, to in sorted_transforms:
        lines.append(
            f"    {{{c_string(frm)}, {len(frm.encode('utf-8'))}, {c_string(to)}}},"
        )
    lines.append("};")
    lines.append("")

    lines.append(f"#define N_RULES {len(_RULES)}")
    lines.append("")
    lines.append("/*")
    lines.append(" * Stem endings are codepoint atoms: a literal letter or a one-codepoint")
    lines.append(" * class `[...]`/`[^...]`. The head (the stem before its ending) is")
    lines.append(" * HEAD_ANY: any codepoints, at least min_extra of them (`.+`, `.*`);")
    lines.append(" * HEAD_ALL: one or more, every one in head_class (`[cls]+`);")
    lines.append(" * HEAD_SOME: at least one codepoint in head_class (`.*[cls].*`).")
    lines.append(" */")
    lines.append("#define HEAD_ANY 0")
    lines.append("#define HEAD_ALL 1")
    lines.append("#define HEAD_SOME 2")
    lines.append("")

    for i, (stem_pat, suffix_str) in enumerate(_RULES):
        pat = expand_stem_pattern(stem_pat)
        ptype, endings = pat.kind, pat.endings

        if ptype in ("any", "any_nongreedy"):
            kind = ".+" if ptype == "any" else ".+?"
            lines.append(f"/* Rule {i}: {kind} */")
            lines.append(f"static const char *const rule_{i}_stem_ends[] = {{ NULL }};")
            lines.append(f"#define RULE_{i}_N_STEM_ENDS 0")
        else:
            lines.append(f"/* Rule {i}: {stem_pat} */")
            lines.append(f"static const char *const rule_{i}_stem_ends[] = {{")
            for e in endings:
                lines.append(f"    {c_string(e)},")
            lines.append("};")
            lines.append(f"#define RULE_{i}_N_STEM_ENDS {len(endings)}")

        # Suffixes: empty alternative kept; sort order matches Python regex
        # greediness for the stem pattern (`.+?` lazy = longest-first).
        suffixes = suffix_str.split("|")
        reverse = (ptype == "any_nongreedy")
        suffixes.sort(key=lambda s: len(s.encode("utf-8")), reverse=reverse)

        lines.append(f"static const char *const rule_{i}_suffixes[] = {{")
        for s in suffixes:
            lines.append(f"    {c_string(s)},")
        lines.append("};")
        lines.append(f"#define RULE_{i}_N_SUFFIXES {len(suffixes)}")
        lines.append(f"#define RULE_{i}_MIN_EXTRA {pat.min_extra}")
        lines.append(f"#define RULE_{i}_HEAD_MODE {('HEAD_ANY', 'HEAD_ALL', 'HEAD_SOME')[pat.head_mode]}")
        lines.append(f"#define RULE_{i}_HEAD_CLASS {c_string(pat.head_class) if pat.head_class else 'NULL'}")
        lines.append(f"#define RULE_{i}_LAZY {1 if ptype == 'any_nongreedy' else 0}")
        lines.append("")

    lines.append("typedef struct {")
    lines.append("    const char *const *stem_ends;")
    lines.append("    int n_stem_ends;  /* 0 = any stem */")
    lines.append("    const char *const *suffixes;")
    lines.append("    int n_suffixes;")
    lines.append("    int min_extra;    /* codepoints required before the stem ending */")
    lines.append("    int head_mode;    /* HEAD_ANY / HEAD_ALL / HEAD_SOME, see below */")
    lines.append("    const char *head_class; /* class the head is checked against */")
    lines.append("    int lazy;         /* 1 = non-greedy `.+?` catch-all rule */")
    lines.append("} StemRule;")
    lines.append("")
    lines.append("static const StemRule rules[N_RULES] = {")
    for i in range(len(_RULES)):
        lines.append(
            f"    {{ rule_{i}_stem_ends, RULE_{i}_N_STEM_ENDS, "
            f"rule_{i}_suffixes, RULE_{i}_N_SUFFIXES, "
            f"RULE_{i}_MIN_EXTRA, RULE_{i}_HEAD_MODE, RULE_{i}_HEAD_CLASS, "
            f"RULE_{i}_LAZY }},"
        )
    lines.append("};")
    lines.append("")
    lines.append("#endif /* CROATIAN_STEMMER_RULES_H */")

    with open("pg/croatian_stemmer_rules.h", "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    total_endings = sum(
        len(expand_stem_pattern(p).endings) for p, _ in _RULES
    )
    print(
        f"Generated pg/croatian_stemmer_rules.h "
        f"({len(_RULES)} rules, {total_endings} stem endings, "
        f"{len(sorted_forms)} stop words, "
        f"{len(sorted_transforms)} transforms)"
    )


if __name__ == "__main__":
    main()

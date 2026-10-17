"""
Croatian stemmer based on the Ljubešić-Pandžić algorithm.

Reference: "Retrieving Information in Croatian: Building a Simple and Efficient
Rule-Based Stemmer" — Ljubešić, Boras & Kubelka (2007).
"""

import re

from .rules import LEXICON, STOP_WORDS, TRANSFORMATIONS, WORD_PATTERNS

_SYLLABIC_R = re.compile(r"(^|[^aeiou])r($|[^aeiou])")
_VOWEL = re.compile(r"[aeiouR]")
_REGULAR_COMPARATIVE_CASE_ENDINGS = (
    "ijima", "ijega", "ijemu", "ijeg", "ijem", "ijim",
    "ijih", "ijoj", "iji", "ije", "ija", "iju",
)


def _mark_syllabic_r(word: str) -> str:
    """Mark syllabic R as uppercase (counts as vowel in Croatian)."""
    return _SYLLABIC_R.sub(r"\1R\2", word)


def _has_vowel(word: str) -> bool:
    """Check if word contains a vowel (including syllabic R)."""
    return bool(_VOWEL.search(_mark_syllabic_r(word)))


def _normalize_regular_comparative_case(word: str) -> str | None:
    """Collapse regular -ij comparative case forms back to the base stem."""
    for ending in _REGULAR_COMPARATIVE_CASE_ENDINGS:
        if word.endswith(ending):
            candidate = word[: -len(ending)]
            if len(candidate) > 1 and _has_vowel(candidate):
                return candidate
            break
    return None


def _normalize_terminal_i_case(word: str, stemmed: str) -> str:
    """Unify adjective/plural -ih forms that still retain a final stem i."""
    if word.endswith("ih") and stemmed.endswith("i") and len(stemmed) > 2:
        candidate = stemmed[:-1]
        if len(candidate) > 1 and _has_vowel(candidate):
            return candidate
    return stemmed


def _apply_transformations(word: str) -> str:
    """Apply morphophonological transformations to normalize consonant alternations."""
    for suffix, replacement in TRANSFORMATIONS.items():
        if word.endswith(suffix):
            return word[: len(word) - len(suffix)] + replacement
    return word


def _strip_suffixes(word: str) -> str:
    """Apply suffix stripping rules to a word."""
    for pattern in WORD_PATTERNS:
        match = pattern.match(word)
        if match and len(match.group(1)) > 1 and _has_vowel(match.group(1)):
            return match.group(1)
    return word


def _stem_word(word: str) -> str:
    """Apply transformations and suffix stripping to a single word."""
    transformed = _apply_transformations(word)
    stemmed = _strip_suffixes(transformed)

    # Fleeting-a removal: Croatian nominative masculine forms insert an "a"
    # between consonant clusters (e.g., važan/važna, slobodan/slobodna).
    # Remove it to unify with oblique forms that lack the fleeting vowel.
    if stemmed.endswith("an") and len(stemmed) > 3:
        before_a = stemmed[-3]
        if before_a not in "aeiou":
            candidate = stemmed[:-2] + "n"
            if _has_vowel(candidate) and len(candidate) > 1:
                stemmed = candidate

    # Plural -ov-/-ev- extension: Croatian masculine nouns add -ov- (after
    # hard consonants) or -ev- (after soft) before plural endings.
    # Strip to unify with singular: planov→plan, ratov→rat, kraljev→kralj.
    if len(stemmed) > 3:
        for ext in ("ov", "ev"):
            if stemmed.endswith(ext):
                candidate = stemmed[:-2]
                if _has_vowel(candidate) and len(candidate) > 2:
                    stemmed = candidate
                break

    # Post-processing: if the stem ends with comparative "-ij",
    # try stripping it to unify comparative and base forms.
    # e.g., "starij" → "star", "novij" → "nov"
    if stemmed.endswith("ij") and len(stemmed) > 3:
        shorter = stemmed[:-2]
        if _has_vowel(shorter):
            return shorter

    # Reverse consonant alternations in stems to unify comparative/derived
    # forms with their base: duž→dug, jač→jak, mlađ→mlad, viš→vis,
    # skuplj→skup, dublj→dub (jotation), šir→širok (not handled here)
    # Jotation patterns (multi-char) — allowed up to 7 chars
    _JOTATION = {"plj": "p", "blj": "b", "vlj": "v", "mlj": "m",
                 "šć": "st", "žd": "zd"}
    if len(stemmed) <= 7:
        for pal, base in _JOTATION.items():
            if stemmed.endswith(pal):
                candidate = stemmed[: -len(pal)] + base
                if _has_vowel(candidate) and len(candidate) > 1:
                    return candidate
                break

    # Simple palatalization — only very short stems (≤3) to avoid noise like
    # prič→prik for 4-5 char noun stems that legitimately end in a palatal.
    _DEPALATALIZE = {"ž": "g", "č": "k", "đ": "d", "š": "s"}
    if len(stemmed) <= 3:
        for pal, base in _DEPALATALIZE.items():
            if stemmed.endswith(pal):
                candidate = stemmed[: -len(pal)] + base
                if _has_vowel(candidate) and len(candidate) > 1:
                    return candidate
                break

    return stemmed


def stem(word: str) -> str:
    """Stem a single Croatian word.

    Forms listed in the lexicon (including stop words) return their lemma's
    canonical stem; otherwise the rules apply. Returns the lowercased word
    if no rule matches.
    """
    lower = word.lower()

    if lower in LEXICON:
        return LEXICON[lower]

    # Strip superlative prefix "naj" and stem the remainder,
    # so "najveći" and "veći" converge to the same stem.
    if lower.startswith("naj") and len(lower) > 4:
        without_prefix = lower[3:]
        if without_prefix in LEXICON:
            return LEXICON[without_prefix]
        regular_comparative = _normalize_regular_comparative_case(without_prefix)
        if regular_comparative is not None:
            return regular_comparative

        stemmed = _stem_word(without_prefix)
        if stemmed != without_prefix:
            return _normalize_terminal_i_case(lower, stemmed)
        # Inner word unchanged (too short for rules) — stem the full word
        # and strip naj- from the result to unify superlative forms.
        # e.g., najnovijeg → _stem_word → najnov → strip → nov
        result = _stem_word(lower)
        if result.startswith("naj") and len(result) > 4:
            stripped = result[3:]
            if _has_vowel(stripped) and len(stripped) > 1:
                return _normalize_terminal_i_case(lower, stripped)
        return _normalize_terminal_i_case(lower, result)

    return _normalize_terminal_i_case(lower, _stem_word(lower))


def stem_text(text: str) -> list[str]:
    """Stem all words in a text, returning a list of stems.

    Stop words (auxiliary and modal forms such as "sam", "će", "mogu") are
    excluded from the output; every other token is stemmed.
    """
    tokens = re.findall(r"\w+", text.lower())
    result = []
    for token in tokens:
        if token in STOP_WORDS:
            continue
        result.append(stem(token))
    return result

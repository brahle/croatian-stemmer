"""
Croatian stemmer based on the Ljubešić-Pandžić algorithm.

Reference: "Retrieving Information in Croatian: Building a Simple and Efficient
Rule-Based Stemmer" — Ljubešić, Boras & Kubelka (2007).
"""

import re
from typing import NamedTuple

from .rules import STOP_WORDS, TRANSFORMATIONS, WORD_PATTERNS

# Syllabic r stands between consonants (trg, krv, prst, crkva) or starts
# the word before a consonant (rđa). A stem-final r after a consonant
# (br-oj, str-oj, vjetr) is not syllabic: it closes the syllable before.
_SYLLABIC_R = re.compile(r"(^|[^aeiou])r(?=[^aeiou])")
_VOWEL = re.compile(r"[aeiouR]")
_DEVOICE = {"z": "s", "ž": "š", "b": "p", "g": "k"}
_NO_COMPARATIVE_IJ = frozenset("cčćđfghjkszšž")
_REGULAR_COMPARATIVE_CASE_ENDINGS = (
    "ijima", "ijega", "ijemu", "ijeg", "ijem", "ijim",
    "ijih", "ijoj", "iji", "ije", "ija", "iju",
)


def _mark_syllabic_r(word: str) -> str:
    """Mark syllabic R as uppercase (counts as vowel in Croatian)."""
    return _SYLLABIC_R.sub(r"\1R", word)


def _syllables(word: str) -> int:
    """Count syllable nuclei: vowel groups plus a syllabic r between
    consonants (trg, prst). A stem-final r after a consonant (vjetr, žanr)
    is not counted: it closes the syllable before it. The long jat reflex
    -ije- is one syllable (dijel, snijeg)."""
    return len(re.findall(r"ije|[aeiou]+|(?:^|(?<=[^aeiou]))r(?=[^aeiou])", word))


def _has_vowel(word: str) -> bool:
    """Check if word contains a vowel (including syllabic R)."""
    return bool(_VOWEL.search(_mark_syllabic_r(word)))


def _has_vowel_before(word: str, cut: int) -> bool:
    """Check word[:-cut] for a vowel, judging a syllabic r by the whole
    word (cvr-čak, škr-tac, smr-zla: the r is syllabic before the cut)."""
    return bool(_VOWEL.search(_mark_syllabic_r(word)[:-cut]))


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


# Verbal endings that follow the thematic vowel (rad-i-la, gled-a-ti):
# l-participle, infinitive, present person endings, imperative, aorist and
# imperfect, past and present gerund. Case endings (-lu, -lom, -ama, ...) are absent.
_THEMATIC_ENDINGS = frozenset({
    "l", "la", "li", "lo", "le", "o", "lu", "lom", "lima", "lama",
    "lih", "lim", "log", "loga", "loj", "lome", "lomu",
    "ti", "t",
    "m", "š", "mo", "te", "ju",
    "j", "jmo", "jte",
    "h", "še", "smo", "ste", "hu",
    "vši", "jući",
    # -j- present of vowel stems (dobi-je, razumi-jem, pozna-je)
    "je", "jem", "ješ", "jemo", "jete",
})


def _is_root(stem: str) -> bool:
    """A verb root before a derivational suffix: three letters and a vowel."""
    return len(stem) > 2 and _has_vowel(stem)


class _Stripped(NamedTuple):
    """Result of suffix stripping: the stem, the ending the matched rule
    removed (before any thematic-vowel adjustment), and whether that rule
    was verbal, i.e. a verb rule removed an infinitive, l-participle or
    other thematic ending (radi-ti, gleda-la, traži-ti)."""

    stem: str
    ending: str
    verbal: bool


def _strip_suffixes(word: str) -> _Stripped:
    """Apply suffix stripping rules to a word."""
    for pattern in WORD_PATTERNS:
        match = pattern.match(word)
        if match and len(match.group(1)) > 1 and _has_vowel(match.group(1)):
            stem = match.group(1)
            ending = word[len(stem):]
            # Thematic vowel: verb rules keep it on the stem (radi-la,
            # gleda-ti) while the bare forms lose it to the catch-all
            # (radi -> rad, gleda -> gled). Drop it so they agree.
            catch_all = pattern.pattern.startswith("^(.+?)")
            verbal = not catch_all and ending in _THEMATIC_ENDINGS
            # The short infinitive -t (gleda-t, radi-t) needs a root
            # syllable before the thematic vowel: in brat and vrat the r
            # before -at is not syllabic, so -t is not an ending.
            if verbal and ending == "t" and not _has_vowel(stem[:-1]):
                continue
            # -ovati/-ivati verbs: the infinitive stem -ova-/-iva- alternates
            # with the present -uj- (djelova-ti/djeluj-e, pokaziva-ti/
            # pokazuj-e). Map all three to one -iv stem. The root before the
            # suffix needs three letters and a vowel of its own: in struj-a
            # the -uj- is part of the root.
            if verbal and stem.endswith(("ova", "iva")) and _is_root(stem[:-3]):
                return _Stripped(stem[:-3] + "iv", ending, verbal)
            if stem.endswith("uj") and not catch_all and _is_root(stem[:-2]):
                return _Stripped(stem[:-2] + "iv", ending, verbal)
            if (stem[-1] in "ai" and len(stem) > 3 and verbal
                    and _has_vowel(stem[:-1])):
                return _Stripped(stem[:-1], ending, verbal)
            return _Stripped(stem, ending, verbal)
    return _Stripped(word, "", False)


# -je-/-ije- verbs (vidjeti, voljela, donijeli): the jat reflex is their
# thematic vowel, which the present and the -io participle drop (vidi,
# vidio, volio, donio). Strip it with the infinitive or l-participle ending.
# A stem shorter than three letters is left alone (cijela, bijeli, tijelo).
_PRESENT_ENDINGS = frozenset({"e", "em", "eš", "emo", "ete", "u", "i", "imo", "ite"})
_JE_VERB_ENDINGS = (
    "ijeti", "jeti",
    "ijela", "ijeli", "ijelo", "ijele", "jela", "jeli", "jelo", "jele",
)
# Verbal prefixes, longest first, used to find the root a -je- follows.
_VERB_PREFIXES = (
    "pred", "pod", "nad", "raz", "ras",
    "pre", "pri", "pro",
    "do", "iz", "na", "ne", "ob", "od", "po", "sa", "za",
    "o", "s", "u",
)


def _root_after_prefix(stem: str) -> str:
    """Strip one leading verbal prefix, keeping at least one letter."""
    for prefix in _VERB_PREFIXES:
        if stem.startswith(prefix) and len(stem) > len(prefix):
            return stem[len(prefix):]
    return stem


def _strip_je_theme(word: str) -> str | None:
    """Strip a -je-/-ije- thematic vowel with its verbal ending, if any.

    Long -ije- is thematic only in -nijeti/-rijeti verbs (donijeti,
    umrijeti), and only -nijeti keeps it in the l-participle (donijela, but
    umro/umrla): elsewhere -ije- is a root (podijeliti, odijelo, strijela,
    primijetiti). Short -je- needs a root of its own before it: after
    a prefix plus a single consonant it is part of the root (sav-jet,
    za-vjet, po-djela, do-djela, raz-djela, po-sjet), and a candidate in s
    is the sjet- root (posjetiti, podsjetiti, prisjetiti).
    """
    for ending in _JE_VERB_ENDINGS:
        if word.endswith(ending):
            candidate = word[: -len(ending)]
            if len(candidate) <= 2 or not _has_vowel(candidate):
                return None
            if ending.startswith("ij"):
                allowed = "nr" if ending == "ijeti" else "n"
                if candidate[-1] not in allowed:
                    return None
            elif (candidate[-1] == "s"
                    or len(_root_after_prefix(candidate)) == 1):
                return None
            return candidate
    return None


_JOTATED_PARTICIPLE = (
    ("šćen", "st"), ("šten", "st"), ("žđen", "zd"),
    ("plj" + "en", "p"), ("blj" + "en", "b"), ("vlj" + "en", "v"),
    ("mlj" + "en", "m"),
    # sl jotates to šlj (misl-iti -> mišljen, zamišljen, osmišljen).
    ("šljen", "sl"), ("ljen", "l"), ("njen", "n"),
    ("đen", "d"), ("ćen", "t"),
    # i-verbs whose root already ends in a palatal (završ-iti, uključ-iti,
    # ulož-iti) keep it in the participle (završen, uključen, uložen).
    ("čen", "č"), ("šen", "š"), ("žen", "ž"),
    # e-verbs in -sti keep the root dental after -e- (dovesti -> doved-en,
    # donijeti -> dones-en, plesti -> plet-en).
    ("eden", "ed"), ("esen", "es"), ("ezen", "ez"), ("eten", "et"),
    # i-verbs with a root in vowel + r do not jotate (otvor-iti -> otvoren,
    # ostvar-iti -> ostvaren, uvjer-iti -> uvjeren, proširiti -> proširen).
    ("oren", "or"), ("aren", "ar"), ("eren", "er"), ("iren", "ir"),
    # -oj- roots keep j (spoj-iti -> spojen); vowel roots insert -v-
    # (otkri-ti -> otkriven, obu-ti -> obuven), which goes with -en.
    ("ojen", "oj"), ("iven", ""), ("uven", ""),
    # bi-ti/vi-ti compounds insert -j- instead (ubijen, razvijen).
    ("bijen", "b"), ("vijen", "v"),
)


def _undo_participle_jotation(stem: str) -> str | None:
    """Map a jotated -en participle stem back to the verb root."""
    for ending, root in _JOTATED_PARTICIPLE:
        if stem.endswith(ending):
            candidate = stem[: -len(ending)] + root
            if len(candidate) > 2 and _has_vowel(candidate):
                return candidate
            return None
    return None


def _stem_word(word: str) -> str:
    """Apply transformations and suffix stripping to a single word."""
    transformed = _apply_transformations(word)
    je_stem = _strip_je_theme(transformed)
    if je_stem is not None:
        stripped = _Stripped(je_stem, transformed[len(je_stem):], True)
    else:
        stripped = _strip_suffixes(transformed)
    stemmed = stripped.stem

    # -ići compounds (doći, proći, naći, poći, izaći): the l-participle and
    # the adjective prošli build on -šl-, the present on -đ- (došla/dođe,
    # prošli/prođe, našli/nađem, pošla/pođu). When a case or gender ending
    # follows the l, map vowel + šl to vowel + đ, so these forms meet the
    # present and keep apart from dodati/prodati/nada.
    if (stripped.ending and len(stemmed) > 2 and stemmed.endswith("šl")
            and stemmed[-3] in "aeiou"):
        stemmed = stemmed[:-2] + "đ"

    # Comparative -ij-: strip it first, so the positive stem then goes
    # through the same participle and fleeting-a steps as the positive
    # (kompliciranij -> kompliciran -> komplicir, složenij -> slož).
    # e.g., "starij" → "star", "novij" → "nov". Velar, sibilant and palatal
    # stems never take -ij- (they jotate: jak -> jači, brz -> brži), so -ij
    # after them belongs to a noun (akcija, strategija, misija, vizija).
    if (stemmed.endswith("ij") and len(stemmed) > 3
            and stemmed[-3] not in _NO_COMPARATIVE_IJ
            and _has_vowel(stemmed[:-2])):
        stemmed = stemmed[:-2]


    # Fleeting a in -ak: postupak/postupka/postupaka, odlazak/odlaska. Drop
    # the a and devoice the consonant before k as the oblique forms do.
    # Stems with a stable a (korak/koraka) get the same -Ck stem in every
    # form, so nothing splits. -dak/-tak are left to the -dak/-tk steps.
    if (len(stemmed) > 4 and stemmed.endswith("ak")
            and stemmed[-3] not in "aeioudt"):
        candidate = stemmed[:-2] + "k"
        candidate = candidate[:-2] + _DEVOICE.get(candidate[-2], candidate[-2]) + "k"
        if _has_vowel_before(candidate, 2):
            stemmed = candidate

    # Fleeting a in -ac nouns (kupac/kupca/kupci, stranac, borac): the
    # nominative and genitive plural keep the a that the other forms lose.
    # Generalizes the v0.1 -nac/-mac/-vac/-rac/... transformations.
    if (len(stemmed) > 4 and stemmed.endswith("ac")
            and stemmed[-3] not in "aeiou" and _has_vowel_before(stemmed, 3)):
        stemmed = stemmed[:-2] + "c"

    # -dak nouns alternate like -tak ones: the oblique forms devoice the d
    # before k (pogodak/pogotka, napredak/napretka, dohodak/dohotka) and the
    # plural drops it (pogoci). Read vowel + dak as vowel + tk. The short
    # -dak stems the -aci plural of -datak nouns leaves (podak from podaci,
    # zadak, dodak) already match the -tk step's output and are untouched.
    if (len(stemmed) > 5 and stemmed.endswith("dak")
            and stemmed[-4] in "aeiou"):
        stemmed = stemmed[:-3] + "tk"

    # -tak nouns lose the t before the plural -ci (podatak/podatka/podaci,
    # trenutak/trenuci, gubitak/gubici); a vowel + tk stem drops the t to
    # meet the plural.
    if (len(stemmed) > 5 and stemmed.endswith("tk")
            and stemmed[-3] in "aeiou"):
        stemmed = stemmed[:-2] + "k"

    # Comparatives in -š- after k/p (lak-š-i, mek-š-i, ljep-š-i).
    if stemmed.endswith(("kš", "pš")) and len(stemmed) > 3:
        stemmed = stemmed[:-1]

    # Velar -ći verbs take -n- in the present (pomog-n-e, stig-n-u, dig-n-eš)
    # but not in the l-participle (pomogla, stigao). Drop it after g.
    if stemmed.endswith("gn") and len(stemmed) > 3:
        stemmed = stemmed[:-1]

    # Fleeting-a removal: Croatian nominative masculine forms insert an "a"
    # between consonant clusters (e.g., važan/važna, slobodan/slobodna).
    # Remove it to unify with oblique forms that lack the fleeting vowel.
    # Passive participles of i-verbs jotate the root before -en
    # (objav-iti -> objavlj-en, učin-iti -> učinj-en, vrat-iti -> vrać-en,
    # izgrad-iti -> izgrađ-en). Strip -en and undo the jotation. After a
    # non-palatal consonant -en is too often a noun or adjective (jesen,
    # leden, bazen) to strip.
    participle = _undo_participle_jotation(stemmed)
    if participle is not None:
        stemmed = participle

    # -stati verbs build the present on -stan- (posta-n-e, osta-n-u), which
    # the -an noun rule hands over as postan; drop -an to meet posta-la.
    # Only with a present-tense ending: bare koristan/bolestan are adjectives.
    if (stemmed.endswith("stan") and len(stemmed) > 4
            and transformed[len(stemmed):] in _PRESENT_ENDINGS
            and _has_vowel(stemmed[:-2])):
        stemmed = stemmed[:-2]
    # -irati verbs form their participle in -iran (organiziran, planiran);
    # its a is not fleeting (organizirana), so drop -an to meet organizir-ati.
    elif stemmed.endswith("iran") and len(stemmed) > 5:
        stemmed = stemmed[:-2]
    # a-verb participles keep their a (napisana, povezana, održana), while
    # fleeting-a adjectives lose it (jasna, obavezna). A -an stem left by an
    # ending after s/z, a palatal or h is therefore a participle (nouns with
    # a stable -an mostly have -lan/-ran/-van/-kan/-tan: plan, ekran, Ivan):
    # drop -an to meet napis-ati. The bare form stays with fleeting-a.
    # -ovati/-ivati participles (očekivana, imenovanog) join the -iv stem
    # that #89 gives these verbs.
    elif (stemmed.endswith(("ivan", "ovan")) and len(stemmed) > 6
            and transformed[len(stemmed):]):
        stemmed = stemmed[:-4] + "iv"
    elif (stemmed.endswith(("san", "zan", "čan", "ćan", "žan", "šan", "han"))
            and len(stemmed) > 5
            and transformed[len(stemmed):]):
        stemmed = stemmed[:-2]
    elif stemmed.endswith("an") and len(stemmed) > 3:
        before_a = stemmed[-3]
        if before_a not in "aeiou":
            candidate = stemmed[:-2] + "n"
            # -stan adjectives also lose the t in the oblique forms
            # (koristan/korisna, svjestan/svjesna, izvrstan/izvrsna).
            if candidate.endswith("stn"):
                candidate = candidate[:-2] + "n"
            if _has_vowel(candidate) and len(candidate) > 1:
                stemmed = candidate

    # Plural -ov-/-ev- extension: monosyllabic masculine nouns add -ov-
    # (after hard consonants) or -ev- (after soft) before plural endings.
    # Strip to unify with singular: planov→plan, ratov→rat, kraljev→kralj.
    # Longer stems keep it: there -ov/-ev is mostly the possessive adjective
    # suffix (premijerov, prijateljev), a separate lemma.
    if len(stemmed) > 3:
        for ext in ("ov", "ev"):
            if stemmed.endswith(ext):
                candidate = stemmed[:-2]
                if _syllables(candidate) == 1 and len(candidate) > 2:
                    stemmed = candidate
                break


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

    # No single-consonant depalatalization (ž -> g, č -> k, š -> s). A stem
    # ending in a palatal is read as the root's own: the ending cannot tell
    # a comparative or e-verb present (jači, piše) from an i-/a-verb or noun
    # with a palatal root (traži, priča, naš, riječ), and undoing it merged
    # tražiti with trag, pokušati with pokus and naš with nas.

    return stemmed


def _stem_raw(word: str) -> str:
    """Stem a single word before the final fleeting-a normalization."""
    lower = word.lower()

    if lower in STOP_WORDS:
        return lower

    # Strip superlative prefix "naj" and stem the remainder,
    # so "najveći" and "veći" converge to the same stem.
    if lower.startswith("naj") and len(lower) > 4:
        without_prefix = lower[3:]
        regular_comparative = _normalize_regular_comparative_case(without_prefix)
        if regular_comparative is not None:
            # Stem the positive like any other word (najsloženiji -> složen
            # -> slož, najkompliciraniji -> komplicir).
            return _stem_word(regular_comparative)

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


def _fleeting_ar(stemmed: str) -> str:
    """Fleeting a in -tar/-bar/-dar: metar/metra, dobar/dobra, Zadar/Zadra.

    The nominative keeps the a that the other forms lose. Applied to every
    stem, a stable-a word (kadar/kadra aside) gets the same -tr/-br/-dr
    stem in all its forms, so it does not split.
    """
    if (len(stemmed) > 4 and stemmed.endswith(("tar", "bar", "dar"))
            and _has_vowel_before(stemmed, 3)):
        return stemmed[:-2] + "r"
    # Fleeting -ao: posao/posla, topao/topla, misao/misli, okrugao/okrugla.
    # The masculine loses the l (pos-a-o -> pos), the other forms keep it
    # after a consonant (posl-a). Drop a stem-final l after a consonant so
    # both meet; a-verb participles (čeka-la) have a vowel before the l.
    if (len(stemmed) > 3 and stemmed[-1] == "l"
            and stemmed[-2] in "bcdfghkmnprstvzčćđšž"
            and _has_vowel_before(stemmed, 2)):
        return stemmed[:-1]
    return stemmed


def stem(word: str) -> str:
    """Stem a single Croatian word.

    Returns the lowercased word unchanged if it is a stop word or no rule
    matches.
    """
    lower = word.lower()
    if lower in STOP_WORDS:
        return lower
    return _fleeting_ar(_stem_raw(lower))


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

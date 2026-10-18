"""Prepare suggestions from caller-supplied corpora; never create human gold."""

import hashlib
import itertools
import json
import random
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple
from uuid import NAMESPACE_URL, uuid5

from croatian_stemmer import stem

from .schema import UPOS, digest, normalized

# Strata of items built only to become known-answer items (gold), from corpus truth.
# They are never served as ordinary work and never released (see docs/labeling.md).
RESERVE_PREFIX = "gold_reserve_"
RESERVE_STRATA = (RESERVE_PREFIX + "lemma", RESERVE_PREFIX + "lemma_decoy",
                  RESERVE_PREFIX + "pair_decoy_same", RESERVE_PREFIX + "pair_decoy_different")


# Content words only: names, foreign words and function words make poor known answers.
RESERVE_UPOS = frozenset(("NOUN", "VERB", "ADJ", "ADV"))
PREFIX_LETTERS = 4


def is_reserve(stratum: str) -> bool:
    return stratum.startswith(RESERVE_PREFIX)


@dataclass(frozen=True)
class Token:
    word: str
    lemma: str
    upos: str
    ref: str
    context: str


def tokens_from_conllu(path: Path) -> list[Token]:
    """One representative occurrence per form/lemma/POS, with source line.

    Lemmas are suggestions from the corpus, never human annotations imported
    into the new dataset. Missing lemmas and multiword/range tokens are skipped.
    """
    return index_conllu(path)[0]


class CorpusIndex(NamedTuple):
    tokens: list  # one representative occurrence per form/lemma/POS (tokens_from_conllu)
    freq: Counter  # freq[(form, lemma, upos)] over every occurrence
    lemmas_of: dict  # lemmas_of[(form, upos)]: every lemma the form has with the POS
    seen: dict  # seen[(form, lemma, upos)]: its first `keep` (at least one) occurrences, in file order


def index_conllu(path: Path, keep: int = 8) -> CorpusIndex:
    """One pass over the corpus: the representative tokens, the counts the gold rules read,
    and a few occurrences per form/lemma/POS (the gold reserve takes unused ones)."""
    seen, freq, lemmas_of = {}, Counter(), defaultdict(set)
    for token in occurrences(path):
        key = (token.word, token.lemma, token.upos)
        found = seen.setdefault(key, [])
        if len(found) < max(keep, 1):
            found.append(token)
        freq[key] += 1
        lemmas_of[(token.word, token.upos)].add(token.lemma)
    tokens = sorted((found[0] for found in seen.values()), key=lambda t: (t.upos, t.lemma, t.word))
    return CorpusIndex(tokens, freq, lemmas_of, seen)


def occurrences(path: Path):
    """Every eligible token occurrence, in file order (the column handling of
    tokens_from_conllu, which keeps the first occurrence of each form/lemma/POS)."""
    context = ""
    columns = {"ID": 0, "FORM": 1, "LEMMA": 2, "UPOS": 3}
    with path.open(encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, 1):
            if not line.strip():
                context = ""
                continue
            if line.startswith("# global.columns = "):
                names = line.split("=", 1)[1].split()
                if len(set(names)) != len(names) or not set(columns).issubset(names):
                    raise ValueError("CoNLL-U Plus header needs unique ID/FORM/LEMMA/UPOS columns")
                columns = {name: names.index(name) for name in columns}
            if line.startswith("# text = "):
                context = line[9:].strip()[:4000]
            if line.startswith("#"):
                continue
            fields = line.rstrip("\n\r").split("\t")
            if len(fields) <= max(columns.values()) or not fields[columns["ID"]].isdigit():
                continue
            form = normalized(fields[columns["FORM"]])
            lemma = normalized(fields[columns["LEMMA"]])
            upos = fields[columns["UPOS"]]
            if not form.isalpha() or not lemma.isalpha() or upos not in UPOS:
                continue
            if len(form) > 128 or len(lemma) > 128:
                continue
            yield Token(form, lemma, upos, f"line:{line_number}", context)


def settled_lemma(freq, lemmas_of, form, upos, min_freq):
    """The corpus truth for a form and POS, or None: the form has exactly one lemma for
    the POS and occurs with it at least min_freq times (the gold builder's rule, 4.3.1)."""
    lemmas = lemmas_of.get((form, upos), ())
    if len(lemmas) != 1:
        return None
    (lemma,) = lemmas
    return lemma if freq[(form, lemma, upos)] >= min_freq else None


def _plain(value):
    return "".join(c for c in unicodedata.normalize("NFD", value) if not unicodedata.combining(c))


def related(a: str, b: str) -> bool:
    """Lemmas a reader could take for variants of one word: equal, one a prefix of the
    other, or equal without diacritics. Never used as a `different` known answer or decoy."""
    return a.startswith(b) or b.startswith(a) or _plain(a) == _plain(b)


def reservoir(values, size, rng):
    if not size:
        return []
    result = []
    for index, value in enumerate(values):
        if index < size:
            result.append(value)
        elif size:
            choice = rng.randrange(index + 1)
            if choice < size:
                result[choice] = value
    return result


def algorithm_sha256() -> str:
    """Package source-code hashes travel with suggestions, never a fabricated human label."""
    package_root = Path(__file__).resolve().parents[1]
    algorithm = hashlib.sha256()
    for name in ("stemmer.py", "rules.py"):
        algorithm.update((package_root / name).read_bytes())
    return algorithm.hexdigest()


def _check_provenance(source_uri, license):
    if not source_uri.strip() or not license.strip():
        raise ValueError("source URI and license are required")
    if len(source_uri) > 2048 or len(license) > 512 or "\x00" in source_uri + license:
        raise ValueError("invalid source provenance")


class Records:
    """Candidate rows of one corpus in the versioned candidate schema (v1)."""

    def __init__(self, *, corpus_id, corpus_sha256, source_uri, license):
        self.base = {"candidate_schema_version": 1, "corpus_id": corpus_id, "corpus_sha256": corpus_sha256,
                     "source_uri": source_uri, "license": license}
        self.corpus_id = corpus_id
        self.algorithm = algorithm_sha256()

    def candidate(self, left, kind, *, right=None, stratum="word_suggestion", lemma=None, other_lemma=None):
        """lemma/other_lemma override the suggestions shown (gold-reserve decoys only); the
        identity then includes the stratum and both suggestions, so a decoy never shares an
        item id with an ordinary item on the same occurrences."""
        proposed_stem = stem(left.word) if kind == "stem" else ""
        proposed = left.lemma if lemma is None else lemma
        other_proposed = (right.lemma if right else "") if other_lemma is None else other_lemma
        parts = [kind, left.ref, right.ref if right else "", proposed_stem]
        if is_reserve(stratum):
            parts += [stratum, proposed, other_proposed]
        identity = json.dumps(parts, ensure_ascii=False)
        return {**self.base,
                "item_id": str(uuid5(NAMESPACE_URL, self.corpus_id + ":" + identity)),
                "kind": kind, "word": left.word, "other_word": right.word if right else "",
                "proposed_lemma": proposed, "other_proposed_lemma": other_proposed,
                "proposed_stem": proposed_stem, "upos": left.upos,
                "context": left.context, "other_context": right.context if right else "",
                "word_ref": left.ref, "other_word_ref": right.ref if right else "",
                "sampling_stratum": stratum, "algorithm_sha256": self.algorithm}


def sample(tokens, records: Records, *, pair_count, word_count, rng, prefix="", word_strata=None):
    """The stratified sample of prepare: same-lemma pairs, stem-collision and random
    different-lemma pairs, then word items (one lemma and one stem item per token).

    `prefix` is put before every stratum name (raw-text corpora use `text_`, so their
    strata never share a class prior with a lemmatised corpus's). `word_strata`, if
    given, maps a token to its word-item stratum instead of `word_suggestion` and must
    already hold `word_count` tokens chosen by the caller (raw text samples by
    frequency band)."""
    by_lemma, by_stem, by_pos = {}, {}, {}
    for token in tokens:
        by_lemma.setdefault((token.upos, token.lemma), []).append(token)
        by_stem.setdefault((token.upos, stem(token.word)), []).append(token)
        by_pos.setdefault(token.upos, []).append(token)

    pairs, seen = [], set()

    def add(left, right, stratum):
        if left.word == right.word:
            return False
        left, right = sorted((left, right), key=lambda t: (t.word, t.lemma, t.ref))
        key = left.ref, right.ref
        if key in seen:
            return False
        seen.add(key)
        pairs.append((left, right, prefix + stratum))
        return True

    same_budget = pair_count // 2
    same = itertools.chain.from_iterable(itertools.combinations(group, 2) for group in by_lemma.values())
    for left, right in reservoir(same, same_budget, rng):
        add(left, right, "corpus_same_lemma_suggestion")
    hard = ((a, b) for group in by_stem.values() for a, b in itertools.combinations(group, 2)
            if a.lemma != b.lemma and a.word != b.word)
    negative_budget = pair_count - len(pairs)
    for left, right in reservoir(hard, negative_budget // 2, rng):
        add(left, right, "stem_collision_different_lemma_suggestion")
    eligible_pos = [group for group in by_pos.values() if len({t.lemma for t in group}) >= 2]
    for _ in range(max(pair_count * 40, 100)):
        if len(pairs) >= pair_count or not eligible_pos:
            break
        group = rng.choice(eligible_pos)
        left, right = rng.sample(group, 2)
        if left.lemma != right.lemma:
            add(left, right, "random_different_lemma_suggestion")

    out = [records.candidate(left, "pair", right=right, stratum=stratum) for left, right, stratum in pairs]
    if word_strata is None:
        chosen = [(token, prefix + "word_suggestion") for token in reservoir(tokens, min(word_count, len(tokens)), rng)]
    else:
        chosen = word_strata
    for token, stratum in chosen:
        out.append(records.candidate(token, "lemma", stratum=stratum))
        out.append(records.candidate(token, "stem", stratum=stratum))
    return out, len(pairs)


def gold_reserve(index: CorpusIndex, records: Records, *, size, min_freq, rng, used_refs=()):
    """Items built to become gold from corpus truth, `size` per reserve stratum.

    Only content words (RESERVE_UPOS) the corpus settles (settled_lemma) take part. No
    occurrence is used twice or taken from `used_refs` (the ordinary sample, or an earlier
    candidates file of the same corpus): a form already used appears again only in another
    sentence. Agreeing lemma items show the corpus lemma. Decoys show a suggestion
    the corpus contradicts, so that the copy flag and the promotion floor have known
    answers that differ from the suggestion:

    - lemma_decoy: the lemma of another settled word with the same stem and POS, else the
      form itself; the known answer is the corpus lemma (the correction);
    - pair_decoy_same: two forms whose settled lemmas differ (and are not variants), one
      shown with the other's lemma, so the suggestion says `same`; the answer is `different`.
      Forms the stemmer merges come first, then forms sharing their first four letters;
    - pair_decoy_different: two forms of one settled lemma, one shown with a decoy lemma,
      so the suggestion says `different`; the answer is `same`.
    """
    if not size:
        return [], {stratum: 0 for stratum in RESERVE_STRATA}
    used, taken = set(used_refs), set()

    def fresh(token):
        """An occurrence of the token's form/lemma/POS that no item uses yet, or None."""
        return next((t for t in index.seen[(token.word, token.lemma, token.upos)]
                     if t.ref not in used and t.ref not in taken), None)

    settled = [t for t in index.tokens if t.upos in RESERVE_UPOS and fresh(t) is not None
               and settled_lemma(index.freq, index.lemmas_of, t.word, t.upos, min_freq) == t.lemma]
    by_stem, by_lemma = defaultdict(list), defaultdict(list)
    for token in settled:
        by_stem[(token.upos, stem(token.word))].append(token)
        by_lemma[(token.upos, token.lemma)].append(token)

    def decoy(token):
        near = sorted({u.lemma for u in by_stem[(token.upos, stem(token.word))]
                       if not related(u.lemma, token.lemma)})
        if near:
            return rng.choice(near)
        return token.word if token.word != token.lemma else None

    out, counts = [], {}

    def emit(stratum, rows):
        counts[stratum] = len(rows)
        out.extend(rows)

    def pick(pool, build, shuffle=True):
        rows = []
        order = list(pool)
        if shuffle:
            rng.shuffle(order)
        for entry in order:
            if len(rows) >= size:
                break
            group = [fresh(t) for t in (entry if isinstance(entry, tuple) else (entry,))]
            if None in group:
                continue
            row = build(*group)
            if row is not None:
                taken.update(t.ref for t in group)
                rows.append(row)
        return rows

    emit(RESERVE_STRATA[0], pick(settled, lambda t: records.candidate(t, "lemma", stratum=RESERVE_STRATA[0])))

    def lemma_decoy(t):
        wrong = decoy(t)
        return None if wrong is None else records.candidate(t, "lemma", stratum=RESERVE_STRATA[1], lemma=wrong)
    emit(RESERVE_STRATA[1], pick(settled, lemma_decoy))

    def ordered(a, b):
        return sorted((a, b), key=lambda t: (t.word, t.lemma, t.ref))

    # Plausible look-alikes first: forms the stemmer merges, then forms that share their
    # first letters, then (only if still too few) any two settled words of one POS.
    collisions = [(a, b) for group in by_stem.values() for a, b in itertools.combinations(group, 2)
                  if a.word != b.word and not related(a.lemma, b.lemma)]
    rng.shuffle(collisions)
    if len(collisions) < size:
        by_prefix = defaultdict(list)
        for token in settled:
            by_prefix[(token.upos, token.word[:PREFIX_LETTERS])].append(token)
        alike = [(a, b) for group in by_prefix.values() for a, b in itertools.combinations(group, 2)
                 if a.word != b.word and not related(a.lemma, b.lemma) and stem(a.word) != stem(b.word)]
        if len(alike) > size * 50:
            alike = reservoir(iter(alike), size * 50, rng)
        rng.shuffle(alike)
        collisions += alike
    if len(collisions) < size:
        by_pos = defaultdict(list)
        for token in settled:
            by_pos[token.upos].append(token)
        groups = [g for g in by_pos.values() if len({t.lemma for t in g}) >= 2]
        for _ in range(size * 40):
            if not groups:
                break
            a, b = rng.sample(rng.choice(groups), 2)
            if a.word != b.word and not related(a.lemma, b.lemma):
                collisions.append((a, b))

    def pair_decoy_same(a, b):
        left, right = ordered(a, b)
        if rng.random() < 0.5:
            return records.candidate(left, "pair", right=right, stratum=RESERVE_STRATA[2], other_lemma=left.lemma)
        return records.candidate(left, "pair", right=right, stratum=RESERVE_STRATA[2], lemma=right.lemma)
    emit(RESERVE_STRATA[2], pick(collisions, pair_decoy_same, shuffle=False))

    same = [(a, b) for group in by_lemma.values() for a, b in itertools.combinations(group, 2) if a.word != b.word]
    if len(same) > size * 50:  # a seeded subset keeps memory flat on large corpora
        same = reservoir(iter(same), size * 50, rng)

    def pair_decoy_different(a, b):
        left, right = ordered(a, b)
        if rng.random() < 0.5:
            wrong = decoy(right)
            return None if wrong is None else records.candidate(
                left, "pair", right=right, stratum=RESERVE_STRATA[3], other_lemma=wrong)
        wrong = decoy(left)
        return None if wrong is None else records.candidate(
            left, "pair", right=right, stratum=RESERVE_STRATA[3], lemma=wrong)
    emit(RESERVE_STRATA[3], pick(same, pair_decoy_different))
    return out, counts


def read_candidates(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def prepare(path: Path, *, source_uri: str, license: str,
            pair_count: int = 10000, word_count: int = 1000, seed: int = 0,
            gold_reserve_size: int = 0, min_freq: int = 5, supplement=()):
    """Deterministic stratified candidates; source guesses are not answers.

    gold_reserve_size: items per gold-reserve stratum (gold_reserve), drawn with their
    own seeded generator so the ordinary sample is the same with or without them.
    supplement: candidate rows already prepared from this corpus (an earlier file). The
    output then holds only new item ids and never reuses their occurrences; provenance
    must match theirs."""
    _check_provenance(source_uri, license)
    if (type(pair_count) is not int or type(word_count) is not int or type(gold_reserve_size) is not int
            or pair_count < 0 or word_count < 0 or gold_reserve_size < 0
            or pair_count + word_count + gold_reserve_size == 0):
        raise ValueError("request at least one candidate")
    if type(min_freq) is not int or min_freq < 1:
        raise ValueError("min-freq must be positive")
    raw_digest = digest(path)
    index = index_conllu(path)
    tokens = index.tokens
    if not tokens:
        raise ValueError("corpus contains no eligible form/lemma/POS suggestions")
    # Detect concurrent corpus edits rather than certifying rows with the hash
    # of different bytes. The preparer does not mutate the corpus.
    if digest(path) != raw_digest:
        raise ValueError("corpus changed while preparing candidates")
    corpus_id = str(uuid5(NAMESPACE_URL, "croatian-stemmer-corpus:" + raw_digest))
    supplement = list(supplement)
    for row in supplement:
        if (row.get("corpus_id"), row.get("corpus_sha256"), row.get("source_uri"), row.get("license")) != (
                corpus_id, raw_digest, source_uri, license):
            raise ValueError("the supplemented candidates have a different corpus or provenance "
                             "(corpus_sha256, source URI and license must be the same)")
    records = Records(corpus_id=corpus_id, corpus_sha256=raw_digest, source_uri=source_uri, license=license)
    rows, n_pairs = sample(tokens, records, pair_count=pair_count, word_count=word_count, rng=random.Random(seed))
    existing_ids = {row["item_id"] for row in supplement}
    rows = [row for row in rows if row["item_id"] not in existing_ids]
    used = {ref for row in supplement + rows for ref in (row["word_ref"], row["other_word_ref"]) if ref}
    reserve, reserve_counts = gold_reserve(index, records, size=gold_reserve_size,
                                           min_freq=min_freq, rng=random.Random(f"gold-reserve:{seed}"),
                                           used_refs=used)
    rows += [row for row in reserve if row["item_id"] not in existing_ids]
    receipt = {"candidate_schema_version": 1, "corpus_id": corpus_id,
               "corpus_sha256": raw_digest, "source_uri": source_uri, "license": license,
               "seed": seed, "unique_form_lemma_pos_suggestions": len(tokens),
               "requested_pairs": pair_count, "prepared_pairs": n_pairs,
               "prepared_lemma_items": sum(r["kind"] == "lemma" and not is_reserve(r["sampling_stratum"]) for r in rows),
               "prepared_stem_items": sum(r["kind"] == "stem" for r in rows),
               "human_judgments": 0, "algorithm_sha256": records.algorithm}
    if gold_reserve_size or supplement:
        receipt.update({"gold_reserve": {"size": gold_reserve_size, "min_freq": min_freq, **reserve_counts},
                        "supplement": {"existing_items": len(supplement), "new_items": len(rows)}})
    return rows, receipt

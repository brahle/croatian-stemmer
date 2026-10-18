"""Prepare suggestions from caller-supplied corpora; never create human gold."""

import hashlib
import itertools
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from croatian_stemmer import stem

from .schema import UPOS, digest, normalized


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
    tokens = {}
    for token in occurrences(path):
        tokens.setdefault((token.word, token.lemma, token.upos), token)
    return sorted(tokens.values(), key=lambda t: (t.upos, t.lemma, t.word))


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


def prepare(path: Path, *, source_uri: str, license: str,
            pair_count: int = 10000, word_count: int = 1000, seed: int = 0):
    """Deterministic stratified candidates; source guesses are not answers."""
    if not source_uri.strip() or not license.strip():
        raise ValueError("source URI and license are required")
    if len(source_uri) > 2048 or len(license) > 512 or "\x00" in source_uri + license:
        raise ValueError("invalid source provenance")
    if (type(pair_count) is not int or type(word_count) is not int
            or pair_count < 0 or word_count < 0 or pair_count + word_count == 0):
        raise ValueError("request at least one candidate")
    raw_digest = digest(path)
    tokens = tokens_from_conllu(path)
    if not tokens:
        raise ValueError("corpus contains no eligible form/lemma/POS suggestions")
    # Detect concurrent corpus edits rather than certifying rows with the hash
    # of different bytes. The preparer does not mutate the corpus.
    if digest(path) != raw_digest:
        raise ValueError("corpus changed while preparing candidates")
    corpus_id = str(uuid5(NAMESPACE_URL, "croatian-stemmer-corpus:" + raw_digest))
    rng = random.Random(seed)
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
        pairs.append((left, right, stratum))
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

    # Package source-code hashes with suggestions, not with a fabricated
    # human label. The proposal's concrete value remains the stem target.
    package_root = Path(__file__).resolve().parents[1]
    algorithm = hashlib.sha256()
    for name in ("stemmer.py", "rules.py"):
        algorithm.update((package_root / name).read_bytes())
    algorithm_digest = algorithm.hexdigest()
    records = []

    def candidate(left, kind, *, right=None, stratum="word_suggestion"):
        proposed_stem = stem(left.word) if kind == "stem" else ""
        identity = json.dumps([kind, left.ref, right.ref if right else "", proposed_stem], ensure_ascii=False)
        return {"candidate_schema_version": 1, "corpus_id": corpus_id,
                "corpus_sha256": raw_digest, "source_uri": source_uri, "license": license,
                "item_id": str(uuid5(NAMESPACE_URL, corpus_id + ":" + identity)),
                "kind": kind, "word": left.word, "other_word": right.word if right else "",
                "proposed_lemma": left.lemma, "other_proposed_lemma": right.lemma if right else "",
                "proposed_stem": proposed_stem, "upos": left.upos,
                "context": left.context, "other_context": right.context if right else "",
                "word_ref": left.ref, "other_word_ref": right.ref if right else "",
                "sampling_stratum": stratum, "algorithm_sha256": algorithm_digest}

    for left, right, stratum in pairs:
        records.append(candidate(left, "pair", right=right, stratum=stratum))
    for token in reservoir(tokens, min(word_count, len(tokens)), rng):
        records.append(candidate(token, "lemma"))
        records.append(candidate(token, "stem"))
    return records, {"candidate_schema_version": 1, "corpus_id": corpus_id,
                     "corpus_sha256": raw_digest, "source_uri": source_uri, "license": license,
                     "seed": seed, "unique_form_lemma_pos_suggestions": len(tokens),
                     "requested_pairs": pair_count, "prepared_pairs": len(pairs),
                     "prepared_lemma_items": sum(r["kind"] == "lemma" for r in records),
                     "prepared_stem_items": sum(r["kind"] == "stem" for r in records),
                     "human_judgments": 0, "algorithm_sha256": algorithm_digest}

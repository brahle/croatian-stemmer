"""Bootstrap gold from a corpus that is internally consistent (4.3.1).

Only candidates whose answer the corpus settles beyond doubt become gold: both
forms frequent enough and unambiguous (one lemma per form and POS). The answer of
such gold always equals what the visible suggestion implies, so it serves the
qualification pool (always shown without the suggestion) and the agreeing share of
the audit pool. Gold whose answer differs from the suggestion, and all stem gold,
comes only from people on the trusted list.
"""

import hashlib
import json
import random
from collections import Counter, defaultdict
from pathlib import Path

from .candidates import occurrences, reservoir
from .schema import digest

GOLD_SCHEMA_VERSION = 1
SAME_STRATA = ("corpus_same_lemma_suggestion",)
DIFFERENT_STRATA = ("random_different_lemma_suggestion", "stem_collision_different_lemma_suggestion")
MAX_SAME_SHARE = 0.6


def corpus_counts(path: Path):
    """freq[(form, lemma, upos)] over every occurrence and lemmas_of[(form, upos)]."""
    freq, lemmas_of = Counter(), defaultdict(set)
    for token in occurrences(path):
        freq[(token.word, token.lemma, token.upos)] += 1
        lemmas_of[(token.word, token.upos)].add(token.lemma)
    return freq, lemmas_of


def decide(candidate, freq, lemmas_of, min_freq):
    """(answer, lemma, basis) when the corpus settles the candidate, else None. Never stem."""
    upos = candidate["upos"]

    def settled(form, lemma):
        return freq[(form, lemma, upos)] >= min_freq and lemmas_of[(form, upos)] == {lemma}

    kind, stratum = candidate["kind"], candidate["sampling_stratum"]
    if kind == "pair":
        left, right = candidate["proposed_lemma"], candidate["other_proposed_lemma"]
        if not (settled(candidate["word"], left) and settled(candidate["other_word"], right)):
            return None
        if stratum in SAME_STRATA and left == right:
            return "same", "", "corpus_unambiguous_same_lemma"
        if stratum in DIFFERENT_STRATA and left != right and not left.startswith(right) and not right.startswith(left):
            return "different", "", "corpus_unambiguous_different_lemma"
        return None
    if kind == "lemma" and settled(candidate["word"], candidate["proposed_lemma"]):
        return "confirmed", candidate["proposed_lemma"], "corpus_unambiguous_lemma"
    return None


def build(corpus: Path, candidates: Path, *, min_freq=5, per_kind=400, seed=1, qualification=80, exclude=()):
    """(rows, receipt). Deterministic: identical inputs and options give identical bytes."""
    if min_freq < 1 or per_kind < 1 or qualification < 0:
        raise ValueError("min-freq and per-kind must be positive, the qualification split non-negative")
    corpus_digest = digest(corpus)
    raw = candidates.read_bytes()
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("no candidates")
    if any(row.get("corpus_sha256") != corpus_digest for row in rows):
        raise ValueError("the candidates were not prepared from this corpus (corpus_sha256 differs)")
    freq, lemmas_of = corpus_counts(corpus)
    if digest(corpus) != corpus_digest:
        raise ValueError("corpus changed while building gold")
    excluded = set(exclude)
    eligible = defaultdict(list)  # (kind, answer) -> [(candidate, lemma, basis)]
    for row in rows:
        if row["item_id"] in excluded:
            continue
        decided = decide(row, freq, lemmas_of, min_freq)
        if decided:
            answer, lemma, basis = decided
            eligible[(row["kind"], answer)].append((row, answer, lemma, basis))
    rng = random.Random(seed)
    out, receipt_counts = [], Counter()
    for kind in ("pair", "lemma"):
        if kind == "pair":
            same, different = eligible[("pair", "same")], eligible[("pair", "different")]
            n_same = min(len(same), int(MAX_SAME_SHARE * per_kind))
            n_different = min(len(different), per_kind - n_same)
            # At most 60 % `same`, also when there are too few `different` items.
            n_same = min(n_same, int(n_different * MAX_SAME_SHARE / (1 - MAX_SAME_SHARE)))
            chosen = reservoir(same, n_same, rng) + reservoir(different, n_different, rng)
        else:
            chosen = reservoir(eligible[("lemma", "confirmed")], per_kind, rng)
        rng.shuffle(chosen)
        for index, (row, answer, lemma, basis) in enumerate(chosen):
            pool = "qualification" if index < qualification else "audit"
            out.append({"gold_schema_version": GOLD_SCHEMA_VERSION, "corpus_id": row["corpus_id"],
                        "item_id": row["item_id"], "kind": kind, "pool": pool, "answer": answer, "lemma": lemma,
                        "basis": basis, "source": "hr500k", "corpus_sha256": corpus_digest})
            receipt_counts[(kind, pool, answer, basis)] += 1
    options = {"min_freq": min_freq, "per_kind": per_kind, "seed": seed, "qualification": qualification,
               "exclude": sorted(excluded)}
    inputs = {"corpus_sha256": corpus_digest, "candidates_sha256": hashlib.sha256(raw).hexdigest()}
    batch = hashlib.sha256(json.dumps({**inputs, **options}, sort_keys=True).encode()).hexdigest()[:16]
    for row in out:
        row["batch"] = batch
    receipt = {"gold_schema_version": GOLD_SCHEMA_VERSION, "batch": batch, **inputs, **options,
               "eligible": {f"{kind}/{answer}": len(found) for (kind, answer), found in sorted(eligible.items())},
               "counts": [{"kind": k, "pool": p, "answer": a, "basis": b, "n": n}
                          for (k, p, a, b), n in sorted(receipt_counts.items())],
               "human_judgments": 0}
    return out, receipt

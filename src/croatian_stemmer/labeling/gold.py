"""Bootstrap gold from a corpus that is internally consistent (4.3.1), and the check of a
gold file against the readiness targets of the trust system.

Only candidates whose answer the corpus settles beyond doubt become gold: every form
involved occurs often enough and is unambiguous (one lemma per form and POS). The answer
is the corpus truth, whatever the item shows as its suggestion. Ordinary candidates
show the corpus lemmas, so their gold always agrees with the suggestion; gold whose
answer differs from the suggestion comes from the gold-reserve decoys of `prepare
--gold-reserve` (or from people on the trusted list). Stem gold is never derived from
a corpus: a lemma annotation does not settle whether a stem is acceptable.
"""

import hashlib
import json
import math
import random
import re
from collections import Counter, defaultdict
from pathlib import Path

from .candidates import index_conllu, private_seed, related, reservoir, settled_lemma
from .schema import digest, word
from .scoring import DEFAULT_PARAMS, answer_class, suggested_class, validate_params

GOLD_SCHEMA_VERSION = 1
MAX_SAME_SHARE = 0.6
KINDS = ("pair", "lemma", "stem")
GOLD_FIELDS = {"gold_schema_version", "corpus_id", "item_id", "kind", "pool", "answer", "lemma", "basis", "source",
               "corpus_sha256", "batch"}
ANSWERS = {"pair": ("same", "different"), "lemma": ("confirmed",), "stem": ("accept", "reject")}
# The chance that a pool still meets its target after the import holds out the
# calibration sample (audit_sample_rate per cent of items, decided by a keyed hash).
CONFIDENCE = 0.999


def corpus_counts(path: Path):
    """freq[(form, lemma, upos)] over every occurrence and lemmas_of[(form, upos)]."""
    index = index_conllu(path, keep=0)
    return index.freq, index.lemmas_of


def decide(candidate, freq, lemmas_of, min_freq):
    """(answer, lemma, basis) when the corpus settles the candidate, else None. Never stem.

    The answer is the corpus truth of the forms shown, independent of the suggestion."""
    upos, kind = candidate["upos"], candidate["kind"]
    if kind == "pair":
        left = settled_lemma(freq, lemmas_of, candidate["word"], upos, min_freq)
        right = settled_lemma(freq, lemmas_of, candidate["other_word"], upos, min_freq)
        if left is None or right is None:
            return None
        if left == right:
            return "same", "", "corpus_unambiguous_same_lemma"
        if not related(left, right):
            return "different", "", "corpus_unambiguous_different_lemma"
        return None
    if kind == "lemma":
        lemma = settled_lemma(freq, lemmas_of, candidate["word"], upos, min_freq)
        if lemma is not None:
            return "confirmed", lemma, "corpus_unambiguous_lemma"
    return None


def agrees(candidate, answer, lemma):
    """Whether gold equals what the visible suggestion implies; None for stem. The same
    rule the web import applies to the stored item (routes_trust.gold_agrees)."""
    suggestion = suggested_class(candidate)
    return None if suggestion is None else answer_class(candidate["kind"], answer, lemma) == suggestion


def load_candidates(paths):
    """{item_id: candidate} over one or more candidate files, and their hashes."""
    by_id, hashes = {}, []
    for path in paths:
        raw = path.read_bytes()
        hashes.append(hashlib.sha256(raw).hexdigest())
        for number, line in enumerate(raw.decode("utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if row["item_id"] in by_id and by_id[row["item_id"]] != row:
                raise ValueError(f"{path}:{number}: item {row['item_id']} appears with different content")
            by_id[row["item_id"]] = row
    if not by_id:
        raise ValueError("no candidates")
    return by_id, hashes


def read_gold(path: Path) -> list[dict]:
    rows = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{number}: not JSON ({exc.msg})") from None
    return rows


def needed(target, hold_out_rate, confidence=CONFIDENCE):
    """The fewest rows n such that, when each is held out independently with probability
    hold_out_rate/100, at least `target` remain with probability >= confidence."""
    if target <= 0:
        return 0
    keep = 1 - hold_out_rate / 100
    if keep >= 1:
        return target
    n = target
    while True:
        # P(Binomial(n, keep) >= target), summed in log space.
        total = 0.0
        for k in range(target, n + 1):
            total += math.exp(math.lgamma(n + 1) - math.lgamma(k + 1) - math.lgamma(n - k + 1)
                              + k * math.log(keep) + (n - k) * math.log1p(-keep))
        if total >= confidence:
            return n
        n += 1


def live_pools(data):
    """{kind: {"qualification": {class: n}, "audit": {class: n}, "wrong": n}}: the active gold
    pools of the live site, from the JSON of GET /api/admin/overview (its `readiness`) or of
    GET /api/admin/gold (its `pools`). Classes are the stem answers, or `all`."""
    pools = {kind: {"qualification": {}, "audit": {}, "wrong": 0} for kind in KINDS}
    if isinstance(data, dict) and isinstance(data.get("readiness"), dict):
        for kind in KINDS:
            found = data["readiness"][kind]["pools"]
            pools[kind] = {"qualification": dict(found["qualification"]), "audit": dict(found["audit"]),
                           "wrong": int(found.get("wrong_suggestion") or 0)}
        return pools
    if isinstance(data, dict) and isinstance(data.get("pools"), list):
        for row in data["pools"]:
            if row["status"] != "active":
                continue
            bucket = pools[row["kind"]][row["pool"]]
            bucket["all"] = bucket.get("all", 0) + row["n"]
            if row["pool"] == "audit" and row["suggestion_agrees"] is False:
                pools[row["kind"]]["wrong"] += row["n"]
        return pools
    raise ValueError("live pools: expected the JSON of /api/admin/overview or /api/admin/gold")


def coverage(rows, params=None, live=None, upper_bound=False):
    """Per kind, the pools a gold import of `rows` (dicts with kind, pool, answer and
    agrees, in import order) gives, against the readiness targets of `params`.

    The import fills each kind's qualification pool up to its target and sends the rest
    to audit; it holds out calibration-sampled items (audit_sample_rate per cent). A pool
    is `ok` when it meets its target after that hold-out with probability >= 0.999.
    `live` (live_pools) holds the site's active pools, counted as they are; the rows then
    only need to fill the rest. Without it, earlier gold counted among `rows` is an upper
    bound (`upper_bound`): retired, contested or served-out items are not known offline.
    Stem gold cannot come from a corpus: an empty stem pool is reported as
    `expert_only` and does not make the report fail."""
    params = validate_params(params if params is not None else DEFAULT_PARAMS)
    r, rate = params["readiness"], params["audit_sample_rate"]
    report = {"hold_out_rate": rate, "confidence": CONFIDENCE, "live": live is not None,
              "upper_bound": bool(upper_bound and live is None), "kinds": {}}
    ok = True
    for kind in KINDS:
        mine = [row for row in rows if row["kind"] == kind]
        have = (live or {}).get(kind) or {"qualification": {}, "audit": {}, "wrong": 0}
        live_q, live_a, live_w = sum(have["qualification"].values()), sum(have["audit"].values()), have["wrong"]
        n_q = sum(row["pool"] == "qualification" for row in mine)
        n_a = len(mine) - n_q
        wrong = sum(row["pool"] == "audit" and row["agrees"] is False for row in mine)
        t_q = r["stem_qualification_pool" if kind == "stem" else "qualification_pool"]
        t_a = r["stem_audit_pool" if kind == "stem" else "audit_pool"]
        room = max(0, t_q - live_q)
        q_needed = needed(room, rate)
        q_ok = n_q >= q_needed
        if live is None:
            a_needed = needed(t_q + t_a, rate) - t_q if q_ok else needed(t_a, rate)
            routed = n_a + max(0, n_q - t_q)
        else:  # the live audit pool is certain; new qualification rows fill the room first
            a_needed = needed(max(0, t_a - live_a), rate)
            routed = n_a + max(0, n_q - q_needed)
        entry = {"qualification": {"live": live_q, "rows": n_q, "target": t_q, "needed": q_needed, "ok": q_ok},
                 "audit": {"live": live_a, "rows": routed, "target": t_a, "needed": a_needed, "ok": routed >= a_needed}}
        if kind == "stem":
            share = r["minority_class_share"]
            for pool, rows_in_pool in (("qualification", [x for x in mine if x["pool"] == "qualification"]),
                                       ("audit", [x for x in mine if x["pool"] == "audit"])):
                classes = Counter(x["answer"] for x in rows_in_pool)
                classes.update({c: n for c, n in have[pool].items() if c in ANSWERS["stem"]})
                entry[pool]["classes"] = {c: classes.get(c, 0) for c in ANSWERS["stem"]}
                least = math.ceil(share * (entry[pool]["needed"] + entry[pool]["live"]))
                entry[pool]["minority_needed"] = least
                entry[pool]["ok"] = entry[pool]["ok"] and all(classes.get(c, 0) >= least for c in ANSWERS["stem"])
            if not mine and not live_q + live_a:
                entry["status"] = "expert_only"
                entry["note"] = ("stem known answers are not derivable from a lemmatised corpus; they come from "
                                 "the trusted list (anchor answers through the seed queue) or curator decisions")
            else:
                entry["status"] = "ok" if entry["qualification"]["ok"] and entry["audit"]["ok"] else "short"
                ok = ok and entry["status"] == "ok"
        else:
            w_needed = needed(max(0, r["wrong_suggestion_pool"] - live_w), rate)
            entry["wrong_suggestion"] = {"live": live_w, "rows": wrong, "target": r["wrong_suggestion_pool"],
                                         "needed": w_needed, "ok": wrong >= w_needed}
            entry["status"] = "ok" if all(entry[p]["ok"] for p in ("qualification", "audit", "wrong_suggestion")) \
                else "short"
            ok = ok and entry["status"] == "ok"
        report["kinds"][kind] = entry
    report["ok"] = ok
    return report


def coverage_table(report) -> str:
    """The coverage report as text, for a terminal."""
    lines = [f"Gold coverage against the readiness targets (calibration hold-out {report['hold_out_rate']} %, "
             f"each pool met with probability >= {report['confidence']}):",
             f"  {'kind':6} {'pool':17} {'live':>6} {'rows':>6} {'needed':>7} {'target':>7}  status"]
    for kind, entry in report["kinds"].items():
        for pool in ("qualification", "audit", "wrong_suggestion"):
            if pool not in entry:
                continue
            p = entry[pool]
            extra = ""
            if "classes" in p:
                extra = "  (" + ", ".join(f"{c} {n}" for c, n in p["classes"].items()) + \
                        f"; each class needs {p['minority_needed']})"
            state = "ok" if p["ok"] else ("EXPERT ONLY" if entry["status"] == "expert_only" else "SHORT")
            live = p["live"] if report.get("live") else "-"
            lines.append(f"  {kind:6} {pool:17} {live:>6} {p['rows']:>6} {p['needed']:>7} {p['target']:>7}  "
                         f"{state}{extra}")
        if entry.get("note"):
            lines.append(f"  {kind:6} {entry['note']}")
    if report.get("upper_bound"):
        lines.append("UPPER BOUND: the earlier gold files count as if every row were imported and still active. "
                     "Pass --live with the site's /api/admin/overview JSON for the real pools.")
    lines.append("All pair and lemma pools are covered." if report["ok"] else
                 "SHORT: some pools cannot reach readiness from this gold. See docs/labeling.md "
                 "(prepare --gold-reserve, gold --wrong-suggestion).")
    return "\n".join(lines)


def check_row(row, candidates):
    """The web import's validation of one gold line, offline (requests.GoldRow), plus
    the item's existence in the candidates it was built from."""
    if not isinstance(row, dict) or not set(row) <= GOLD_FIELDS or not (GOLD_FIELDS - {"batch", "lemma"}) <= set(row):
        raise ValueError("fields do not match the gold schema")
    if row["gold_schema_version"] != GOLD_SCHEMA_VERSION:
        raise ValueError("unsupported gold schema version")
    kind = row["kind"]
    if kind not in ANSWERS or row["pool"] not in ("qualification", "audit"):
        raise ValueError("invalid kind or pool")
    if row["answer"] not in ANSWERS[kind]:
        raise ValueError(f"{kind} gold must be one of {ANSWERS[kind]}")
    lemma = row.get("lemma", "")
    if (kind == "lemma") != bool(lemma) or (lemma and word(lemma, "lemma") != lemma):
        raise ValueError("lemma gold needs a normalised lemma; other kinds have none")
    if row["source"] != "hr500k" or not isinstance(row["basis"], str) or not 1 <= len(row["basis"]) <= 64:
        raise ValueError("invalid source or basis")
    if not re.fullmatch(r"[0-9a-f]{64}", str(row["corpus_sha256"])):
        raise ValueError("invalid corpus_sha256")
    candidate = candidates.get(row["item_id"])
    if candidate is None or candidate["corpus_id"] != row["corpus_id"] or candidate["kind"] != kind \
            or candidate["corpus_sha256"] != row["corpus_sha256"]:
        raise ValueError("the item is not in the candidates (or its corpus or kind differs)")
    return candidate


def check(gold_paths, candidate_paths, params=None, live=None):
    """Verify gold files (in import order) against their candidates and the readiness
    targets: every line valid, no item with two different answers, and the coverage."""
    candidates, _ = load_candidates(candidate_paths)
    seen, rows, duplicates = {}, [], 0
    for path in gold_paths:
        for number, row in enumerate(read_gold(path), 1):
            try:
                candidate = check_row(row, candidates)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError(f"{path}:{number}: {exc}") from None
            label = (row["answer"], row.get("lemma", ""))
            if row["item_id"] in seen:
                if seen[row["item_id"]] != label:
                    raise ValueError(f"{path}:{number}: item {row['item_id']} has two different gold answers")
                duplicates += 1  # the import reports it as unchanged
                continue
            seen[row["item_id"]] = label
            rows.append({"kind": row["kind"], "pool": row["pool"], "answer": row["answer"],
                         "agrees": agrees(candidate, *label)})
    report = coverage(rows, params, live=live)
    report["rows"] = len(rows)
    report["duplicates"] = duplicates
    return report


def build(corpus: Path, candidates, *, min_freq=5, per_kind=400, seed=None, qualification=80, wrong=30, exclude=(),
          existing=(), params=None, live=None):
    """(rows, receipt). Deterministic for a given private seed: identical inputs and options give
    identical bytes. seed: private_seed(); drawn at random when not given and recorded in the
    receipt only (which items are gold must not be reproducible from public inputs).

    candidates: one path or a list (an original file and its supplements). existing: gold
    rows already imported (from earlier gold files); their items are never used again and
    they count towards the coverage in the receipt (an upper bound unless `live` gives the
    site's active pools). wrong: suggestion-wrong items per kind, all in the audit pool,
    part of per_kind."""
    seed = private_seed(seed)
    if min_freq < 1 or per_kind < 1 or qualification < 0 or wrong < 0:
        raise ValueError("min-freq and per-kind must be positive, the qualification split and wrong count "
                         "non-negative")
    paths = [candidates] if isinstance(candidates, Path) else list(candidates)
    corpus_digest = digest(corpus)
    by_id, hashes = load_candidates(paths)
    if any(row.get("sampling_stratum", "").startswith("text_") for row in by_id.values()):
        raise ValueError("raw-text candidates (from-text) have no ground truth; gold needs a lemmatised corpus")
    if any(row.get("corpus_sha256") != corpus_digest for row in by_id.values()):
        raise ValueError("the candidates were not prepared from this corpus (corpus_sha256 differs)")
    freq, lemmas_of = corpus_counts(corpus)
    if digest(corpus) != corpus_digest:
        raise ValueError("corpus changed while building gold")
    existing = list(existing)
    known, labels = [], {}
    for number, row in enumerate(existing, 1):
        try:
            candidate = check_row(row, by_id)
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(f"existing gold line {number}: {exc}") from None
        label = (row["answer"], row.get("lemma", ""))
        if row["item_id"] in labels:  # the same item in two earlier files: once, or a conflict
            if labels[row["item_id"]] != label:
                raise ValueError(f"existing gold line {number}: item {row['item_id']} has two different answers")
            continue
        labels[row["item_id"]] = label
        known.append({"kind": row["kind"], "pool": row["pool"], "answer": row["answer"],
                      "agrees": agrees(candidate, *label)})
    excluded = set(exclude) | {row["item_id"] for row in existing}
    eligible = defaultdict(list)  # (kind, answer, agrees) -> [(candidate, answer, lemma, basis, agrees)]
    for row in by_id.values():
        if row["item_id"] in excluded:
            continue
        decided = decide(row, freq, lemmas_of, min_freq)
        if decided:
            answer, lemma, basis = decided
            agree = agrees(row, answer, lemma)
            if not agree:
                basis += "_against_suggestion"
            eligible[(row["kind"], answer, agree)].append((row, answer, lemma, basis, agree))
    rng = random.Random(seed)
    out, receipt_counts = [], Counter()
    for kind in ("pair", "lemma"):
        if kind == "pair":
            # Both directions of a wrong suggestion: shown `same` (answer different) and shown
            # `different` (answer same), half each when both exist.
            shown_same, shown_different = eligible[("pair", "different", False)], eligible[("pair", "same", False)]
            n_a = min(len(shown_same), wrong - wrong // 2)
            n_b = min(len(shown_different), wrong - n_a)
            n_a = min(len(shown_same), wrong - n_b)
            chosen_wrong = reservoir(shown_same, n_a, rng) + reservoir(shown_different, n_b, rng)
            same, different = eligible[("pair", "same", True)], eligible[("pair", "different", True)]
            budget = max(0, per_kind - len(chosen_wrong))
            n_same = min(len(same), int(MAX_SAME_SHARE * budget))
            n_different = min(len(different), budget - n_same)
            # At most 60 % `same`, also when there are too few `different` items.
            n_same = min(n_same, int(n_different * MAX_SAME_SHARE / (1 - MAX_SAME_SHARE)))
            chosen = reservoir(same, n_same, rng) + reservoir(different, n_different, rng)
        else:
            chosen_wrong = reservoir(eligible[("lemma", "confirmed", False)], wrong, rng)
            chosen = reservoir(eligible[("lemma", "confirmed", True)], max(0, per_kind - len(chosen_wrong)), rng)
        rng.shuffle(chosen)
        audit = [(entry, "audit") for entry in chosen[qualification:]] + [(entry, "audit") for entry in chosen_wrong]
        rng.shuffle(audit)
        for (row, answer, lemma, basis, agree), pool in [(e, "qualification") for e in chosen[:qualification]] + audit:
            out.append({"gold_schema_version": GOLD_SCHEMA_VERSION, "corpus_id": row["corpus_id"],
                        "item_id": row["item_id"], "kind": kind, "pool": pool, "answer": answer, "lemma": lemma,
                        "basis": basis, "source": "hr500k", "corpus_sha256": corpus_digest})
            receipt_counts[(kind, pool, answer, basis)] += 1
    options = {"min_freq": min_freq, "per_kind": per_kind, "seed": seed, "qualification": qualification,
               "wrong_suggestion": wrong, "exclude": sorted(set(exclude))}
    inputs = {"corpus_sha256": corpus_digest, "candidates_sha256": hashes if len(hashes) > 1 else hashes[0]}
    if existing:
        inputs["existing_gold_sha256"] = hashlib.sha256(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in existing).encode()).hexdigest()
    batch = hashlib.sha256(json.dumps({**inputs, **options}, sort_keys=True).encode()).hexdigest()[:16]
    for row in out:
        row["batch"] = batch
    new = [{"kind": row["kind"], "pool": row["pool"], "answer": row["answer"],
            "agrees": not row["basis"].endswith("_against_suggestion")} for row in out]
    receipt = {"gold_schema_version": GOLD_SCHEMA_VERSION, "batch": batch, **inputs, **options,
               "eligible": {f"{kind}/{answer}" + ("" if agree else "/against_suggestion"): len(found)
                            for (kind, answer, agree), found in sorted(eligible.items(), key=lambda kv: str(kv[0]))},
               "counts": [{"kind": k, "pool": p, "answer": a, "basis": b, "n": n}
                          for (k, p, a, b), n in sorted(receipt_counts.items())],
               "existing_rows": len(known),
               "coverage": coverage(new if live is not None else known + new, params, live=live,
                                    upper_bound=bool(known)),
               "human_judgments": 0}
    return out, receipt

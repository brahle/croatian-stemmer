"""Trust scoring: a pure function from the journals at a watermark to tiers, weights,
item posteriors, states and the events a run decides.

No I/O, no clock, no randomness and no NumPy: identical inputs give identical outputs
(and `outputs_sha256`) on every machine, so a run can be replayed offline from its
restricted bundle. The database side (barrier, loader, publication fence) lives in
web/scoring_run.py; the model is described in docs/trust.md.
"""

import copy
import hashlib
import json
import math
from bisect import bisect_left
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SCORING_VERSION = "2.0"

DEFAULT_PARAMS = {
    "version": "2.0", "iterations": 10, "prior": [4, 2], "prior_anchor": [18, 2],
    "theta_max": {"new": 0.78, "qualified": 0.80, "established": 0.95, "anchor": 0.98}, "theta_min": 0.5,
    "class_prior": "estimated", "lemma_k": 3,
    "soft_weight": 0.5, "soft_min_info": 1.0, "peer_cap_ratio": 1.0, "peer_cap_floor": 12,
    "gold_delay_days": 1,
    "qualification_n": 12, "qualification_hits": 9,
    "established_disc_gold": 30, "established_theta_lb": 0.75, "established_keep_theta_lb": 0.70,
    "established_wrong_sugg_gold": 5, "established_wrong_sugg_min_acc": 0.6, "established_votes": 100,
    "resolve_confidence": 0.95, "resolve_min_votes": 2, "votes_low_cap": 5, "votes_expert_cap": 3,
    "calibration_n": 30, "calibration_lb": 0.80,
    "audit_sample_rate": 10, "review_sample_rate": 2, "blind_rate": 20,
    "gold_rate": {"new": 10, "qualified": 10, "established": 5, "anchor": 0, "quarantined": 10},
    "gold_max_serves": 150, "gold_pool_warn": 150, "gold_contest_confidence": 0.95,
    "gold_contest_min_votes": 3, "anchor_consensus_votes": None,
    "readiness": {"qualification_pool": 60, "audit_pool": 100, "wrong_suggestion_pool": 15,
                  "stem_qualification_pool": 16, "stem_audit_pool": 30, "minority_class_share": 0.25,
                  "anchors": 1},
    "wrong_suggestion_pick": 0.25, "release_min_voters": 3,
    "quarantine_review_days": 14,
    "flags": {"fast_window": 30, "fast_floor_ms": 1000, "fast_anchor_ratio": 0.25,
              "straight_run": 12, "gold_window": 20, "gold_min_accuracy": 0.6, "gold_min_seen": 12,
              "copy_wrong_min": 5, "copy_wrong_max_acc": 0.4,
              "copy_other_min_acc": 0.9, "audit_min": 10, "audit_max_loss": 0.3,
              "unsure_window": 50, "unsure_max_rate": 0.6, "burst_window_min": 60, "burst_count": 400,
              "signup_burst_window_min": 10, "signup_burst_count": 5},
    "corpora": {},
}

# (type, minimum, maximum) for every numeric setting; nested objects are listed by path.
_NUMBERS = {
    "iterations": (int, 1, 100), "theta_min": (float, 0.5, 0.5), "lemma_k": (int, 2, 50),
    "soft_weight": (float, 0.0, 1.0), "soft_min_info": (float, 0.0, 100.0), "peer_cap_ratio": (float, 0.0, 10.0),
    "peer_cap_floor": (int, 0, 10000), "gold_delay_days": (int, 0, 30),
    "qualification_n": (int, 1, 100), "qualification_hits": (int, 1, 100),
    "established_disc_gold": (int, 1, 10000), "established_theta_lb": (float, 0.5, 0.99),
    "established_keep_theta_lb": (float, 0.5, 0.99), "established_wrong_sugg_gold": (int, 1, 1000),
    "established_wrong_sugg_min_acc": (float, 0.0, 1.0), "established_votes": (int, 0, 1000000),
    "resolve_confidence": (float, 0.9, 0.9999), "resolve_min_votes": (int, 2, 20),
    "votes_low_cap": (int, 1, 100), "votes_expert_cap": (int, 1, 100),
    "calibration_n": (int, 1, 1000), "calibration_lb": (float, 0.5, 0.999),
    "audit_sample_rate": (int, 0, 50), "review_sample_rate": (int, 0, 50), "blind_rate": (int, 0, 100),
    "gold_max_serves": (int, 1, 1000000), "gold_pool_warn": (int, 0, 1000000),
    "gold_contest_confidence": (float, 0.5, 0.9999), "gold_contest_min_votes": (int, 1, 100),
    "wrong_suggestion_pick": (float, 0.0, 1.0), "release_min_voters": (int, 2, 100),
    "quarantine_review_days": (int, 1, 14),
    "readiness.qualification_pool": (int, 1, 100000), "readiness.audit_pool": (int, 1, 100000),
    "readiness.wrong_suggestion_pool": (int, 1, 100000), "readiness.stem_qualification_pool": (int, 1, 100000),
    "readiness.stem_audit_pool": (int, 1, 100000), "readiness.minority_class_share": (float, 0.0, 0.5),
    "readiness.anchors": (int, 0, 1000),
    "flags.fast_window": (int, 1, 10000), "flags.fast_floor_ms": (int, 0, 3600000),
    "flags.fast_anchor_ratio": (float, 0.0, 1.0), "flags.straight_run": (int, 2, 10000),
    "flags.gold_window": (int, 1, 10000), "flags.gold_min_accuracy": (float, 0.0, 1.0),
    "flags.gold_min_seen": (int, 1, 10000), "flags.copy_wrong_min": (int, 1, 10000),
    "flags.copy_wrong_max_acc": (float, 0.0, 1.0), "flags.copy_other_min_acc": (float, 0.0, 1.0),
    "flags.audit_min": (int, 1, 10000), "flags.audit_max_loss": (float, 0.0, 1.0),
    "flags.unsure_window": (int, 1, 10000), "flags.unsure_max_rate": (float, 0.0, 1.0),
    "flags.burst_window_min": (int, 1, 1440), "flags.burst_count": (int, 1, 1000000),
    "flags.signup_burst_window_min": (int, 1, 1440), "flags.signup_burst_count": (int, 1, 1000000),
}
TIER_NAMES = ("new", "qualified", "established", "anchor")
# Per-corpus overrides and their floors: no setting lets one anchor vote resolve an item.
CORPUS_OVERRIDES = {"resolve_confidence": (float, 0.9, 0.9999), "resolve_min_votes": (int, 2, 20),
                    "votes_low_cap": (int, 1, 100), "votes_expert_cap": (int, 1, 100)}
# Settings that cannot change any vote, weight, tier or state: changing them keeps the
# calibration evaluation sets (4.4.7).
CALIBRATION_NEUTRAL = ("calibration_n", "calibration_lb", "release_min_voters", "gold_pool_warn",
                       "quarantine_review_days", "audit_sample_rate", "review_sample_rate")


def _number(value, kind, low, high, name):
    if kind is int:
        ok = type(value) is int
    else:
        ok = type(value) in (int, float) and value == value and value not in (float("inf"), float("-inf"))
    if not ok or not low <= value <= high:
        raise ValueError(f"{name} must be a{'n integer' if kind is int else ' number'} in [{low}, {high}]")
    return kind(value)


def validate_params(raw) -> dict:
    """A complete, bounded parameter set (every key required, no extra key), or ValueError."""
    if not isinstance(raw, dict):
        raise ValueError("parameters must be an object")
    expected = set(DEFAULT_PARAMS)
    if set(raw) != expected:
        missing, extra = sorted(expected - set(raw)), sorted(set(raw) - expected)
        raise ValueError(f"parameters must have exactly the documented keys (missing {missing}, extra {extra})")
    params = copy.deepcopy(raw)
    if params["version"] != SCORING_VERSION:
        raise ValueError(f"version must be {SCORING_VERSION}")
    for group in ("readiness", "flags"):
        if not isinstance(params[group], dict) or set(params[group]) != set(DEFAULT_PARAMS[group]):
            raise ValueError(f"{group} must have exactly the documented keys")
    for path, (kind, low, high) in _NUMBERS.items():
        head, _, tail = path.partition(".")
        holder, key = (params[head], tail) if tail else (params, head)
        holder[key] = _number(holder[key], kind, low, high, path)
    for key in ("prior", "prior_anchor"):
        value = params[key]
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"{key} must be [alpha, beta]")
        params[key] = [_number(v, float, 0.01, 1000, key) for v in value]
    if not isinstance(params["theta_max"], dict) or set(params["theta_max"]) != set(TIER_NAMES):
        raise ValueError("theta_max must name new, qualified, established and anchor")
    for tier in TIER_NAMES:
        params["theta_max"][tier] = _number(params["theta_max"][tier], float, 0.5, 0.995, f"theta_max.{tier}")
    rates = params["gold_rate"]
    if not isinstance(rates, dict) or set(rates) != set(TIER_NAMES) | {"quarantined"}:
        raise ValueError("gold_rate must name every tier")
    for tier in rates:
        rates[tier] = _number(rates[tier], int, 0, 100, f"gold_rate.{tier}")
    if params["class_prior"] not in ("estimated", "uniform"):
        raise ValueError("class_prior must be estimated or uniform")
    if params["anchor_consensus_votes"] is not None:
        params["anchor_consensus_votes"] = _number(params["anchor_consensus_votes"], int, 1, 10, "anchor_consensus_votes")
    if params["qualification_hits"] > params["qualification_n"]:
        raise ValueError("qualification_hits cannot exceed qualification_n")
    corpora = params["corpora"]
    if not isinstance(corpora, dict) or len(corpora) > 1000:
        raise ValueError("corpora must be an object of per-corpus overrides")
    for corpus_id, override in corpora.items():
        if not isinstance(corpus_id, str) or len(corpus_id) != 36 or not isinstance(override, dict):
            raise ValueError("corpora maps corpus ids to overrides")
        for key, value in override.items():
            if key not in CORPUS_OVERRIDES:
                raise ValueError(f"corpora.{corpus_id}.{key} cannot be overridden per corpus")
            override[key] = _number(value, *CORPUS_OVERRIDES[key], f"corpora.{corpus_id}.{key}")
    return params


def canonical(value) -> bytes:
    """The one serialisation that every hash in this module is taken over."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def params_sha256(params) -> str:
    return sha256(params)


JOURNALS = ("items", "judgments", "consents", "admin_events", "trust_events")


def inputs_summary(inputs) -> dict:
    """Per journal: its row count and a hash that does not depend on row order."""
    summary = {}
    for name in JOURNALS:
        digest = hashlib.sha256()
        for row in sorted(canonical(row) for row in inputs[name]):
            digest.update(row)
            digest.update(b"\n")
        summary[name] = {"rows": len(inputs[name]), "sha256": digest.hexdigest()}
    return summary


def inputs_sha256(inputs, summary=None) -> str:
    return sha256({"watermark": inputs["watermark"], "as_of_day": inputs["as_of_day"],
                   "journals": summary or inputs_summary(inputs)})


def changed_journals(then, now) -> list:
    """What a later privacy action (erasure re-keying, timing retention, redaction) changed in
    a run's inputs: [{journal, rows_then, rows_now}] for every journal whose hash differs."""
    return [{"journal": name, "rows_then": then[name]["rows"], "rows_now": now[name]["rows"]}
            for name in JOURNALS if then[name]["sha256"] != now[name]["sha256"]]


# ---- vocabulary ----------------------------------------------------------------

KINDS = ("pair", "lemma", "stem")
BINARY_CLASSES = {"pair": ("same", "different"), "stem": ("accept", "reject")}
CELLS = {"pair": ("agrees", "differs"), "lemma": ("agrees", "differs"), "stem": ("none",)}
OTHER = ""  # the lemma class of every lemma nobody voted
# Who is profiled: the notice versions that describe profiling, the terms and the
# participation statement, each confirmed with the minimum age (4.13.1).
PROFILING_COHORT = (("privacy", (1, 3)), ("terms", (1, 1)), ("participation", (1, 0)))
MINIMUM_AGE = 18
HARD_FLAGS = ("fast", "straight", "accuracy", "copy", "review_loss", "burst")
REPORTED_FLAGS = ("unsure_heavy", "disagree")
ROUND = 9


def answer_class(kind, answer, lemma):
    """The class a judgment votes for, or None for an abstention."""
    if answer == "unsure":
        return None
    if kind == "lemma":
        return lemma if answer == "confirmed" and lemma else None
    return answer


def class_answer(kind, cls):
    """(answer, lemma) for a class."""
    if kind == "lemma":
        return ("other", "") if cls == OTHER else ("confirmed", cls)
    return cls, ""


def suggested_class(item):
    """What the visible suggestion implies; None for stem (no suggestion-derived answer)."""
    if item["kind"] == "pair":
        return "same" if item["proposed_lemma"] == item["other_proposed_lemma"] else "different"
    if item["kind"] == "lemma":
        return item["proposed_lemma"]
    return None


def cell_of(item, winner):
    if item["kind"] == "stem" or winner is None:
        return "none"
    return "agrees" if winner == suggested_class(item) else "differs"


def _version(value):
    try:
        return tuple(int(part) for part in value.split("."))
    except (AttributeError, ValueError):
        return None


def in_profiling_cohort(rows) -> bool:
    """rows: (document, version, age_threshold). The same rule on the request path (current
    rows) and in a run (rows up to the watermark)."""
    accepted = [(document, _version(version)) for document, version, age in rows if age == MINIMUM_AGE]
    return all(any(document == wanted and version is not None and version >= minimum
                   for document, version in accepted) for wanted, minimum in PROFILING_COHORT)


def clip(theta, ceiling, floor=0.5):
    return min(max(theta, floor), ceiling)


def weight(theta, k):
    """One-coin Dawid-Skene log-odds weight of a vote at accuracy theta among k classes."""
    return math.log(theta * (k - 1) / (1 - theta))


def posterior(log_prior, sums):
    """Softmax over classes (in log_prior's order) of the log prior plus the summed weights."""
    scores = [(cls, value + sums.get(cls, 0.0)) for cls, value in log_prior]
    top = max(score for _, score in scores)
    exps = [(cls, math.exp(score - top)) for cls, score in scores]
    total = 0.0
    for _, value in exps:
        total += value
    return {cls: value / total for cls, value in exps}


def theta_lower_bound(alpha0, beta0, hits, seen):
    """Normal approximation of the Beta 5th percentile (no SciPy)."""
    mu = (alpha0 + hits) / (alpha0 + beta0 + seen)
    return mu - 1.645 * math.sqrt(mu * (1 - mu) / (alpha0 + beta0 + seen + 1))


def wilson_lower_bound(correct, n, z=1.96):
    if n == 0:
        return 0.0
    p = correct / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - spread) / (1 + z * z / n)


def corpus_params(params, corpus_id):
    """The parameter set for one corpus (resolution overrides applied)."""
    override = params["corpora"].get(str(corpus_id))
    return {**params, **override} if override else params


def calibration_key(params) -> str:
    """Draws are frozen per policy: everything that can change a vote, weight, tier or state."""
    policy = {key: value for key, value in params.items() if key not in CALIBRATION_NEUTRAL}
    return sha256({"scoring_version": SCORING_VERSION, "params": policy})


def readiness(kind, pools, anchors, params):
    """Which capabilities are on for a kind, from the active valid gold pools.

    pools: {"qualification": {class: n}, "audit": {class: n}, "wrong": n}. The scheduler
    calls this with live counts, a run with the counts at its watermark."""
    r = params["readiness"]

    def total(pool):
        return sum(pool.values())

    def balanced(pool, target):
        n = total(pool)
        classes = BINARY_CLASSES["stem"]
        return n >= target and all(pool.get(c, 0) >= r["minority_class_share"] * n for c in classes)

    if kind == "stem":
        qualification = balanced(pools["qualification"], r["stem_qualification_pool"])
        audit = balanced(pools["audit"], r["stem_audit_pool"])
        wrong = None
    else:
        qualification = total(pools["qualification"]) >= r["qualification_pool"]
        audit = total(pools["audit"]) >= r["audit_pool"]
        wrong = pools["wrong"] >= r["wrong_suggestion_pool"]
    return {"qualification": qualification, "audit": audit, "wrong_suggestion": wrong,
            "promotion": audit and wrong is not False and anchors >= r["anchors"],
            "copy_flag": bool(wrong), "accuracy_flag": audit, "anchors": anchors,
            "pools": {"qualification": dict(sorted(pools["qualification"].items())),
                      "audit": dict(sorted(pools["audit"].items())), "wrong_suggestion": pools["wrong"]}}


def count_first_answers(firsts, eligible, caps, exempt=lambda a: False, uncapped=False):
    """The capped count of admitted first answers (4.4.2), in seq order.

    firsts: [(annotator, admitted, group)] in seq order, one per annotator. Returns
    ({"low": n, "expert": n}, set of counted annotators). Admission at answer time and a
    run use this one rule, so a slot freed by a later ineligibility is free for both."""
    used, counted = {"low": 0, "expert": 0}, set()
    for annotator, admitted, group in firsts:
        if not admitted or not eligible(annotator):
            continue
        if exempt(annotator):
            counted.add(annotator)
        elif uncapped or used[group] < caps[group]:
            used[group] += 1
            counted.add(annotator)
    return used, counted


def top(probs):
    """The winning class: highest probability, ties to a voted class, then by name."""
    return sorted(probs, key=lambda c: (-probs[c], c == OTHER, c))[0]


def model_rule(log_prior, votes, k, tiers, p):
    """(met, winner, probabilities) for votes [(annotator, cls, theta_weight_fn)] under the
    item's prior: confidence >= resolve_confidence, at least resolve_min_votes distinct
    voters, and a vote for the winner from an established or anchor annotator."""
    if not votes:
        return False, None, None
    sums = {}
    for annotator, cls, w in votes:
        sums[cls] = sums.get(cls, 0.0) + w
    probs = posterior(log_prior, sums)
    winner = top(probs)
    voters = {annotator for annotator, _, _ in votes}
    expert = any(cls == winner and tiers.get(annotator) in ("established", "anchor") for annotator, cls, _ in votes)
    met = probs[winner] >= p["resolve_confidence"] and len(voters) >= p["resolve_min_votes"] and expert
    return met, winner, probs


def release_rule(log_prior, votes, k, tiers, p):
    """At least release_min_voters distinct voters and no pivotal one: the model rule still
    holds after removing any single vote (4.11.2)."""
    met, winner, _ = model_rule(log_prior, votes, k, tiers, p)
    if not met or len({a for a, _, _ in votes}) < p["release_min_voters"]:
        return False
    for index in range(len(votes)):
        rest = votes[:index] + votes[index + 1:]
        still, other, _ = model_rule(log_prior, rest, k, tiers, p)
        if not still or other != winner:
            return False
    return True


# ---- the run ---------------------------------------------------------------------

class _Judgment:
    __slots__ = ("seq", "id", "key", "annotator", "revision", "answer", "lemma", "irregular", "admitted",
                 "group", "presentation", "elapsed_ms", "created", "day", "cls", "kind")


class _Gold:
    __slots__ = ("kind", "pool", "cls", "answer", "lemma", "source", "agrees", "support", "creator",
                 "set_seq", "valid", "validity_kind", "retired", "reactivated_seq", "disclosed_seq", "exists")


def _parse(inputs):
    items = {}
    for row in inputs["items"]:
        key = (row["corpus_id"], row["item_id"])
        items[key] = row
    judgments = []
    for row in inputs["judgments"]:
        key = (row["corpus_id"], row["item_id"])
        item = items.get(key)
        if item is None:
            raise ValueError("a judgment refers to an item outside the run's membership")
        j = _Judgment()
        j.seq, j.id, j.key = row["seq"] or 0, row["id"], key
        j.annotator, j.revision, j.answer, j.lemma = row["annotator_id"], row["revision"], row["answer"], row["lemma"]
        j.irregular = row["irregular"]
        j.admitted = True if row["admitted"] is None else row["admitted"]
        j.group = row["admission_group"] or "low"
        j.presentation = row["presentation"] or "shown"
        j.elapsed_ms = row["elapsed_ms"]
        j.created = datetime.fromisoformat(row["created_at"])
        j.day = j.created.astimezone(timezone.utc).date()
        j.kind = item["kind"]
        j.cls = answer_class(j.kind, j.answer, j.lemma)
        judgments.append(j)
    judgments.sort(key=lambda j: (j.seq, j.id))
    return items, judgments


def _seq(row):
    return (row.get("seq") or 0, row["id"])


def score(inputs, params):
    """The scoring run's pure step (4.6.4 step 4). See the module docstring."""
    p = params
    watermark = inputs["watermark"]
    today = date.fromisoformat(inputs["as_of_day"])
    items, judgments = _parse(inputs)
    item_keys = sorted(items)

    # (a) state at the watermark: statuses, cohort, anchors, epochs, curator decisions.
    status, last_status = {}, {}
    for event in sorted(inputs["admin_events"], key=_seq):
        if event["kind"] == "annotator.status":
            status[event["target"]] = event["details"].get("to", "active")
            last_status[event["target"]] = event
        elif event["kind"] == "erasure.requested":
            status[event["target"]] = "erased"
    consents = defaultdict(list)
    for row in inputs["consents"]:
        consents[row["annotator_id"]].append((row["document"], row["version"], row["age_threshold"]))
    cohort = {a for a, rows in consents.items() if in_profiling_cohort(rows)}

    trust = sorted(inputs["trust_events"], key=lambda e: e["id"])
    anchors, flags_since, memory = set(), {}, {}
    reopens, curator = defaultdict(list), {}
    draws, redraws, gold_events = [], {}, defaultdict(list)
    for event in trust:
        kind, who, details = event["kind"], event["annotator_id"], event["details"]
        key = (event["corpus_id"], event["item_id"])
        if kind == "anchor.granted":
            anchors.add(who)
        elif kind == "anchor.revoked":
            anchors.discard(who)
        elif kind == "annotator.cleared":
            flags_since[who] = event["id"]
        elif kind == "tier.changed":
            memory[(who, details["kind"])] = details["to"]
        elif kind == "item.reopened":
            reopens[key].append((event["id"], bool(details.get("discard_previous"))))
            curator[key] = ("reopened", event)
        elif kind in ("item.ambiguous", "item.adjudicated"):
            curator[key] = (kind.split(".")[1], event)
        elif kind == "calibration.drawn":
            draws.append(event)
        elif kind == "calibration.redraw_requested":
            redraws[(details["kind"], details["cell"])] = event["id"]
        elif kind.startswith("gold."):
            gold_events[key].append(event)
    n_anchors = len(anchors)

    def state_of(a):
        return status.get(a, "active")

    # Judgments per (annotator, item), in revision order.
    by_pair = defaultdict(list)
    by_item = defaultdict(list)
    for j in judgments:
        by_pair[(j.annotator, j.key)].append(j)
    for pair in by_pair.values():
        pair.sort(key=lambda j: j.revision)
    for (annotator, key), rows in sorted(by_pair.items()):
        by_item[key].append(annotator)

    # (b) gold versions and validity at the watermark, then consensus-support retractions.
    gold = {}
    decided = []  # events this run decides, in a fixed order
    for key in sorted(gold_events):
        g = _Gold()
        g.exists, g.set_seq, g.valid, g.validity_kind = False, 0, False, None
        g.retired, g.reactivated_seq, g.disclosed_seq, g.support, g.creator = False, 0, None, None, None
        for event in gold_events[key]:
            kind, details = event["kind"], event["details"]
            if kind == "gold.set":
                g.exists, g.set_seq = True, event["id"]
                g.kind = items[key]["kind"] if key in items else details.get("kind")
                g.pool, g.answer, g.lemma = details["pool"], details["answer"], details.get("lemma", "")
                g.cls = answer_class(g.kind, g.answer, g.lemma)
                g.source, g.agrees = details["source"], details.get("suggestion_agrees")
                g.support = details.get("support") if g.source == "anchor_consensus" else None
                g.creator = event["actor_id"] if g.source == "curator" else None
            if kind in ("gold.set", "gold.reactivated", "gold.contested", "gold.retracted"):
                g.validity_kind = kind
            if kind == "gold.retired":
                g.retired = True
            if kind == "gold.reactivated":
                g.retired, g.reactivated_seq = False, event["id"]
            if kind == "gold.disclosed" and g.disclosed_seq is None:
                g.disclosed_seq = event["id"]
        if not g.exists or key not in items:
            continue
        g.valid = g.validity_kind in ("gold.set", "gold.reactivated")
        gold[key] = g

    def latest_definite(annotator, key):
        rows = by_pair.get((annotator, key), ())
        return rows[-1] if rows and rows[-1].cls is not None else None

    def supporters(g):
        if g.source == "anchor_consensus":
            support = g.support or {}
            return set(support.get("annotators", ()))
        return {g.creator} if g.creator else set()

    for key in sorted(gold):
        g = gold[key]
        if not g.valid or g.source != "anchor_consensus":
            continue
        support = g.support or {}
        holds = not support.get("redacted") and bool(support.get("annotators"))
        for annotator, judgment_id in zip(support.get("annotators", ()), support.get("judgments", ())):
            latest = latest_definite(annotator, key)
            if (annotator not in anchors or state_of(annotator) in ("blocked", "quarantined", "erased")
                    or latest is None or latest.id != judgment_id or latest.cls != g.cls):
                holds = False
        if not holds:
            g.valid = False
            decided.append({"kind": "gold.retracted", "annotator_id": None, "corpus_id": key[0], "item_id": key[1],
                            "details": {"reason": "support"}})

    def gold_status(g):
        if g is None:
            return None
        if not g.valid:
            return "contested" if g.validity_kind == "gold.contested" else "retracted"
        return "retired" if g.retired else "active"

    def pools_of(kind):
        pools = {"qualification": {}, "audit": {}, "wrong": 0}
        for key in sorted(gold):
            g = gold[key]
            if g.kind != kind or not g.valid or g.retired:
                continue
            pools[g.pool][g.cls if kind == "stem" else "all"] = pools[g.pool].get(g.cls if kind == "stem" else "all", 0) + 1
            if g.pool == "audit" and g.agrees is False:
                pools["wrong"] += 1
        return pools

    ready = {kind: readiness(kind, pools_of(kind), n_anchors, p) for kind in KINDS}

    # (c) hard observations, qualification, preliminary evidence.
    subjects = sorted({j.annotator for j in judgments if j.annotator in cohort})
    obs = defaultdict(list)  # (annotator, kind) -> [(seq, id, hit, disc, wrong, pool, gold_cls)]
    cutoff_day = today - timedelta(days=p["gold_delay_days"])
    for key in sorted(gold):
        g = gold[key]
        if not g.valid:
            continue
        excluded = supporters(g)
        for annotator in by_item.get(key, ()):
            if annotator not in cohort or state_of(annotator) == "blocked" or annotator in excluded:
                continue
            first = next((j for j in by_pair[(annotator, key)] if j.cls is not None), None)
            if first is None:
                continue
            if g.disclosed_seq is not None and first.seq >= g.disclosed_seq:
                continue
            if g.pool == "audit" and not first.day <= cutoff_day:
                continue  # an unannounced check counts from the following (UTC) day
            disc = g.kind == "stem" or first.presentation == "blind" or g.agrees is False
            wrong = g.kind != "stem" and g.agrees is False
            obs[(annotator, g.kind)].append((first.seq, first.id, first.cls == g.cls, disc, wrong, g.pool, g.cls))
    for rows in obs.values():
        rows.sort()

    evidence = {}
    for annotator in subjects:
        for kind in KINDS:
            rows = obs.get((annotator, kind), [])
            qual = [r for r in rows if r[5] == "qualification"][:p["qualification_n"]]
            audit = [r for r in rows if r[5] == "audit"]
            disc = [r for r in rows if r[3]]
            wrong = [r for r in rows if r[4]]
            per_class = {}
            for r in rows:
                seen, hits = per_class.get(r[6], (0, 0))
                per_class[r[6]] = (seen + 1, hits + r[2])
            evidence[(annotator, kind)] = {
                "h": sum(r[2] for r in rows), "m": sum(not r[2] for r in rows),
                "gold_seen": len(audit), "gold_hits": sum(r[2] for r in audit),
                "disc_seen": len(disc), "disc_hits": sum(r[2] for r in disc),
                "wrong_seen": len(wrong), "wrong_hits": sum(r[2] for r in wrong),
                "per_class": per_class,
                "qualified": len(qual) == p["qualification_n"] and sum(r[2] for r in qual) >= p["qualification_hits"],
                "qualification_done": len(qual)}

    latest_by_kind = defaultdict(lambda: [0, 0])  # (annotator, kind) -> [definite, unsure]
    for (annotator, key), rows in by_pair.items():
        counts = latest_by_kind[(annotator, items[key]["kind"])]
        counts[0 if rows[-1].cls is not None else 1] += 1

    def prior_of(annotator):
        return p["prior_anchor"] if annotator in anchors else p["prior"]

    def established(annotator, kind):
        if not ready[kind]["promotion"]:
            return False
        e = evidence[(annotator, kind)]
        alpha0, beta0 = prior_of(annotator)
        lb = theta_lower_bound(alpha0, beta0, e["disc_hits"], e["disc_seen"])

        def floor(min_acc):
            if kind == "stem":
                return all(e["per_class"].get(c, (0, 0))[0] >= p["established_wrong_sugg_gold"]
                           and e["per_class"][c][1] / e["per_class"][c][0] >= min_acc for c in BINARY_CLASSES["stem"])
            return (e["wrong_seen"] >= p["established_wrong_sugg_gold"]
                    and e["wrong_hits"] / e["wrong_seen"] >= min_acc)
        if (e["disc_seen"] >= p["established_disc_gold"] and lb >= p["established_theta_lb"]
                and latest_by_kind[(annotator, kind)][0] >= p["established_votes"]
                and floor(p["established_wrong_sugg_min_acc"])):
            return True
        return (memory.get((annotator, kind)) == "established" and e["disc_seen"] >= p["established_disc_gold"]
                and floor(0.5) and lb >= p["established_keep_theta_lb"])

    def base_tier(annotator, kind):
        if annotator in anchors:
            return "anchor"
        if established(annotator, kind):
            return "established"
        return "qualified" if evidence[(annotator, kind)]["qualified"] else "new"

    # (d) flags, new automatic quarantines, releases at the review deadline.
    released = set()
    for annotator in subjects:
        if state_of(annotator) != "quarantined":
            continue
        event = last_status.get(annotator)
        automated = event is not None and event["actor_id"] is None and event["details"].get("run_id")
        if automated:
            at = datetime.fromisoformat(event["at"]).astimezone(timezone.utc).date()
            if (today - at).days >= p["quarantine_review_days"]:
                released.add(annotator)
    for annotator in sorted(released):
        flags_since[annotator] = watermark  # nothing before the release counts against them

    anchor_timing = {}
    for kind in KINDS:
        values = sorted(j.elapsed_ms for j in judgments if j.annotator in anchors and j.kind == kind
                        and j.cls is not None and j.elapsed_ms is not None and not items[j.key]["audit_sample"])
        anchor_timing[kind] = _median(values) if len(values) >= 100 else None

    anchor_answers = {}
    for key in item_keys:
        classes = {latest_definite(a, key).cls for a in by_item.get(key, ()) if a in anchors and latest_definite(a, key)}
        if len(classes) == 1:
            anchor_answers[key] = classes.pop()

    flags, flag_names = {}, defaultdict(set)
    per_annotator = defaultdict(list)
    for j in judgments:
        per_annotator[(j.annotator, j.kind)].append(j)
    f = p["flags"]
    for annotator in subjects:
        since = flags_since.get(annotator, 0)
        for kind in KINDS:
            if not per_annotator.get((annotator, kind)):
                continue
            rows = [j for j in per_annotator[(annotator, kind)] if j.seq > since]
            definite = [j for j in rows if j.cls is not None]
            signals = {}
            timed = [j.elapsed_ms for j in definite if j.elapsed_ms is not None][-f["fast_window"]:]
            threshold = f["fast_floor_ms"]
            if anchor_timing[kind] is not None:
                threshold = max(threshold, f["fast_anchor_ratio"] * anchor_timing[kind])
            median = _median(sorted(timed)) if timed else None
            signals["fast"] = {"on": len(timed) >= f["fast_window"] and median < threshold,
                               "median_ms": median, "threshold_ms": threshold, "n": len(timed)}
            longest, run, previous = 0, 0, None
            for j in definite:
                run = run + 1 if j.cls == previous else 1
                previous = j.cls
                longest = max(longest, run)
            signals["straight"] = {"on": kind in ("pair", "stem") and longest >= f["straight_run"], "longest": longest}
            mine = [r for r in obs.get((annotator, kind), ()) if r[0] > since]
            audit = [r for r in mine if r[5] == "audit"][-f["gold_window"]:]
            accuracy = sum(r[2] for r in audit) / len(audit) if audit else None
            signals["accuracy"] = {"on": ready[kind]["accuracy_flag"] and len(audit) >= f["gold_min_seen"]
                                   and accuracy < f["gold_min_accuracy"], "seen": len(audit), "accuracy": accuracy}
            wrong = [r for r in mine if r[4]]
            other = [r for r in mine if not r[4]]
            wrong_acc = sum(r[2] for r in wrong) / len(wrong) if wrong else None
            other_acc = sum(r[2] for r in other) / len(other) if other else None
            signals["copy"] = {"on": ready[kind]["copy_flag"] and len(wrong) >= f["copy_wrong_min"]
                               and wrong_acc <= f["copy_wrong_max_acc"] and other_acc is not None
                               and other_acc >= f["copy_other_min_acc"],
                               "wrong_seen": len(wrong), "wrong_accuracy": wrong_acc, "other_accuracy": other_acc}
            checked = lost = 0
            if annotator not in anchors:
                for key in sorted({j.key for j in rows}):
                    if key not in anchor_answers or items[key]["audit_sample"]:
                        continue
                    mine_latest = latest_definite(annotator, key)
                    if mine_latest is None or mine_latest.seq <= since:
                        continue
                    checked += 1
                    lost += mine_latest.cls != anchor_answers[key]
            signals["review_loss"] = {"on": checked >= f["audit_min"] and lost / checked > f["audit_max_loss"],
                                      "checked": checked, "lost": lost}
            times = sorted(j.created for j in rows)
            busiest, start = 0, 0
            window = timedelta(minutes=f["burst_window_min"])
            for end in range(len(times)):
                while times[end] - times[start] >= window:
                    start += 1
                busiest = max(busiest, end - start + 1)
            signals["burst"] = {"on": busiest >= f["burst_count"] and signals["fast"]["on"], "busiest": busiest}
            recent = rows[-f["unsure_window"]:]
            rate = sum(j.cls is None for j in recent) / len(recent) if recent else None
            signals["unsure_heavy"] = {"on": len(recent) >= f["unsure_window"] and rate > f["unsure_max_rate"],
                                       "rate": rate}
            flags[(annotator, kind)] = signals
            for name in HARD_FLAGS:
                if signals[name]["on"]:
                    flag_names[annotator].add(name)

    quarantined_now = set()
    status_changes = []
    for annotator in subjects:
        if (state_of(annotator) == "active" and annotator not in anchors
                and len(flag_names[annotator]) >= 2):
            quarantined_now.add(annotator)
            named = sorted(flag_names[annotator])
            status_changes.append({"annotator_id": annotator, "from": "active", "to": "quarantined", "flags": named})
            by_kind = {kind: sorted(n for n in HARD_FLAGS if flags.get((annotator, kind), {}).get(n, {}).get("on"))
                       for kind in KINDS if (annotator, kind) in flags}
            decided.append({"kind": "annotator.quarantined", "annotator_id": annotator, "corpus_id": None,
                            "item_id": None, "details": {"flags": by_kind}})
    for annotator in sorted(released):
        status_changes.append({"annotator_id": annotator, "from": "quarantined", "to": "active",
                               "reason": "review_deadline"})
        decided.append({"kind": "annotator.cleared", "annotator_id": annotator, "corpus_id": None, "item_id": None,
                        "details": {"reason": "review_deadline"}})

    def final_status(a):
        if a in quarantined_now:
            return "quarantined"
        if a in released:
            return "active"
        return state_of(a)

    def eligible(a):
        return a in cohort and final_status(a) not in ("blocked", "quarantined", "erased")

    tiers, base_tiers = {}, {}
    for annotator in subjects:
        for kind in KINDS:
            if (annotator, kind) not in evidence:
                continue
            base = base_tier(annotator, kind)
            base_tiers[(annotator, kind)] = base
            tiers[(annotator, kind)] = "quarantined" if final_status(annotator) == "quarantined" else base

    # Votes per item: counted first answers per epoch segment, capped per admission group.
    votes, references, counts = {}, {}, {}
    for key in item_keys:
        item = items[key]
        kind = item["kind"]
        pc = corpus_params(p, key[0])
        g = gold.get(key)
        gold_valid = g is not None and g.valid
        bounds = [seq for seq, _ in reopens.get(key, ())]
        discard = max([seq for seq, d in reopens.get(key, ()) if d], default=0)
        firsts = defaultdict(list)
        for annotator in by_item.get(key, ()):
            seen = set()
            for j in by_pair[(annotator, key)]:
                if j.seq <= discard and discard:
                    continue
                segment = bisect_left(bounds, j.seq)
                if segment not in seen:
                    seen.add(segment)
                    firsts[segment].append(j)
        sampled = item["audit_sample"] or item["review_sample"]
        counted, current = set(), {"low": 0, "expert": 0}
        caps = {"low": pc["votes_low_cap"], "expert": pc["votes_expert_cap"]}
        for segment in sorted(firsts):
            rows = sorted(firsts[segment], key=lambda j: (j.seq, j.id))
            if item["audit_sample"]:  # anchors' answers on calibration items are references, not votes
                rows = [j for j in rows if j.annotator not in anchors]
            used, chosen = count_first_answers(
                [(j.annotator, j.admitted, j.group) for j in rows], eligible, caps,
                exempt=lambda a: sampled and a in anchors, uncapped=gold_valid)
            counted |= chosen
            if segment == len(bounds):
                current = used
        cast = []
        for annotator in sorted(counted):
            rows = [j for j in by_pair[(annotator, key)] if not (discard and j.seq <= discard)]
            if rows:
                cast.append(rows[-1])
        votes[key] = cast
        counts[key] = current
        if item["audit_sample"]:
            references[key] = {a: by_pair[(a, key)] for a in by_item.get(key, ()) if a in anchors}

    # (e) EM per kind, with the final tiers.
    thetas, soft = {}, {}
    pis = {}
    for kind in KINDS:
        people = {}
        for a in subjects:
            alpha0, beta0 = prior_of(a)
            e = evidence[(a, kind)]
            people[a] = (alpha0, beta0, e["h"], e["m"], p["theta_max"][base_tiers[(a, kind)]], eligible(a))
        work = []
        for key in item_keys:
            if items[key]["kind"] != kind:
                continue
            definite = [(j.annotator, j.cls) for j in votes[key] if j.cls is not None]
            if definite:
                g = gold.get(key)
                work.append((key, items[key]["stratum"], definite, g is not None and g.valid))
        result = fit(kind, work, people, p)
        for a in subjects:
            thetas[(a, kind)] = result["theta"][a]
            soft[(a, kind)] = result["soft"][a]
        pis[kind] = result["pi"]

    def log_prior(key, classes_present):
        item = items[key]
        if item["kind"] == "lemma":
            m = len(classes_present)
            k = max(p["lemma_k"], m + 1)
            return [(c, math.log(1 / k)) for c in classes_present] + [(OTHER, math.log((k - m) / k))], k
        pi = pis[item["kind"]].get(item["stratum"]) if p["class_prior"] == "estimated" else None
        classes = BINARY_CLASSES[item["kind"]]
        return [(c, math.log(pi[c] if pi else 0.5)) for c in classes], 2

    def weighted(rows, key, k):
        kind = items[key]["kind"]
        return [(j.annotator, j.cls, weight(thetas[(j.annotator, kind)], k)) for j in rows if j.cls is not None]

    # (f) posteriors, calibration, states.
    tier_lookup = {}
    for (annotator, kind), tier in tiers.items():
        tier_lookup.setdefault(kind, {})[annotator] = tier
    item_view = {}
    for key in item_keys:
        item = items[key]
        kind = item["kind"]
        definite = [j for j in votes[key] if j.cls is not None]
        crowd = [j for j in definite if j.annotator not in anchors]
        present = sorted({j.cls for j in definite}) if kind == "lemma" else None
        prior, k = log_prior(key, present or [])
        crowd_present = sorted({j.cls for j in crowd}) if kind == "lemma" else None
        crowd_prior, crowd_k = log_prior(key, crowd_present or [])
        item_view[key] = {"definite": definite, "crowd": crowd, "prior": prior, "k": k,
                          "crowd_prior": crowd_prior, "crowd_k": crowd_k}

    def crowd_rule(key):
        v = item_view[key]
        pc = corpus_params(p, key[0])
        return model_rule(v["crowd_prior"], weighted(v["crowd"], key, v["crowd_k"]), v["crowd_k"],
                          tier_lookup.get(items[key]["kind"], {}), pc)

    key_now = calibration_key(p)
    calibration, draw_sets = {}, {}
    for kind in KINDS:
        for cell in CELLS[kind]:
            population = []
            for key in item_keys:
                if items[key]["kind"] != kind or not items[key]["audit_sample"]:
                    continue
                met, winner, _ = crowd_rule(key)
                if met and cell_of(items[key], winner) == cell:
                    population.append(key)
            drawn = None
            for event in draws:
                d = event["details"]
                if (d["kind"], d["cell"], d["calibration_key"]) == (kind, cell, key_now) and \
                        event["id"] > redraws.get((kind, cell), 0):
                    drawn = event
            if drawn is not None:
                members = [tuple(x) for x in drawn["details"]["items"]]
                drawn_at, draw_population = drawn["id"], drawn["details"].get("population")
            elif len(population) >= p["calibration_n"]:
                ranked = sorted(population, key=lambda key: (items[key]["audit_rank"], key))
                members = ranked[:p["calibration_n"]]
                drawn_at, draw_population = None, len(population)
                decided.append({"kind": "calibration.drawn", "annotator_id": None, "corpus_id": None, "item_id": None,
                                "details": {"kind": kind, "cell": cell, "calibration_key": key_now,
                                            "items": [list(m) for m in members], "population": len(population)}})
            else:
                members, drawn_at, draw_population = [], None, None
            correct, pending, outcomes = 0, [], {}
            for member in members:
                met, winner, _ = crowd_rule(member) if member in items else (False, None, None)
                answers = []
                for annotator in sorted(references.get(member, {})):
                    rows = references[member][annotator]
                    first = next((j for j in rows if j.cls is not None), None)
                    answers.append(first.cls if first else None)
                if not answers:
                    pending.append(list(member))
                    outcomes[member] = "pending"
                    continue
                ok = met and None not in answers and len(set(answers)) == 1 and answers[0] == winner
                correct += ok
                outcomes[member] = "success" if ok else "failure"
            n = len(members)
            wilson = wilson_lower_bound(correct, n)
            passed = (n == p["calibration_n"] and n > 0 and correct / n >= p["resolve_confidence"]
                      and wilson >= p["calibration_lb"])
            calibration[f"{kind}/{cell}"] = {
                "kind": kind, "cell": cell, "calibration_key": key_now, "drawn_seq": drawn_at,
                "n": n, "correct": correct, "wilson_lb": wilson, "passed": passed,
                "population": len(population), "draw_population": draw_population,
                "items": [list(m) for m in members], "pending": pending,
                "missing": max(0, p["calibration_n"] - len(population)) if not members else 0}
            draw_sets[(kind, cell)] = outcomes

    posteriors, item_states, vote_rows = [], [], {}
    resolved_class = {}
    multi_anchor = n_anchors >= 2
    for key in item_keys:
        item = items[key]
        kind = item["kind"]
        pc = corpus_params(p, key[0])
        v = item_view[key]
        tiers_k = tier_lookup.get(kind, {})
        weighted_all = weighted(v["definite"], key, v["k"])
        sums = {}
        for annotator, cls, w in weighted_all:
            sums[cls] = sums.get(cls, 0.0) + w
        probs = posterior(v["prior"], sums) if weighted_all else None
        winner = top(probs) if probs else None
        met, _, _ = model_rule(v["prior"], weighted_all, v["k"], tiers_k, pc)
        g = gold.get(key)
        gold_valid = g is not None and g.valid
        decision = curator.get(key)
        epoch = reopens[key][-1][0] if reopens.get(key) else 0
        n_low, n_expert = counts[key]["low"], counts[key]["expert"]
        source, answer_cls, releasable = None, None, False
        cell = cell_of(item, winner)
        if decision and decision[0] == "ambiguous":
            state = "ambiguous"
        elif decision and decision[0] == "adjudicated":
            state, source = "resolved", "adjudication"
            details = decision[1]["details"]
            answer_cls = answer_class(kind, details["answer"], details.get("lemma", ""))
            releasable = True
        else:
            state = None
            epoch_anchor = {}
            for j in v["definite"]:
                if j.annotator in anchors:
                    epoch_anchor[j.annotator] = j.cls
            if multi_anchor and len(set(epoch_anchor.values())) > 1:
                state = "contested"
            if state is None and (item["audit_sample"] or item["review_sample"]):
                crowd_met, crowd_winner, _ = crowd_rule(key)
                checks = {}
                for annotator in sorted(anchors):
                    rows = [j for j in by_pair.get((annotator, key), ()) if j.seq > epoch or not epoch]
                    latest = next((j for j in reversed(rows) if j.cls is not None), None)
                    if latest is not None:
                        checks[annotator] = latest.cls
                if crowd_met and checks:
                    answers = set(checks.values())
                    if multi_anchor and (len(answers) > 1 or crowd_winner not in answers):
                        state = "contested"
                    else:
                        state = "resolved"
                        source = "reference" if item["audit_sample"] else "review"
                        answer_cls = sorted(answers)[0] if len(answers) == 1 else None
                        crowd_votes = weighted(v["crowd"], key, v["crowd_k"])
                        releasable = release_rule(v["crowd_prior"], crowd_votes, v["crowd_k"], tiers_k, pc)
            if state is None and met:
                calibrated = calibration.get(f"{kind}/{cell}", {}).get("passed", False)
                state, source = ("resolved", "model") if calibrated else ("provisional", None)
                answer_cls = winner
                # The release rule is about the crowd: an anchor's vote never makes a row public.
                releasable = release_rule(v["crowd_prior"], weighted(v["crowd"], key, v["crowd_k"]), v["crowd_k"],
                                          tiers_k, pc)
            if state is None and not gold_valid and n_low >= pc["votes_low_cap"] and n_expert >= pc["votes_expert_cap"]:
                state = "contested"
            if state is None and not gold_valid and n_low >= pc["votes_low_cap"]:
                state = "needs_expert"
            if state is None:
                state = "open"
        if state == "resolved":
            resolved_class[key] = answer_cls
        if probs:
            ordered = sorted(probs.values(), reverse=True)
            priority = 1 - (ordered[0] - (ordered[1] if len(ordered) > 1 else 0.0))
        else:
            priority = 1.0
        if state in ("resolved", "provisional") and source != "adjudication" and not releasable:
            priority = 0.05
        confidence = probs[winner] if probs else None
        answer, lemma = class_answer(kind, answer_cls) if answer_cls is not None else (None, None)
        item_states.append({"corpus_id": key[0], "item_id": key[1], "state": state, "confidence": confidence,
                            "n_low": n_low, "n_expert": n_expert, "priority": priority, "releasable": releasable})
        counted_all = votes[key]
        if counted_all or decision:
            classes = []
            for cls in (probs or {}):
                answer_c, lemma_c = class_answer(kind, cls)
                classes.append({"answer": answer_c, "lemma": lemma_c, "prob": probs[cls], "weight": sums.get(cls, 0.0),
                                "votes": sum(j.cls == cls for j in v["definite"]),
                                "anchor_votes": sum(j.cls == cls and j.annotator in anchors for j in v["definite"]),
                                "established_votes": sum(j.cls == cls and tiers_k.get(j.annotator) == "established"
                                                         for j in v["definite"])})
            classes.sort(key=lambda c: (-c["prob"], c["answer"], c["lemma"]))
            posteriors.append({
                "corpus_id": key[0], "item_id": key[1], "kind": kind, "cell": cell, "classes": classes,
                "confidence": confidence, "state": state, "releasable": releasable, "resolution_source": source,
                "resolved_answer": answer if state == "resolved" else None,
                "resolved_lemma": lemma if state == "resolved" else None, "epoch": epoch,
                "n_definite": len(v["definite"]), "n_low": n_low, "n_expert": n_expert,
                "n_unsure": sum(j.cls is None for j in counted_all), "n_annotators": len(counted_all),
                "n_anchor_votes": sum(j.annotator in anchors for j in v["definite"]),
                "n_established_votes": sum(tiers_k.get(j.annotator) == "established" for j in v["definite"]),
                "irregular_votes": sum(bool(j.irregular) for j in v["definite"]),
                "gold_status": gold_status(g)})
            vote_rows[f"{key[0]}/{key[1]}"] = {
                "k": v["k"], "prior": [[cls, value] for cls, value in v["prior"]],
                "votes": [{"annotator_id": j.annotator, "tier": tiers_k.get(j.annotator), "class": j.cls,
                           "theta": thetas[(j.annotator, kind)],
                           "weight": weight(thetas[(j.annotator, kind)], v["k"]) if j.cls is not None else 0.0,
                           "answer": j.answer, "lemma": j.lemma, "irregular": bool(j.irregular),
                           "presentation": j.presentation, "admitted": j.admitted} for j in counted_all]}

    # Agreement with resolved items (score rows, the reported `disagree` flag).
    agreement = defaultdict(lambda: [0, 0])
    for key, cls in resolved_class.items():
        if cls is None:
            continue
        for j in item_view[key]["definite"]:
            counter = agreement[(j.annotator, items[key]["kind"])]
            counter[1] += 1
            counter[0] += j.cls == cls

    # (g) decisions for the next run: gold contests, consensus gold, tier memory.
    for key in sorted(gold):
        g = gold[key]
        if not g.valid:
            continue
        excluded = supporters(g)
        tiers_k = tier_lookup.get(g.kind, {})
        experts = [j for j in item_view[key]["definite"]
                   if tiers_k.get(j.annotator) in ("established", "anchor") and j.annotator not in excluded]
        if len(experts) < p["gold_contest_min_votes"]:
            continue
        if g.reactivated_seq and not any(j.seq > g.reactivated_seq for j in experts):
            continue
        present = sorted({j.cls for j in experts}) if g.kind == "lemma" else []
        prior, k = log_prior(key, present)
        sums = {}
        for annotator, cls, w in weighted(experts, key, k):
            sums[cls] = sums.get(cls, 0.0) + w
        probs = posterior(prior, sums)
        winner = top(probs)
        if winner != g.cls and probs[winner] >= p["gold_contest_confidence"]:
            decided.append({"kind": "gold.contested", "annotator_id": None, "corpus_id": key[0], "item_id": key[1],
                            "details": {"reason": "reviewers", "votes": len(experts)}})

    consensus = p["anchor_consensus_votes"] or (1 if n_anchors <= 1 else 2)
    candidates = []
    for key in item_keys:
        item = items[key]
        if key in gold_events or item["audit_sample"] or item["review_sample"]:
            continue
        answers = {}
        for annotator in by_item.get(key, ()):
            if annotator in anchors and eligible(annotator):
                latest = latest_definite(annotator, key)
                if latest is not None:
                    answers[annotator] = latest
        if len(answers) < consensus or len({j.cls for j in answers.values()}) != 1:
            continue
        cls = next(iter(answers.values())).cls
        tiers_k = tier_lookup.get(item["kind"], {})
        if any(j.cls != cls and tiers_k.get(j.annotator) == "established" for j in item_view[key]["definite"]):
            continue
        agrees = None if item["kind"] == "stem" else cls == suggested_class(item)
        if agrees:
            continue  # hr500k already supplies gold that agrees with the suggestion
        formed = max(j.seq for j in answers.values())
        candidates.append((formed, key, cls, agrees, sorted(answers.items())))
    targets = p["readiness"]
    for formed, key, cls, agrees, support in sorted(candidates):
        kind = items[key]["kind"]
        pools = pools_of(kind)
        for event in decided:
            if event["kind"] == "gold.set" and items[(event["corpus_id"], event["item_id"])]["kind"] == kind:
                d = event["details"]
                bucket = d["answer"] if kind == "stem" else "all"
                pools[d["pool"]][bucket] = pools[d["pool"]].get(bucket, 0) + 1
                if d["pool"] == "audit" and d["suggestion_agrees"] is False:
                    pools["wrong"] += 1
        pool = None
        if kind == "stem":
            # Qualification first, then audit; each pool fills with both classes at their
            # minimum share: an item of the over-represented class waits as a candidate.
            for name, target in (("qualification", targets["stem_qualification_pool"]),
                                 ("audit", targets["stem_audit_pool"])):
                have = pools[name]
                if sum(have.values()) >= target:
                    continue
                if have.get(cls, 0) + 1 <= target - math.ceil(targets["minority_class_share"] * target):
                    pool = name
                break
        elif pools["wrong"] < targets["wrong_suggestion_pool"]:
            pool = "audit"
        if pool is None:
            continue
        answer, lemma = class_answer(kind, cls)
        decided.append({"kind": "gold.set", "annotator_id": None, "corpus_id": key[0], "item_id": key[1],
                        "details": {"pool": pool, "answer": answer, "lemma": lemma, "source": "anchor_consensus",
                                    "basis": "anchor_consensus", "batch": None, "suggestion_agrees": agrees,
                                    "support": {"annotators": [a for a, _ in support],
                                                "judgments": [j.id for _, j in support]}}})

    scores = []
    for annotator in subjects:
        for kind in KINDS:
            if (annotator, kind) not in evidence or not per_annotator.get((annotator, kind)):
                continue
            e = evidence[(annotator, kind)]
            alpha0, beta0 = prior_of(annotator)
            theta = thetas[(annotator, kind)]
            counted = eligible(annotator)
            agree, total = agreement[(annotator, kind)]
            signals = flags.get((annotator, kind), {})
            signals["disagree"] = {"on": total >= 40 and agree / total < 0.5, "agreement": agree / total if total else None,
                                   "n": total}
            definite_n, unsure_n = latest_by_kind[(annotator, kind)]
            scores.append({
                "annotator_id": annotator, "kind": kind, "tier": tiers[(annotator, kind)],
                "base_tier": base_tiers[(annotator, kind)], "qualified": e["qualified"],
                "alpha0": alpha0, "beta0": beta0, "gold_seen": e["gold_seen"], "gold_hits": e["gold_hits"],
                "disc_seen": e["disc_seen"], "disc_hits": e["disc_hits"],
                "wrong_sugg_seen": e["wrong_seen"], "wrong_sugg_hits": e["wrong_hits"],
                "soft_hits": soft[(annotator, kind)][0], "soft_misses": soft[(annotator, kind)][1],
                "theta_mean": theta, "theta_lb_gold": theta_lower_bound(alpha0, beta0, e["disc_hits"], e["disc_seen"]),
                "weight": weight(theta, 2) if counted else 0.0,
                "flags": {"blocked": final_status(annotator) == "blocked", "counted": counted,
                          "qualification_done": e["qualification_done"], **signals},
                "n_definite": definite_n, "n_unsure": unsure_n,
                "n_resolved_agree": agree, "n_resolved_total": total})
            if base_tiers[(annotator, kind)] != memory.get((annotator, kind), "new"):
                decided.append({"kind": "tier.changed", "annotator_id": annotator, "corpus_id": None, "item_id": None,
                                "details": {"kind": kind, "from": memory.get((annotator, kind), "new"),
                                            "to": base_tiers[(annotator, kind)]}})

    outputs = {"scores": scores, "posteriors": posteriors, "item_states": item_states, "votes": vote_rows,
               "events": decided, "status_changes": status_changes, "calibration": calibration,
               "readiness": ready,
               "counts": {"n_judgments": len(judgments), "n_items": len(items),
                          "n_annotators": len({s["annotator_id"] for s in scores})}}
    return rounded(outputs)


def _median(values):
    n = len(values)
    if not n:
        return None
    middle = n // 2
    return values[middle] if n % 2 else (values[middle - 1] + values[middle]) / 2


def rounded(value):
    """Floats rounded at the boundary, so hashes do not depend on the last bits."""
    if isinstance(value, float):
        return round(value, ROUND)
    if isinstance(value, dict):
        return {k: rounded(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded(v) for v in value]
    return value


def fit(kind, work, people, p):
    """EM for one kind (4.4.3 steps 3-6), a fixed number of passes.

    work: [(key, stratum, [(annotator, cls)], is_gold)] in item order, the counted definite
    votes of each item; people: {annotator: (alpha0, beta0, hits, misses, ceiling, counted)}.
    Returns {"theta": {a: θ}, "soft": {a: (soft_hits, soft_misses)}, "pi": {stratum: {class: π}}}."""
    order = sorted(people)
    theta = {}
    for a in order:
        alpha0, beta0, h, m, ceiling, _ = people[a]
        theta[a] = clip((alpha0 + h) / (alpha0 + beta0 + h + m), ceiling)
    strata = sorted({stratum for _, stratum, _, is_gold in work if not is_gold})
    classes = BINARY_CLASSES.get(kind)
    pi = {stratum: {c: 0.5 for c in classes} for stratum in strata} if classes else {}
    soft = {a: (0.0, 0.0) for a in order}

    def item_prior(stratum, present):
        if kind == "lemma":
            m = len(present)
            k = max(p["lemma_k"], m + 1)
            return [(c, math.log(1 / k)) for c in present] + [(OTHER, math.log((k - m) / k))], k
        prior = pi.get(stratum) if p["class_prior"] == "estimated" else None
        return [(c, math.log(prior[c] if prior else 0.5)) for c in classes], 2

    for _ in range(p["iterations"]):
        s = {a: 0.0 for a in order}
        u = {a: 0.0 for a in order}
        q_sum = {stratum: {c: 0.0 for c in classes} for stratum in strata} if classes else {}
        q_n = {stratum: 0 for stratum in strata}
        for key, stratum, definite, is_gold in work:
            if is_gold:
                continue  # gold is hard evidence; its votes add no soft counts
            present = sorted({cls for _, cls in definite}) if kind == "lemma" else []
            prior, k = item_prior(stratum, present)
            weights = [(a, cls, weight(theta[a], k) if people[a][5] else 0.0) for a, cls in definite]
            sums = {}
            for a, cls, w in weights:
                sums[cls] = sums.get(cls, 0.0) + w
            if classes:
                q = posterior(prior, sums)
                for c in classes:
                    q_sum[stratum][c] += q[c]
                q_n[stratum] += 1
            if len(weights) < 2:
                continue
            for index, (a, cls, w) in enumerate(weights):
                info, other_sums = 0.0, {}
                for position, (_, c, wo) in enumerate(weights):
                    if position != index:
                        info += wo
                        other_sums[c] = other_sums.get(c, 0.0) + wo
                if info < p["soft_min_info"]:
                    continue  # the other votes carry no information about this one
                q_loo = posterior(prior, other_sums)[cls]
                s[a] += p["soft_weight"] * q_loo
                u[a] += p["soft_weight"] * (1 - q_loo)
        for a in order:
            alpha0, beta0, h, m, ceiling, _ = people[a]
            limit = p["peer_cap_ratio"] * max(h + m, p["peer_cap_floor"])
            if s[a] + u[a] > limit:  # peer evidence never outweighs gold by more than the ratio
                scale = limit / (s[a] + u[a])
                s[a], u[a] = s[a] * scale, u[a] * scale
            theta[a] = clip((alpha0 + h + s[a]) / (alpha0 + beta0 + h + m + s[a] + u[a]), ceiling)
            soft[a] = (s[a], u[a])
        if classes and p["class_prior"] == "estimated":
            pi = {stratum: {c: (q_sum[stratum][c] + 1) / (q_n[stratum] + 2) for c in classes} for stratum in strata}
    return {"theta": theta, "soft": soft, "pi": pi}


def replay(bundle) -> dict:
    """Recompute a run from its restricted bundle alone (no database, no audit key).

    A later privacy action (erasure re-keying, the timing retention, a redaction) changes
    a past run's inputs; the report then names the journals that changed instead of
    claiming an output mismatch."""
    run, inputs = bundle["run"], bundle["inputs"]
    summary = inputs_summary(inputs)
    report = {"run_id": run["id"], "inputs_sha256": inputs_sha256(inputs, summary)}
    report["inputs_match"] = report["inputs_sha256"] == run["inputs_sha256"]
    if not report["inputs_match"]:
        report["changed"] = changed_journals(run["inputs_summary"], summary) if run.get("inputs_summary") else None
    outputs = score(inputs, validate_params(run["params"]))
    report["outputs_sha256"] = sha256(outputs)
    report["outputs_match"] = report["outputs_sha256"] == run["outputs_sha256"] if report["inputs_match"] else None
    return {"report": report, "outputs": outputs}


def krippendorff_alpha(units):
    """Krippendorff's alpha for nominal data. units: one list of values per item (only items
    with at least two values are pairable). None when there is no disagreement to expect."""
    coincidence = defaultdict(float)
    for values in units:
        m = len(values)
        if m < 2:
            continue
        counts = defaultdict(int)
        for value in values:
            counts[value] += 1
        for c in sorted(counts):
            for k in sorted(counts):
                coincidence[(c, k)] += counts[c] * (counts[k] - (c == k)) / (m - 1)
    totals = defaultdict(float)
    for (c, _), value in sorted(coincidence.items()):
        totals[c] += value
    n = sum(totals.values())
    if n <= 1:
        return None
    observed = sum(value for (c, k), value in coincidence.items() if c != k)
    expected = sum(totals[c] * totals[k] for c in totals for k in totals if c != k) / (n - 1)
    return None if expected == 0 else 1 - observed / expected


def observed_agreement(units):
    """The share of items with at least two definite answers on which all agree."""
    multi = [values for values in units if len(values) >= 2]
    return sum(len(set(values)) == 1 for values in multi) / len(multi) if multi else None

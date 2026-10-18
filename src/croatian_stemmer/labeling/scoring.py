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

SCORING_VERSION = "2.0"

DEFAULT_PARAMS = {
    "version": "2.0", "iterations": 10, "prior": [4, 2], "prior_anchor": [18, 2],
    "theta_max": {"new": 0.75, "qualified": 0.80, "established": 0.95, "anchor": 0.98}, "theta_min": 0.5,
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

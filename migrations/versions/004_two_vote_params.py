"""Scoring parameters 0.3.1: two votes that carry evidence resolve an item.

0.3.1 changes two defaults: the `new` tier's ceiling 0.75 -> 0.78, so an established and
a new annotator agreeing can meet the 0.95 rule; and the new `resolve_vote_min_theta`
(0.70): only votes for the winning answer whose author's theta is at least 0.70 count
towards the two votes, so neither the class prior nor a worthless second vote stands in
for one. Migration 003 stored the 0.3.0 defaults in label_setting, and 0.3.1 refuses a
parameter set without the new key, so this migration touches every stored set:

- the stored value equals the 0.3.0 defaults exactly and no person ever wrote a
  `params.changed` event (only this migration's own): it becomes the 0.3.1 defaults;
- any other value without the new key (parameters a curator chose): only
  `resolve_vote_min_theta` = 0.70 is added (the owner decided to close the gap the
  0.3.0 rule left); every chosen value stays;
- a value that has the key already (a database created by 0.3.1): nothing.

Each change appends the `params.changed` event PUT /api/admin/scoring/params appends
(actor NULL: the system), so it is in the journal and the next run draws new
calibration sets for the new policy. Both parameter sets are frozen here (not
imported), so the migration means the same thing whatever later versions do to
DEFAULT_PARAMS. No schema change.

downgrade() (run with the 0.3.1 image before rolling back to 0.3.0, whose init
container does not know this revision and whose validation refuses the new key):
when the latest `params.changed` event is this migration's move and the value still
equals the 0.3.1 defaults, the 0.3.0 defaults come back; otherwise only the new key is
removed. Either way with the reverse event.
"""
import hashlib
import json

from alembic import op
from sqlalchemy import text

revision = "004_two_vote_params"
down_revision = "003_trust"
branch_labels = None
depends_on = None

MODERATION_LOCK = 7266002

# validate_params(DEFAULT_PARAMS) of 0.3.0, as migration 003 stored it.
DEFAULTS_0_3_0 = json.loads("""{"anchor_consensus_votes": null, "audit_sample_rate": 10, "blind_rate": 20,
"calibration_lb": 0.8, "calibration_n": 30, "class_prior": "estimated", "corpora": {}, "established_disc_gold": 30,
"established_keep_theta_lb": 0.7, "established_theta_lb": 0.75, "established_votes": 100,
"established_wrong_sugg_gold": 5, "established_wrong_sugg_min_acc": 0.6, "flags": {"audit_max_loss": 0.3,
"audit_min": 10, "burst_count": 400, "burst_window_min": 60, "copy_other_min_acc": 0.9, "copy_wrong_max_acc": 0.4,
"copy_wrong_min": 5, "fast_anchor_ratio": 0.25, "fast_floor_ms": 1000, "fast_window": 30, "gold_min_accuracy": 0.6,
"gold_min_seen": 12, "gold_window": 20, "signup_burst_count": 5, "signup_burst_window_min": 10, "straight_run": 12,
"unsure_max_rate": 0.6, "unsure_window": 50}, "gold_contest_confidence": 0.95, "gold_contest_min_votes": 3,
"gold_delay_days": 1, "gold_max_serves": 150, "gold_pool_warn": 150, "gold_rate": {"anchor": 0, "established": 5,
"new": 10, "qualified": 10, "quarantined": 10}, "iterations": 10, "lemma_k": 3, "peer_cap_floor": 12,
"peer_cap_ratio": 1.0, "prior": [4.0, 2.0], "prior_anchor": [18.0, 2.0], "qualification_hits": 9,
"qualification_n": 12, "quarantine_review_days": 14, "readiness": {"anchors": 1, "audit_pool": 100,
"minority_class_share": 0.25, "qualification_pool": 60, "stem_audit_pool": 30, "stem_qualification_pool": 16,
"wrong_suggestion_pool": 15}, "release_min_voters": 3, "resolve_confidence": 0.95, "resolve_min_votes": 2,
"review_sample_rate": 2, "soft_min_info": 1.0, "soft_weight": 0.5, "theta_max": {"anchor": 0.98,
"established": 0.95, "new": 0.75, "qualified": 0.8}, "theta_min": 0.5, "version": "2.0", "votes_expert_cap": 3,
"votes_low_cap": 5, "wrong_suggestion_pick": 0.25}""")
DEFAULTS_0_3_1 = {**DEFAULTS_0_3_0, "theta_max": {**DEFAULTS_0_3_0["theta_max"], "new": 0.78},
                  "resolve_vote_min_theta": 0.70}
FLOOR = "resolve_vote_min_theta"
CHANGED = ["resolve_vote_min_theta", "theta_max.new"]  # the curator UI's sorted dotted paths


def params_sha256(params):
    """scoring.params_sha256: sha256 of the canonical JSON."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


UPGRADE_REASON = "migration 004: 0.3.1 default parameters"
FLOOR_REASON = "migration 004: resolve_vote_min_theta added"
DOWNGRADE_REASON = "migration 004 downgrade: 0.3.0 default parameters"
DOWNGRADE_FLOOR_REASON = "migration 004 downgrade: resolve_vote_min_theta removed"
REASONS = (UPGRADE_REASON, FLOOR_REASON, DOWNGRADE_REASON, DOWNGRADE_FLOOR_REASON)


def _write(bind, old, new, diff, reason):
    """Store `new` in place of `old` and append the event the curator UI appends."""
    bind.execute(text("UPDATE label_setting SET value = CAST(:new AS jsonb), updated_at = now(), updated_by = NULL "
                      "WHERE key = 'scoring_params'"), {"new": json.dumps(new)})
    details = {"old_sha256": params_sha256(old), "new_sha256": params_sha256(new), "diff": diff, "reason": reason}
    bind.execute(text("INSERT INTO label_trust_event (kind, details) VALUES ('params.changed', CAST(:d AS jsonb))"),
                 {"d": json.dumps(details)})


def _stored(bind):
    # As every moderation writer does: the shared moderation lock first (4.6.5), then the row.
    bind.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": MODERATION_LOCK})
    value = bind.execute(text("SELECT value FROM label_setting WHERE key = 'scoring_params' FOR UPDATE")).scalar()
    return json.loads(value) if isinstance(value, str) else value


def upgrade():
    bind = op.get_bind()
    stored = _stored(bind)
    if stored is None or FLOOR in stored:
        return
    # Any params.changed event not written by this migration is a person's choice.
    chosen = bind.execute(text("SELECT EXISTS (SELECT 1 FROM label_trust_event WHERE kind = 'params.changed' "
                               "AND NOT coalesce(details ->> 'reason' = ANY(:reasons), false))"),
                          {"reasons": list(REASONS)}).scalar_one()
    if stored == DEFAULTS_0_3_0 and not chosen:
        _write(bind, stored, DEFAULTS_0_3_1, CHANGED, UPGRADE_REASON)
    else:
        _write(bind, stored, {**stored, FLOOR: DEFAULTS_0_3_1[FLOOR]}, [FLOOR], FLOOR_REASON)


def downgrade():
    bind = op.get_bind()
    stored = _stored(bind)
    if stored is None or FLOOR not in stored:
        return
    latest = bind.execute(text("SELECT details ->> 'reason' FROM label_trust_event WHERE kind = 'params.changed' "
                               "ORDER BY id DESC LIMIT 1")).scalar_one_or_none()
    if latest == UPGRADE_REASON and stored == DEFAULTS_0_3_1:
        _write(bind, stored, DEFAULTS_0_3_0, CHANGED, DOWNGRADE_REASON)
    else:
        _write(bind, stored, {k: v for k, v in stored.items() if k != FLOOR}, [FLOOR], DOWNGRADE_FLOOR_REASON)

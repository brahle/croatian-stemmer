"""Scoring parameters 0.3.1: the `new` tier's ceiling 0.75 -> 0.78 (two-vote resolution).

Migration 003 stored the 0.3.0 default parameters in label_setting. This migration
moves a database to the 0.3.1 defaults only when nobody has chosen its parameters:
the stored value equals the 0.3.0 defaults exactly and no `params.changed` event
exists other than this migration's own (so a downgrade and a second upgrade
round-trip). Then it writes the 0.3.1 defaults and appends the same `params.changed`
event the curator's PUT /api/admin/scoring/params appends (actor NULL: the system),
so the change is in the journal and the next run draws a new calibration set for the
new policy. Any other value is the curator's choice and is left alone
(GET /api/admin/scoring/params returns the new defaults next to the live value).

Both parameter sets are frozen here (not imported), so the migration means the same
thing whatever later versions do to DEFAULT_PARAMS. No schema change.

downgrade() (run with the 0.3.1 image before rolling back to 0.3.0, whose init
container does not know this revision) undoes only its own change: when the latest
`params.changed` event is this migration's and the stored value still equals the
0.3.1 defaults, it writes the 0.3.0 defaults back and appends the reverse event.
Otherwise the parameters stay as they are (every 0.3.1 value is valid in 0.3.0).
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
DEFAULTS_0_3_1 = {**DEFAULTS_0_3_0, "theta_max": {**DEFAULTS_0_3_0["theta_max"], "new": 0.78}}
CHANGED = ["theta_max.new"]


def params_sha256(params):
    """scoring.params_sha256: sha256 of the canonical JSON."""
    canonical = json.dumps(params, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


UPGRADE_REASON = "migration 004: 0.3.1 default parameters"
DOWNGRADE_REASON = "migration 004 downgrade: 0.3.0 default parameters"


def _replace(bind, old, new, reason):
    """Swap the stored parameters from `old` to `new` (only if they are exactly `old`) and
    append the event PUT /api/admin/scoring/params appends. True when it changed them."""
    updated = bind.execute(text(
        "UPDATE label_setting SET value = CAST(:new AS jsonb), updated_at = now(), updated_by = NULL "
        "WHERE key = 'scoring_params' AND value = CAST(:old AS jsonb) RETURNING key"),
        {"new": json.dumps(new), "old": json.dumps(old)}).all()
    if updated:
        details = {"old_sha256": params_sha256(old), "new_sha256": params_sha256(new), "diff": CHANGED,
                   "reason": reason}
        bind.execute(text("INSERT INTO label_trust_event (kind, details) VALUES ('params.changed', CAST(:d AS jsonb))"),
                     {"d": json.dumps(details)})
    return bool(updated)


def _lock(bind):
    # As every moderation writer does: the shared moderation lock first (4.6.5).
    bind.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": MODERATION_LOCK})


def upgrade():
    bind = op.get_bind()
    _lock(bind)
    # Any params.changed event not written by this migration is a person's choice.
    chosen = bind.execute(text("SELECT EXISTS (SELECT 1 FROM label_trust_event WHERE kind = 'params.changed' "
                               "AND (details ->> 'reason') IS DISTINCT FROM :up "
                               "AND (details ->> 'reason') IS DISTINCT FROM :down)"),
                          {"up": UPGRADE_REASON, "down": DOWNGRADE_REASON}).scalar_one()
    if not chosen:
        _replace(bind, DEFAULTS_0_3_0, DEFAULTS_0_3_1, UPGRADE_REASON)


def downgrade():
    bind = op.get_bind()
    _lock(bind)
    latest = bind.execute(text("SELECT details ->> 'reason' FROM label_trust_event WHERE kind = 'params.changed' "
                               "ORDER BY id DESC LIMIT 1")).scalar_one_or_none()
    if latest == UPGRADE_REASON:
        _replace(bind, DEFAULTS_0_3_1, DEFAULTS_0_3_0, DOWNGRADE_REASON)

"""Trust system (0.3.0): one journal sequence, trust events, gold, scoring runs and their outputs.

Forward-only and not destructive. It adds the sequence and the triggers that stamp
every journal row with it (taking the shared journal lock, and the shared moderation
lock for moderation events, 4.6.3 and 4.6.5), the new tables, nullable columns on
the V1 journals (rows written before 003 keep seq NULL, which counts as 0), the
redaction allowed on an erased person's events, and a backfill: the default scoring
parameters, scoring_enabled = false (deploying 003 scores and profiles nobody), a
new random audit key, and for every existing item its label_item_state row and its
immutable label_item_audit row. Rollback is the previous image plus a restore of
the pre-deploy backup; downgrade() refuses.
"""
import hashlib
import hmac
import json

from alembic import op
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, Date, DateTime, Double, ForeignKey,
                        ForeignKeyConstraint, Integer, String, Text, Uuid, text)
from sqlalchemy.dialects.postgresql import JSONB

from croatian_stemmer.labeling.scoring import DEFAULT_PARAMS, validate_params

revision = "003_trust"
down_revision = "002a_v1_followups"
branch_labels = None
depends_on = None

JOURNAL_LOCK, MODERATION_LOCK = 7266001, 7266002
TRUST_EVENTS = ("trusted.added", "trusted.removed", "anchor.granted", "anchor.revoked",
                "annotator.quarantined", "annotator.cleared", "tier.changed",
                "gold.set", "gold.retired", "gold.reactivated", "gold.contested", "gold.retracted",
                "gold.disclosed", "calibration.drawn", "calibration.redraw_requested",
                "item.adjudicated", "item.ambiguous", "item.reopened",
                "params.changed", "run.pinned", "run.unpinned")
MODERATION_TRUST = ("trusted.added", "trusted.removed", "anchor.granted", "anchor.revoked",
                    "annotator.cleared", "gold.set", "gold.retired", "gold.reactivated",
                    "gold.contested", "gold.retracted", "gold.disclosed", "item.adjudicated",
                    "item.ambiguous", "item.reopened", "params.changed", "calibration.redraw_requested")
STATES = "('open', 'provisional', 'resolved', 'needs_expert', 'contested', 'ambiguous')"


def _in(values):
    return "(" + ", ".join(f"'{v}'" for v in values) + ")"


def keyed(key_hex, message):
    """The first 8 bytes of HMAC-SHA256(audit key, message) as an unsigned integer
    (the same rule as web/scheduler.py keyed())."""
    return int.from_bytes(hmac.new(bytes.fromhex(key_hex), message.encode("utf-8"), hashlib.sha256).digest()[:8], "big")


def item_bits(key_hex, corpus_id, item_id, audit_rate, review_rate):
    audit = keyed(key_hex, f"sample:{corpus_id}:{item_id}") % 100 < audit_rate
    review = not audit and keyed(key_hex, f"review:{corpus_id}:{item_id}") % 100 < review_rate
    return audit, review, keyed(key_hex, f"rank:{corpus_id}:{item_id}") - 2 ** 63


def upgrade():
    bind = op.get_bind()
    op.execute("SET LOCAL lock_timeout = '5s'")
    op.execute("CREATE SEQUENCE label_journal_seq CACHE 1")
    for table in ("label_judgment", "label_consent", "label_admin_event"):
        op.add_column(table, Column("seq", BigInteger, nullable=True))
    op.add_column("label_judgment", Column("admitted", Boolean, nullable=True))
    op.add_column("label_judgment", Column("admission_group", String(8), nullable=True))
    op.add_column("label_judgment", Column("presentation", String(8), nullable=True))
    op.create_check_constraint("label_judgment_admission_group", "label_judgment", "admission_group IN ('low', 'expert')")
    op.create_check_constraint("label_judgment_presentation", "label_judgment", "presentation IN ('shown', 'blind')")
    op.add_column("label_assignment", Column("presentation", String(8), nullable=True))
    op.create_check_constraint("label_assignment_presentation", "label_assignment", "presentation IN ('shown', 'blind')")
    op.create_index("ix_label_assignment_item_lease", "label_assignment", ["corpus_id", "item_id"],
                    postgresql_where=text("current_revision = 0"))

    op.create_table(
        "label_trust_event",
        Column("id", BigInteger, primary_key=True, autoincrement=False),
        Column("at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        Column("actor_id", Uuid, ForeignKey("label_annotator.id"), nullable=True),
        Column("kind", String(32), nullable=False),
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), nullable=True),
        Column("corpus_id", Uuid, nullable=True),
        Column("item_id", Uuid, nullable=True),
        Column("run_id", Uuid, nullable=True),
        Column("details", JSONB, nullable=False),
        CheckConstraint("kind IN " + _in(TRUST_EVENTS), name="label_trust_event_kind"))
    op.create_index("ix_label_trust_event_annotator", "label_trust_event", ["annotator_id", "id"])
    op.create_index("ix_label_trust_event_item", "label_trust_event", ["corpus_id", "item_id", "id"])
    op.create_index("ix_label_trust_event_kind", "label_trust_event", ["kind", "id"])
    op.create_table(
        "label_trusted_email",
        Column("id", BigInteger, primary_key=True),
        Column("email", String(320), nullable=True),
        Column("email_sha256", String(64), nullable=True),
        Column("label", String(100), nullable=True),
        Column("added_by", Uuid, ForeignKey("label_annotator.id"), nullable=False),
        Column("added_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        Column("removed_at", DateTime(timezone=True), nullable=True),
        CheckConstraint("(removed_at IS NULL) = (email IS NOT NULL AND email_sha256 IS NOT NULL AND label IS NOT NULL)",
                        name="label_trusted_email_identity"))
    op.create_index("ux_label_trusted_email_active", "label_trusted_email", ["email_sha256"], unique=True,
                    postgresql_where=text("removed_at IS NULL"))
    op.create_table(
        "label_anchor",
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), primary_key=True),
        Column("trusted_id", BigInteger, ForeignKey("label_trusted_email.id"), nullable=False),
        Column("granted_event_id", BigInteger, nullable=False))
    op.create_table(
        "label_gold",
        Column("corpus_id", Uuid, primary_key=True),
        Column("item_id", Uuid, primary_key=True),
        Column("kind", String(16), nullable=False),
        Column("pool", String(16), nullable=False),
        Column("answer", String(16), nullable=False),
        Column("lemma", String(128), nullable=False, server_default=""),
        Column("source", String(16), nullable=False),
        Column("suggestion_agrees", Boolean, nullable=True),
        Column("status", String(16), nullable=False),
        Column("served_count", Integer, nullable=False, server_default="0"),
        Column("last_event_id", BigInteger, nullable=False),
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint("pool IN ('qualification', 'audit')", name="label_gold_pool"),
        CheckConstraint("answer IN ('same', 'different', 'confirmed', 'accept', 'reject')", name="label_gold_answer"),
        CheckConstraint("source IN ('hr500k', 'curator', 'anchor_consensus')", name="label_gold_source"),
        CheckConstraint("status IN ('active', 'retired', 'contested', 'retracted')", name="label_gold_status"))
    op.create_index("ix_label_gold_pool", "label_gold", ["kind", "pool", "status"])
    op.create_table(
        "label_scoring_run",
        Column("id", Uuid, primary_key=True),
        Column("scoring_version", String(16), nullable=False),
        Column("params", JSONB, nullable=False),
        Column("params_sha256", String(64), nullable=False),
        Column("watermark", BigInteger, nullable=False),
        Column("as_of_day", Date, nullable=False),
        Column("previous_run_id", Uuid, ForeignKey("label_scoring_run.id"), nullable=True),
        Column("started_at", DateTime(timezone=True), nullable=True),
        Column("finished_at", DateTime(timezone=True), nullable=True),
        Column("status", String(16), nullable=False),
        Column("triggered_by", Uuid, ForeignKey("label_annotator.id"), nullable=True),
        Column("n_judgments", Integer, nullable=True),
        Column("n_items", Integer, nullable=True),
        Column("n_annotators", Integer, nullable=True),
        Column("inputs_sha256", String(64), nullable=True),
        Column("outputs_sha256", String(64), nullable=True),
        Column("calibration", JSONB, nullable=True),
        Column("readiness", JSONB, nullable=True),
        Column("pinned", Boolean, nullable=False, server_default=text("false")),
        Column("error", Text, nullable=True),
        CheckConstraint("status IN ('running', 'done', 'failed', 'superseded')", name="label_scoring_run_status"))
    op.create_table(
        "label_annotator_score",
        Column("run_id", Uuid, ForeignKey("label_scoring_run.id", ondelete="CASCADE"), primary_key=True),
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), primary_key=True),
        Column("kind", String(16), primary_key=True),
        Column("tier", String(16), nullable=False),
        Column("base_tier", String(16), nullable=False),
        Column("qualified", Boolean, nullable=False),
        *[Column(name, Double, nullable=False) for name in ("alpha0", "beta0")],
        *[Column(name, Integer, nullable=False) for name in ("gold_seen", "gold_hits", "disc_seen", "disc_hits",
                                                             "wrong_sugg_seen", "wrong_sugg_hits")],
        *[Column(name, Double, nullable=False) for name in ("soft_hits", "soft_misses", "theta_mean",
                                                            "theta_lb_gold", "weight")],
        Column("flags", JSONB, nullable=False),
        *[Column(name, Integer, nullable=False) for name in ("n_definite", "n_unsure", "n_resolved_agree",
                                                             "n_resolved_total")],
        CheckConstraint("tier IN ('new', 'qualified', 'established', 'anchor', 'quarantined')",
                        name="label_annotator_score_tier"))
    op.create_index("ix_label_annotator_score_annotator", "label_annotator_score", ["annotator_id", "run_id"])
    op.create_table(
        "label_item_posterior",
        Column("run_id", Uuid, ForeignKey("label_scoring_run.id", ondelete="CASCADE"), primary_key=True),
        Column("corpus_id", Uuid, primary_key=True),
        Column("item_id", Uuid, primary_key=True),
        Column("kind", String(16), nullable=False),
        Column("cell", String(16), nullable=False),
        Column("classes", JSONB, nullable=False),
        Column("confidence", Double, nullable=True),
        Column("state", String(16), nullable=False),
        Column("releasable", Boolean, nullable=False),
        Column("resolution_source", String(16), nullable=True),
        Column("resolved_answer", String(16), nullable=True),
        Column("resolved_lemma", String(128), nullable=True),
        Column("epoch", BigInteger, nullable=False),
        *[Column(name, Integer, nullable=False) for name in ("n_definite", "n_low", "n_expert", "n_unsure",
                                                             "n_annotators", "n_anchor_votes",
                                                             "n_established_votes", "irregular_votes")],
        Column("gold_status", String(16), nullable=True),
        CheckConstraint("state IN " + STATES, name="label_item_posterior_state"),
        CheckConstraint("resolution_source IN ('model', 'adjudication', 'reference', 'review')",
                        name="label_item_posterior_source"))
    op.create_table(
        "label_item_state",
        Column("corpus_id", Uuid, primary_key=True),
        Column("item_id", Uuid, primary_key=True),
        Column("kind", String(16), nullable=False),
        Column("run_id", Uuid, nullable=True),
        Column("state", String(16), nullable=False, server_default="open"),
        Column("confidence", Double, nullable=True),
        Column("releasable", Boolean, nullable=False, server_default=text("false")),
        Column("n_low", Integer, nullable=False, server_default="0"),
        Column("n_expert", Integer, nullable=False, server_default="0"),
        Column("priority", Double, nullable=False, server_default=text("1.0")),
        Column("epoch", BigInteger, nullable=False, server_default="0"),
        Column("epoch_at", DateTime(timezone=True), nullable=True),
        Column("epoch_discard", Boolean, nullable=False, server_default=text("false")),
        Column("updated_at", DateTime(timezone=True), nullable=False, server_default=text("now()")),
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint("state IN " + STATES, name="label_item_state_state"))
    op.create_index("ix_label_item_state_queue", "label_item_state",
                    ["corpus_id", "kind", "state", text("priority DESC")])
    op.create_table(
        "label_item_audit",
        Column("corpus_id", Uuid, primary_key=True),
        Column("item_id", Uuid, primary_key=True),
        Column("seq", BigInteger, nullable=True),
        Column("audit_sample", Boolean, nullable=False),
        Column("review_sample", Boolean, nullable=False),
        Column("audit_rank", BigInteger, nullable=False),
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint("NOT (audit_sample AND review_sample)", name="label_item_audit_disjoint"))

    # ---- backfill (before the stamping triggers exist, so these rows keep seq NULL = 0) ----
    params = validate_params(DEFAULT_PARAMS)
    bind.execute(text("INSERT INTO label_setting (key, value, updated_at) VALUES "
                      "('scoring_params', CAST(:params AS jsonb), now()), "
                      "('scoring_enabled', 'false'::jsonb, now()), "
                      "('audit_key', to_jsonb(md5(gen_random_uuid()::text) || md5(gen_random_uuid()::text)), now())"),
                 {"params": json.dumps(params)})
    key = bind.execute(text("SELECT value #>> '{}' FROM label_setting WHERE key = 'audit_key'")).scalar_one()
    # Vote counts as V1's definite_votes(): latest answer per annotator, excluded annotators left out.
    bind.execute(text("""
        INSERT INTO label_item_state (corpus_id, item_id, kind, n_low, priority)
        SELECT i.corpus_id, i.id, i.kind, coalesce(v.n, 0), CASE WHEN coalesce(v.n, 0) > 0 THEN 0.5 ELSE 1.0 END
        FROM label_item i LEFT JOIN (
          SELECT corpus_id, item_id, count(*) FILTER (WHERE answer <> 'unsure') AS n FROM (
            SELECT DISTINCT ON (corpus_id, item_id, annotator_id) corpus_id, item_id, annotator_id, answer
            FROM label_judgment
            WHERE annotator_id NOT IN (
              SELECT a.id FROM label_annotator a WHERE a.status = 'blocked' OR (a.status = 'erased' AND (
                SELECT e.details ->> 'to' FROM label_admin_event e
                WHERE e.kind = 'annotator.status' AND e.target = a.id::text ORDER BY e.id DESC LIMIT 1) = 'blocked'))
            ORDER BY corpus_id, item_id, annotator_id, revision DESC) latest
          GROUP BY corpus_id, item_id) v ON v.corpus_id = i.corpus_id AND v.item_id = i.id"""))
    after = None
    while True:
        page = bind.execute(text("SELECT corpus_id, id FROM label_item "
                                 + ("WHERE (corpus_id, id) > (:c, :i) " if after else "")
                                 + "ORDER BY corpus_id, id LIMIT 1000"),
                            {"c": after[0], "i": after[1]} if after else {}).all()
        if not page:
            break
        rows = []
        for corpus_id, item_id in page:
            audit, review, rank = item_bits(key, corpus_id, item_id, params["audit_sample_rate"],
                                            params["review_sample_rate"])
            rows.append({"c": corpus_id, "i": item_id, "a": audit, "r": review, "k": rank})
        bind.execute(text("INSERT INTO label_item_audit (corpus_id, item_id, audit_sample, review_sample, audit_rank) "
                          "VALUES (:c, :i, :a, :r, :k)"), rows)
        after = page[-1]

    # ---- moderation predicate, redaction, journal stamping ----
    op.execute(f"""
CREATE FUNCTION label_is_moderation(source text, kind text, run_id uuid, details jsonb) RETURNS boolean
LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE source
    WHEN 'label_admin_event' THEN kind IN ('annotator.status', 'erasure.requested')
    -- A run's own decisions and served-out retirement (which never changes a score) are not moderation.
    WHEN 'label_trust_event' THEN run_id IS NULL AND kind IN {_in(MODERATION_TRUST)}
      AND NOT (kind = 'gold.retired' AND details ->> 'reason' = 'served_out')
    ELSE false END
$$""")
    op.execute("""
CREATE FUNCTION label_redact_details(kind text, details jsonb) RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
  -- What an erased person's events keep: the item kind, the status or tier change and the run.
  SELECT coalesce(jsonb_object_agg(key, value), '{}'::jsonb) FROM jsonb_each(details)
  WHERE key IN ('kind', 'from', 'to', 'run_id')
$$""")
    op.execute(f"""
CREATE FUNCTION label_journal_stamp() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Held until the writer's transaction ends: a run's barrier waits for every writer
  -- that holds it, so every seq at or below the watermark belongs to a finished transaction.
  PERFORM pg_advisory_xact_lock_shared({JOURNAL_LOCK});
  IF TG_TABLE_NAME = 'label_admin_event' THEN
    IF label_is_moderation(TG_TABLE_NAME, NEW.kind, NULL, NEW.details) THEN
      PERFORM pg_advisory_xact_lock_shared({MODERATION_LOCK});
    END IF;
  END IF;
  IF TG_TABLE_NAME = 'label_trust_event' THEN
    IF label_is_moderation(TG_TABLE_NAME, NEW.kind, NEW.run_id, NEW.details) THEN
      PERFORM pg_advisory_xact_lock_shared({MODERATION_LOCK});
    END IF;
    NEW.id := nextval('label_journal_seq');
  ELSE
    NEW.seq := nextval('label_journal_seq');
  END IF;
  RETURN NEW;
END $$""")
    for table in ("label_judgment", "label_consent", "label_admin_event", "label_trust_event", "label_item_audit"):
        op.execute(f"CREATE TRIGGER {table}_journal_stamp BEFORE INSERT ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION label_journal_stamp()")

    # ---- append-only journals: the V1 exceptions plus the redaction of an erased person's events ----
    op.execute("""
CREATE OR REPLACE FUNCTION label_admin_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'details') = (to_jsonb(OLD) - 'details') THEN
    -- Completing an erasure deletes the identifying details of its request event.
    IF NEW.details = '{}'::jsonb THEN
      RETURN NEW;
    END IF;
    -- Erasing the subject redacts reasons, flags and signal values from its events.
    IF NEW.details = label_redact_details(OLD.kind, OLD.details) AND EXISTS (
         SELECT 1 FROM label_annotator a WHERE a.id::text = OLD.target AND a.status = 'erased') THEN
      RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'label_admin_event is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    op.execute("""
CREATE FUNCTION label_trust_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (to_jsonb(NEW) - 'details') = (to_jsonb(OLD) - 'details') THEN
    IF NEW.details = label_redact_details(OLD.kind, OLD.details) AND EXISTS (
         SELECT 1 FROM label_annotator a WHERE a.id = OLD.annotator_id AND a.status = 'erased') THEN
      RETURN NEW;
    END IF;
    -- Consensus gold supported by an erased person: the support (annotator and
    -- judgment ids) goes, so no live row joins the old and the new identifier.
    IF OLD.kind = 'gold.set' AND jsonb_typeof(OLD.details -> 'support') = 'object'
       AND NEW.details = jsonb_set(OLD.details, '{support}', '{"redacted": true}'::jsonb)
       AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(coalesce(OLD.details -> 'support' -> 'annotators', '[]'::jsonb)) s
                   JOIN label_annotator a ON a.id::text = s.value WHERE a.status = 'erased') THEN
      RETURN NEW;
    END IF;
  END IF;
  RAISE EXCEPTION 'label_trust_event is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    op.execute("""
CREATE FUNCTION label_item_audit_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'label_item_audit is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    for table in ("label_trust_event", "label_item_audit"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION {table}_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {table}_append_only()")


def downgrade():
    raise RuntimeError("003 is forward-only; roll back by deploying the previous image and restoring "
                       "the pre-deploy database backup")

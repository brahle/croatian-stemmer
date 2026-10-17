"""Shared corpora, pseudonymous annotators, consent and an append-only journal.

DESTRUCTIVE: drops the owner-scoped 001 tables. It refuses to run while
label_judgment has rows unless LABELING_MIGRATION_ALLOW_DROP=true, so a database
holding human labels stops the deploy instead of losing them. Export first.
"""
import os

from alembic import op
from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Column, DateTime, ForeignKey, ForeignKeyConstraint,
                        Integer, String, UniqueConstraint, Uuid, text)
from sqlalchemy.dialects.postgresql import JSONB

revision = "002_shared_corpus"
down_revision = "001_labeling"
branch_labels = None
depends_on = None

GUARD = "002 drops label_* tables; export and set LABELING_MIGRATION_ALLOW_DROP=true"


def now():
    return text("now()")


def upgrade():
    judgments = op.get_bind().execute(text("SELECT count(*) FROM label_judgment")).scalar_one()
    if judgments > 0 and os.environ.get("LABELING_MIGRATION_ALLOW_DROP") != "true":
        raise RuntimeError(GUARD)
    op.execute("DROP TABLE label_judgment, label_item, label_corpus")

    op.create_table(
        "label_annotator",
        Column("id", Uuid, primary_key=True, server_default=text("gen_random_uuid()")),
        Column("subject", String(256), nullable=True, unique=True),
        Column("email", String(320), nullable=True),
        Column("email_verified", Boolean, nullable=False, server_default=text("false")),
        Column("status", String(16), nullable=False, server_default="active"),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=now()),
        Column("last_seen_at", DateTime(timezone=True), nullable=False, server_default=now()),
        Column("erased_at", DateTime(timezone=True), nullable=True),
        CheckConstraint("status IN ('active', 'quarantined', 'blocked', 'erased')", name="label_annotator_status"),
        CheckConstraint("(status = 'erased') = (subject IS NULL)", name="label_annotator_erased_subject"))
    op.create_table(
        "label_consent",
        Column("id", BigInteger, primary_key=True),
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), nullable=False),
        Column("document", String(16), nullable=False),
        Column("version", String(32), nullable=False),
        Column("locale", String(5), nullable=False),
        Column("age_confirmed", Boolean, nullable=False),
        Column("ui_version", String(32), nullable=False),
        Column("accepted_at", DateTime(timezone=True), nullable=False, server_default=now()),
        UniqueConstraint("annotator_id", "document", "version"),
        CheckConstraint("document IN ('privacy', 'terms')", name="label_consent_document"),
        CheckConstraint("locale IN ('hr', 'en')", name="label_consent_locale"),
        CheckConstraint("age_confirmed", name="label_consent_age"))
    op.create_table(
        "label_corpus",
        Column("id", Uuid, primary_key=True),
        Column("name", String(200), nullable=False),
        Column("sha256", String(64), nullable=False),
        Column("source_uri", String(2048), nullable=False),
        Column("license", String(512), nullable=False),
        Column("labels_license", String(64), nullable=True),
        Column("status", String(16), nullable=False, server_default="draft"),
        Column("created_by", Uuid, ForeignKey("label_annotator.id"), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False, server_default=now()),
        Column("published_at", DateTime(timezone=True), nullable=True),
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="label_corpus_sha256"),
        CheckConstraint("status IN ('draft', 'published', 'archived')", name="label_corpus_status"),
        CheckConstraint("(status = 'published') <= (labels_license IS NOT NULL)", name="label_corpus_published_license"))
    op.create_table(
        "label_item",
        Column("corpus_id", Uuid, ForeignKey("label_corpus.id", ondelete="CASCADE"), primary_key=True),
        Column("id", Uuid, primary_key=True),
        Column("ordinal", Integer, nullable=False),
        Column("kind", String(16), nullable=False),
        Column("payload", JSONB, nullable=False),
        Column("revision", Integer, nullable=False, server_default="1"),
        Column("status", String(16), nullable=False, server_default="active"),
        UniqueConstraint("corpus_id", "ordinal"),
        CheckConstraint("kind IN ('pair', 'lemma', 'stem')", name="label_item_kind"),
        CheckConstraint("revision >= 1", name="label_item_revision"),
        CheckConstraint("status IN ('active', 'retired')", name="label_item_status"))
    op.create_table(
        "label_judgment",
        Column("id", Uuid, primary_key=True),
        Column("corpus_id", Uuid, nullable=False),
        Column("item_id", Uuid, nullable=False),
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("answer", String(16), nullable=False),
        Column("lemma", String(128), nullable=False, server_default=""),
        Column("irregular", Boolean, nullable=False),
        Column("item_revision", Integer, nullable=False),
        Column("client_version", String(32), nullable=False),
        Column("source", String(16), nullable=False, server_default="web"),
        Column("elapsed_ms", Integer, nullable=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        UniqueConstraint("annotator_id", "corpus_id", "item_id", "revision"),
        CheckConstraint("revision > 0", name="label_judgment_revision"),
        CheckConstraint("answer IN ('same', 'different', 'unsure', 'confirmed', 'accept', 'reject')",
                        name="label_judgment_answer"),
        CheckConstraint("source IN ('web', 'adjudication', 'import')", name="label_judgment_source"),
        CheckConstraint("elapsed_ms BETWEEN 0 AND 3600000", name="label_judgment_elapsed"))
    op.create_index("ix_label_judgment_annotator_created", "label_judgment", ["annotator_id", "created_at"])
    op.create_index("ix_label_judgment_item", "label_judgment", ["corpus_id", "item_id"])
    op.create_table(
        "label_assignment",
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), primary_key=True),
        Column("corpus_id", Uuid, primary_key=True),
        Column("item_id", Uuid, primary_key=True),
        Column("first_shown_at", DateTime(timezone=True), nullable=False),
        Column("last_shown_at", DateTime(timezone=True), nullable=False),
        Column("shown_count", Integer, nullable=False, server_default="1"),
        Column("current_revision", Integer, nullable=False, server_default="0"),
        Column("last_answer_at", DateTime(timezone=True), nullable=True),
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint("shown_count >= 0", name="label_assignment_shown"),
        CheckConstraint("current_revision >= 0", name="label_assignment_revision"))
    op.create_table(
        "label_setting",
        Column("key", String(64), primary_key=True),
        Column("value", JSONB, nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("updated_by", Uuid, ForeignKey("label_annotator.id"), nullable=True))
    op.create_table(
        "label_admin_event",
        Column("id", BigInteger, primary_key=True),
        Column("at", DateTime(timezone=True), nullable=False, server_default=now()),
        Column("actor_id", Uuid, ForeignKey("label_annotator.id"), nullable=True),
        Column("kind", String(32), nullable=False),
        Column("target", String(256), nullable=False),
        Column("details", JSONB, nullable=False))
    op.create_table(
        "label_erasure_request",
        Column("id", BigInteger, primary_key=True),
        Column("annotator_id", Uuid, ForeignKey("label_annotator.id"), nullable=False),
        Column("subject_sha256", String(64), nullable=True),
        Column("requested_at", DateTime(timezone=True), nullable=False),
        Column("app_erased_at", DateTime(timezone=True), nullable=False),
        Column("keycloak_deleted_at", DateTime(timezone=True), nullable=True))

    op.execute("INSERT INTO label_setting (key, value, updated_at) VALUES ('accepting_judgments', 'true'::jsonb, now())")

    # Append-only journals. The application role owns the tables, so a trigger
    # (not a privilege) is the guard. Each allows exactly one sanctioned UPDATE.
    op.execute("""
CREATE FUNCTION label_judgment_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Erasure may null elapsed_ms (behavioural data); nothing else may change.
  IF TG_OP = 'UPDATE' AND NEW.elapsed_ms IS NULL
     AND (to_jsonb(NEW) - 'elapsed_ms') = (to_jsonb(OLD) - 'elapsed_ms') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'label_judgment is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    op.execute("""
CREATE FUNCTION label_consent_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'label_consent is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    op.execute("""
CREATE FUNCTION label_admin_event_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  -- Completing an erasure deletes the identifying details of its request event.
  IF TG_OP = 'UPDATE' AND NEW.details = '{}'::jsonb
     AND (to_jsonb(NEW) - 'details') = (to_jsonb(OLD) - 'details') THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'label_admin_event is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    for table in ("label_judgment", "label_consent", "label_admin_event"):
        op.execute(f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
                   f"FOR EACH ROW EXECUTE FUNCTION {table}_append_only()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
                   f"FOR EACH STATEMENT EXECUTE FUNCTION {table}_append_only()")


def downgrade():
    # Like 001's downgrade: recreates the 001 tables EMPTY. Only for a database
    # with nothing worth keeping; roll back the image first.
    op.execute("DROP TABLE label_erasure_request, label_admin_event, label_setting, label_assignment, "
               "label_judgment, label_item, label_corpus, label_consent, label_annotator")
    for table in ("label_judgment", "label_consent", "label_admin_event"):
        op.execute(f"DROP FUNCTION {table}_append_only()")
    op.create_table("label_corpus", Column("owner_id", String(256), primary_key=True),
                    Column("id", Uuid, primary_key=True), Column("name", String(200), nullable=False),
                    Column("sha256", String(64), nullable=False), Column("source_uri", String(2048), nullable=False),
                    Column("license", String(512), nullable=False),
                    Column("created_at", DateTime(timezone=True), server_default=text("now()"), nullable=False),
                    CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"))
    op.create_table("label_item", Column("owner_id", String(256), primary_key=True),
                    Column("corpus_id", Uuid, primary_key=True), Column("id", Uuid, primary_key=True),
                    Column("ordinal", Integer, nullable=False), Column("kind", String(16), nullable=False),
                    Column("payload", JSONB, nullable=False), Column("current_revision", Integer, server_default="0", nullable=False),
                    ForeignKeyConstraint(["owner_id", "corpus_id"], ["label_corpus.owner_id", "label_corpus.id"], ondelete="CASCADE"),
                    UniqueConstraint("owner_id", "corpus_id", "ordinal"),
                    CheckConstraint("kind IN ('pair', 'lemma', 'stem')"), CheckConstraint("current_revision >= 0"))
    op.create_table("label_judgment", Column("owner_id", String(256), primary_key=True),
                    Column("corpus_id", Uuid, primary_key=True), Column("item_id", Uuid, primary_key=True),
                    Column("revision", Integer, primary_key=True), Column("annotation_id", Uuid, nullable=False),
                    Column("answer", String(16), nullable=False), Column("lemma", String(128), nullable=False),
                    Column("irregular", Boolean, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False),
                    ForeignKeyConstraint(["owner_id", "corpus_id", "item_id"], ["label_item.owner_id", "label_item.corpus_id", "label_item.id"], ondelete="CASCADE"),
                    UniqueConstraint("owner_id", "annotation_id"), CheckConstraint("revision > 0"),
                    CheckConstraint("answer IN ('same', 'different', 'unsure', 'confirmed', 'accept', 'reject')"))

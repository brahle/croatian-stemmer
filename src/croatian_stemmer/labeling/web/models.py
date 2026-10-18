"""Shared corpora, pseudonymous annotators, append-only journals and the trust tables.

Migrations 002, 002a and 003 create exactly these tables (alembic check compares
them) plus what alembic does not compare: the journal sequence, the triggers that
stamp every journal row with it, and the append-only triggers on label_judgment,
label_consent, label_admin_event, label_trust_event and label_item_audit.

The five journals (judgments, consents, admin events, trust events, item
membership) share one sequence, label_journal_seq, so "after the watermark" is one
integer comparison. A scoring run reads only those journals up to its watermark;
every other trust table is a mirror for the request path or a run's output.
"""

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, Date, DateTime, Double, FetchedValue, ForeignKey,
                        ForeignKeyConstraint,
                        Index, Integer, SmallInteger, String, Text, UniqueConstraint, Uuid, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ANSWERS = ("same", "different", "unsure", "confirmed", "accept", "reject")
CONSENT_DOCUMENTS = ("privacy", "terms", "participation")
TRUST_EVENTS = ("trusted.added", "trusted.removed", "anchor.granted", "anchor.revoked",
                "annotator.quarantined", "annotator.cleared", "tier.changed",
                "gold.set", "gold.retired", "gold.reactivated", "gold.contested", "gold.retracted",
                "gold.disclosed", "calibration.drawn", "calibration.redraw_requested",
                "item.adjudicated", "item.ambiguous", "item.reopened",
                "params.changed", "run.pinned", "run.unpinned")
ITEM_STATES = ("open", "provisional", "resolved", "needs_expert", "contested", "ambiguous")
TIERS = ("new", "qualified", "established", "anchor", "quarantined")
GOLD_ANSWERS = ("same", "different", "confirmed", "accept", "reject")
# Advisory lock keys (migration 003's triggers use the same numbers).
JOURNAL_LOCK = 7266001  # shared by every journal insert; exclusive for a run's barrier
MODERATION_LOCK = 7266002  # shared by moderation writers; exclusive while a run publishes
SCORING_LOCK = 7266003  # one scoring run at a time (session-level, try-lock)
# Admin and trust events that a run must not publish over (4.6.5); the journal trigger
# takes the shared moderation lock for exactly these (label_is_moderation()).
MODERATION_ADMIN_EVENTS = ("annotator.status", "erasure.requested")
MODERATION_TRUST_EVENTS = ("trusted.added", "trusted.removed", "anchor.granted", "anchor.revoked",
                           "annotator.cleared", "gold.set", "gold.retired", "gold.reactivated",
                           "gold.contested", "gold.retracted", "gold.disclosed", "item.adjudicated",
                           "item.ambiguous", "item.reopened", "params.changed", "calibration.redraw_requested")


class Base(DeclarativeBase):
    pass


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Annotator(Base):
    """`id` is the pseudonym printed in every export; erasure nulls subject and email.

    An erased row is either an emptied profile (its answers moved away) or the
    subject-less row that received them under a new random id."""
    __tablename__ = "label_annotator"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, server_default=text("gen_random_uuid()"))
    subject: Mapped[str | None] = mapped_column(String(256), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    email_verified: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint(_in("status", ("active", "quarantined", "blocked", "erased")), name="label_annotator_status"),
        CheckConstraint("(status = 'erased') = (subject IS NULL)", name="label_annotator_erased_subject"),
        CheckConstraint("status <> 'erased' OR (email IS NULL AND NOT email_verified)",
                        name="label_annotator_erased_email"),
    )


class Consent(Base):
    """Append-only (trigger), apart from the erasure move and the deletion of an erased person's rows."""
    __tablename__ = "label_consent"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    document: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    locale: Mapped[str] = mapped_column(String(5))
    age_confirmed: Mapped[bool] = mapped_column(Boolean)
    ui_version: Mapped[str] = mapped_column(String(32))
    # The minimum age the person confirmed (NULL on rows from before 0.2.3, which asked for 16).
    age_threshold: Mapped[int | None] = mapped_column(SmallInteger)
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seq: Mapped[int | None] = mapped_column(BigInteger)  # journal position (trigger)
    __table_args__ = (
        UniqueConstraint("annotator_id", "document", "version"),
        CheckConstraint(_in("document", CONSENT_DOCUMENTS), name="label_consent_document"),
        CheckConstraint(_in("locale", ("hr", "en")), name="label_consent_locale"),
        CheckConstraint("age_confirmed", name="label_consent_age"),
    )


class Corpus(Base):
    __tablename__ = "label_corpus"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    source_uri: Mapped[str] = mapped_column(String(2048))
    license: Mapped[str] = mapped_column(String(512))
    labels_license: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), server_default="draft")
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="label_corpus_sha256"),
        CheckConstraint(_in("status", ("draft", "published", "archived")), name="label_corpus_status"),
        CheckConstraint("(status = 'published') <= (labels_license IS NOT NULL)", name="label_corpus_published_license"),
    )


class Item(Base):
    """Immutable question; content changes only by retiring it and importing a new item."""
    __tablename__ = "label_item"
    corpus_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_corpus.id", ondelete="CASCADE"), primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSONB)
    revision: Mapped[int] = mapped_column(Integer, server_default="1")
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    __table_args__ = (
        UniqueConstraint("corpus_id", "ordinal"),
        CheckConstraint(_in("kind", ("pair", "lemma", "stem")), name="label_item_kind"),
        CheckConstraint("revision >= 1", name="label_item_revision"),
        CheckConstraint(_in("status", ("active", "retired")), name="label_item_status"),
    )


class Judgment(Base):
    """Append-only journal (trigger). Erasure may null elapsed_ms, move the rows to a
    new erased annotator (fresh id, day-level time) or delete an erased person's rows."""
    __tablename__ = "label_judgment"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(Uuid)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    revision: Mapped[int] = mapped_column(Integer)
    answer: Mapped[str] = mapped_column(String(16))
    lemma: Mapped[str] = mapped_column(String(128), server_default="")
    irregular: Mapped[bool] = mapped_column(Boolean)
    item_revision: Mapped[int] = mapped_column(Integer)
    client_version: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16), server_default="web")
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Journal position (trigger); NULL on rows written before 003, which count as 0.
    seq: Mapped[int | None] = mapped_column(BigInteger)
    # Vote admission at answer time (4.9.2); NULL (a V1 row) counts as admitted, group low.
    admitted: Mapped[bool | None] = mapped_column(Boolean)
    admission_group: Mapped[str | None] = mapped_column(String(8))
    # Whether the suggestion was shown; NULL = shown.
    presentation: Mapped[str | None] = mapped_column(String(8))
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        UniqueConstraint("annotator_id", "corpus_id", "item_id", "revision"),
        CheckConstraint(_in("admission_group", ("low", "expert")), name="label_judgment_admission_group"),
        CheckConstraint(_in("presentation", ("shown", "blind")), name="label_judgment_presentation"),
        Index("ix_label_judgment_annotator_created", "annotator_id", "created_at"),
        Index("ix_label_judgment_item", "corpus_id", "item_id"),
        CheckConstraint("revision > 0", name="label_judgment_revision"),
        CheckConstraint(_in("answer", ANSWERS), name="label_judgment_answer"),
        CheckConstraint(_in("source", ("web", "adjudication", "import")), name="label_judgment_source"),
        CheckConstraint("elapsed_ms BETWEEN 0 AND 3600000", name="label_judgment_elapsed"),
    )


class Assignment(Base):
    """One row per (annotator, item) ever shown; current_revision is the concurrency token."""
    __tablename__ = "label_assignment"
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    first_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_shown_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    shown_count: Mapped[int] = mapped_column(Integer, server_default="1")
    current_revision: Mapped[int] = mapped_column(Integer, server_default="0")
    last_answer_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Decided at the first showing (blind = no suggestion) and copied to the judgment.
    presentation: Mapped[str | None] = mapped_column(String(8))
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        Index("ix_label_assignment_item_lease", "corpus_id", "item_id", postgresql_where=text("current_revision = 0")),
        CheckConstraint(_in("presentation", ("shown", "blind")), name="label_assignment_presentation"),
        CheckConstraint("shown_count >= 0", name="label_assignment_shown"),
        CheckConstraint("current_revision >= 0", name="label_assignment_revision"),
    )


class Setting(Base):
    __tablename__ = "label_setting"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | bool] = mapped_column(JSONB)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))


class AdminEvent(Base):
    """Append-only journal of privileged actions. Erasure completion may only clear
    `details`; erasing the subject may only redact it (label_redact_details)."""
    __tablename__ = "label_admin_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    kind: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(256))
    details: Mapped[dict] = mapped_column(JSONB)
    seq: Mapped[int | None] = mapped_column(BigInteger)  # journal position (trigger)


class ErasureRequest(Base):
    __tablename__ = "label_erasure_request"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    subject_sha256: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    app_erased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    keycloak_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrustEvent(Base):
    """Append-only journal of trust decisions; `id` is its journal position, assigned by
    the trigger (no default). `details` never holds an email, an email hash, a name or a
    label; erasing the subject may only redact it."""
    __tablename__ = "label_trust_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False, server_default=FetchedValue())
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))  # NULL = a run
    kind: Mapped[str] = mapped_column(String(32))
    annotator_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    corpus_id: Mapped[UUID | None] = mapped_column(Uuid)
    item_id: Mapped[UUID | None] = mapped_column(Uuid)
    run_id: Mapped[UUID | None] = mapped_column(Uuid)  # the run that decided it (automation)
    details: Mapped[dict] = mapped_column(JSONB)
    __table_args__ = (
        CheckConstraint(_in("kind", TRUST_EVENTS), name="label_trust_event_kind"),
        Index("ix_label_trust_event_annotator", "annotator_id", "id"),
        Index("ix_label_trust_event_item", "corpus_id", "item_id", "id"),
        Index("ix_label_trust_event_kind", "kind", "id"),
    )


class TrustedEmail(Base):
    """The curator's trusted list. Identity fields are deleted on removal or erasure;
    only `id` ever appears in the journal."""
    __tablename__ = "label_trusted_email"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    email_sha256: Mapped[str | None] = mapped_column(String(64))
    label: Mapped[str | None] = mapped_column(String(100))
    added_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("(removed_at IS NULL) = (email IS NOT NULL AND email_sha256 IS NOT NULL AND label IS NOT NULL)",
                        name="label_trusted_email_identity"),
        Index("ux_label_trusted_email_active", "email_sha256", unique=True, postgresql_where=text("removed_at IS NULL")),
    )


class Anchor(Base):
    """Request-path mirror of anchor.granted/anchor.revoked; runs read the events."""
    __tablename__ = "label_anchor"
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"), primary_key=True)
    trusted_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("label_trusted_email.id"))
    granted_event_id: Mapped[int] = mapped_column(BigInteger)


class Gold(Base):
    """Serving mirror of the gold.* events (scheduler, dashboard); runs read the events."""
    __tablename__ = "label_gold"
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    pool: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str] = mapped_column(String(16))
    lemma: Mapped[str] = mapped_column(String(128), server_default="")
    source: Mapped[str] = mapped_column(String(16))
    # pair/lemma: the gold equals what the visible suggestion implies; NULL for stem.
    suggestion_agrees: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16))
    served_count: Mapped[int] = mapped_column(Integer, server_default="0")
    last_event_id: Mapped[int] = mapped_column(BigInteger)
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint(_in("pool", ("qualification", "audit")), name="label_gold_pool"),
        CheckConstraint(_in("answer", GOLD_ANSWERS), name="label_gold_answer"),
        CheckConstraint(_in("source", ("hr500k", "curator", "anchor_consensus")), name="label_gold_source"),
        CheckConstraint(_in("status", ("active", "retired", "contested", "retracted")), name="label_gold_status"),
        Index("ix_label_gold_pool", "kind", "pool", "status"),
    )


class ScoringRun(Base):
    """One scoring run: its inputs are the journals up to `watermark` and `params`."""
    __tablename__ = "label_scoring_run"
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    scoring_version: Mapped[str] = mapped_column(String(16))
    params: Mapped[dict] = mapped_column(JSONB)
    params_sha256: Mapped[str] = mapped_column(String(64))
    watermark: Mapped[int] = mapped_column(BigInteger)
    as_of_day: Mapped[date] = mapped_column(Date)
    previous_run_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_scoring_run.id"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    triggered_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    n_judgments: Mapped[int | None] = mapped_column(Integer)
    n_items: Mapped[int | None] = mapped_column(Integer)
    n_annotators: Mapped[int | None] = mapped_column(Integer)
    inputs_sha256: Mapped[str | None] = mapped_column(String(64))
    # Per journal: rows and sha256, so a replay can say which journal changed since (4.6.6).
    inputs_summary: Mapped[dict | None] = mapped_column(JSONB)
    outputs_sha256: Mapped[str | None] = mapped_column(String(64))
    calibration: Mapped[dict | None] = mapped_column(JSONB)
    readiness: Mapped[dict | None] = mapped_column(JSONB)
    pinned: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    error: Mapped[str | None] = mapped_column(Text)  # message only, never row contents
    __table_args__ = (
        CheckConstraint(_in("status", ("running", "done", "failed", "superseded")), name="label_scoring_run_status"),
    )


class AnnotatorScore(Base):
    """Per run, annotator and kind. Personal derived data: 30-day retention."""
    __tablename__ = "label_annotator_score"
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_scoring_run.id", ondelete="CASCADE"), primary_key=True)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    tier: Mapped[str] = mapped_column(String(16))
    base_tier: Mapped[str] = mapped_column(String(16))  # ignoring quarantine: what the person's card shows
    qualified: Mapped[bool] = mapped_column(Boolean)
    alpha0: Mapped[float] = mapped_column(Double)
    beta0: Mapped[float] = mapped_column(Double)
    gold_seen: Mapped[int] = mapped_column(Integer)
    gold_hits: Mapped[int] = mapped_column(Integer)
    disc_seen: Mapped[int] = mapped_column(Integer)
    disc_hits: Mapped[int] = mapped_column(Integer)
    wrong_sugg_seen: Mapped[int] = mapped_column(Integer)
    wrong_sugg_hits: Mapped[int] = mapped_column(Integer)
    soft_hits: Mapped[float] = mapped_column(Double)
    soft_misses: Mapped[float] = mapped_column(Double)
    theta_mean: Mapped[float] = mapped_column(Double)
    theta_lb_gold: Mapped[float] = mapped_column(Double)
    weight: Mapped[float] = mapped_column(Double)
    flags: Mapped[dict] = mapped_column(JSONB)
    n_definite: Mapped[int] = mapped_column(Integer)
    n_unsure: Mapped[int] = mapped_column(Integer)
    n_resolved_agree: Mapped[int] = mapped_column(Integer)
    n_resolved_total: Mapped[int] = mapped_column(Integer)
    __table_args__ = (
        CheckConstraint(_in("tier", TIERS), name="label_annotator_score_tier"),
        Index("ix_label_annotator_score_annotator", "annotator_id", "run_id"),
    )


class ItemPosterior(Base):
    """Per run and item with a counted vote or a curator decision; no annotator ids.
    Derived from personal data: 30-day retention."""
    __tablename__ = "label_item_posterior"
    run_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_scoring_run.id", ondelete="CASCADE"), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    cell: Mapped[str] = mapped_column(String(16))  # calibration cell: agrees | differs | none
    classes: Mapped[list] = mapped_column(JSONB)
    confidence: Mapped[float | None] = mapped_column(Double)
    state: Mapped[str] = mapped_column(String(16))
    releasable: Mapped[bool] = mapped_column(Boolean)
    resolution_source: Mapped[str | None] = mapped_column(String(16))
    resolved_answer: Mapped[str | None] = mapped_column(String(16))
    resolved_lemma: Mapped[str | None] = mapped_column(String(128))
    epoch: Mapped[int] = mapped_column(BigInteger)
    n_definite: Mapped[int] = mapped_column(Integer)
    n_low: Mapped[int] = mapped_column(Integer)
    n_expert: Mapped[int] = mapped_column(Integer)
    n_unsure: Mapped[int] = mapped_column(Integer)
    n_annotators: Mapped[int] = mapped_column(Integer)
    n_anchor_votes: Mapped[int] = mapped_column(Integer)
    n_established_votes: Mapped[int] = mapped_column(Integer)
    irregular_votes: Mapped[int] = mapped_column(Integer)
    gold_status: Mapped[str | None] = mapped_column(String(16))  # curator-only diagnostic
    __table_args__ = (
        CheckConstraint(_in("state", ITEM_STATES), name="label_item_posterior_state"),
        CheckConstraint(_in("resolution_source", ("model", "adjudication", "reference", "review")),
                        name="label_item_posterior_source"),
    )


class ItemState(Base):
    """The latest published run's view of each item (scheduler queue), plus the reopen epoch."""
    __tablename__ = "label_item_state"
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    run_id: Mapped[UUID | None] = mapped_column(Uuid)
    state: Mapped[str] = mapped_column(String(16), server_default="open")
    confidence: Mapped[float | None] = mapped_column(Double)
    releasable: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    n_low: Mapped[int] = mapped_column(Integer, server_default="0")
    n_expert: Mapped[int] = mapped_column(Integer, server_default="0")
    priority: Mapped[float] = mapped_column(Double, server_default=text("1.0"))
    epoch: Mapped[int] = mapped_column(BigInteger, server_default="0")  # written only by the reopen route
    epoch_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    epoch_discard: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint(_in("state", ITEM_STATES), name="label_item_state_state"),
        Index("ix_label_item_state_queue", "corpus_id", "kind", "state", text("priority DESC")),
    )


class ItemAudit(Base):
    """Item membership journal: one immutable row per item, written with the item.

    The keyed bits are decided once from the audit key, so a run and its replay need
    the bits but never the key."""
    __tablename__ = "label_item_audit"
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    seq: Mapped[int | None] = mapped_column(BigInteger)  # NULL = written by the 003 backfill (counts as 0)
    audit_sample: Mapped[bool] = mapped_column(Boolean)  # calibration sample (4.4.7)
    review_sample: Mapped[bool] = mapped_column(Boolean)  # moderation review sample (4.8.1)
    audit_rank: Mapped[int] = mapped_column(BigInteger)  # orders evaluation draws
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        CheckConstraint("NOT (audit_sample AND review_sample)", name="label_item_audit_disjoint"),
    )

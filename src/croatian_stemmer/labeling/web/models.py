"""Shared corpora, pseudonymous annotators and an append-only judgment journal.

Migration 002 creates exactly these tables (alembic check compares them) plus
the append-only triggers on label_judgment, label_consent and label_admin_event.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
                        Index, Integer, String, UniqueConstraint, Uuid, func, text)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ANSWERS = ("same", "different", "unsure", "confirmed", "accept", "reject")


class Base(DeclarativeBase):
    pass


def _in(column, values):
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Annotator(Base):
    """`id` is the pseudonym printed in every export; erasure nulls subject and email."""
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
    )


class Consent(Base):
    """Append-only (trigger)."""
    __tablename__ = "label_consent"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    document: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    locale: Mapped[str] = mapped_column(String(5))
    age_confirmed: Mapped[bool] = mapped_column(Boolean)
    ui_version: Mapped[str] = mapped_column(String(32))
    accepted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (
        UniqueConstraint("annotator_id", "document", "version"),
        CheckConstraint(_in("document", ("privacy", "terms")), name="label_consent_document"),
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
    """Append-only journal (trigger); the only permitted UPDATE nulls elapsed_ms on erasure."""
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
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
        UniqueConstraint("annotator_id", "corpus_id", "item_id", "revision"),
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
    __table_args__ = (
        ForeignKeyConstraint(["corpus_id", "item_id"], ["label_item.corpus_id", "label_item.id"]),
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
    """Append-only journal of privileged actions; erasure completion may only clear `details`."""
    __tablename__ = "label_admin_event"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    kind: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(256))
    details: Mapped[dict] = mapped_column(JSONB)


class ErasureRequest(Base):
    __tablename__ = "label_erasure_request"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    annotator_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("label_annotator.id"))
    subject_sha256: Mapped[str | None] = mapped_column(String(64))
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    app_erased_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    keycloak_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

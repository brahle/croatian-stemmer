"""Tenant-scoped corpus, immutable candidates and append-only annotations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKeyConstraint, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Corpus(Base):
    __tablename__ = "label_corpus"
    owner_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    source_uri: Mapped[str] = mapped_column(String(2048))
    license: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    __table_args__ = (CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'"),)


class Item(Base):
    __tablename__ = "label_item"
    owner_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    payload: Mapped[dict] = mapped_column(JSONB)
    current_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "corpus_id"], ["label_corpus.owner_id", "label_corpus.id"], ondelete="CASCADE"),
        UniqueConstraint("owner_id", "corpus_id", "ordinal"),
        CheckConstraint("kind IN ('pair', 'lemma', 'stem')"),
        CheckConstraint("current_revision >= 0"),
    )


class Judgment(Base):
    __tablename__ = "label_judgment"
    owner_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    corpus_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    item_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, primary_key=True)
    annotation_id: Mapped[UUID] = mapped_column(Uuid)
    answer: Mapped[str] = mapped_column(String(16))
    lemma: Mapped[str] = mapped_column(String(128), default="")
    irregular: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        ForeignKeyConstraint(["owner_id", "corpus_id", "item_id"], ["label_item.owner_id", "label_item.corpus_id", "label_item.id"], ondelete="CASCADE"),
        UniqueConstraint("owner_id", "annotation_id"),
        CheckConstraint("revision > 0"),
        CheckConstraint("answer IN ('same', 'different', 'unsure', 'confirmed', 'accept', 'reject')"),
    )

"""Initial tenant-scoped labeling schema."""
from alembic import op
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Uuid, CheckConstraint, ForeignKeyConstraint, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB

revision = "001_labeling"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
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

def downgrade():
    op.drop_table("label_judgment")
    op.drop_table("label_item")
    op.drop_table("label_corpus")

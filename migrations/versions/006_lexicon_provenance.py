"""Lexicon provenance (0.4.0): the source and licence of the lexicon behind a raw-text
corpus's lemma and POS suggestions (candidate schema 2, `from-text`).

Two nullable columns on label_corpus; existing corpora (schema 1) keep NULL. Publishing
takes the stricter of the source and lexicon licences. downgrade() refuses while a corpus
has a lexicon: 0.3.4 would publish it under the source licence alone.
"""
from alembic import op
from sqlalchemy import Column, String, text

revision = "006_lexicon_provenance"
down_revision = "005_gold_reserve"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("label_corpus", Column("lexicon_uri", String(2048), nullable=True))
    op.add_column("label_corpus", Column("lexicon_license", String(512), nullable=True))


def downgrade():
    if op.get_bind().execute(text("SELECT count(*) FROM label_corpus WHERE lexicon_uri IS NOT NULL")).scalar_one():
        raise RuntimeError("006 downgrade: a corpus has lexicon provenance that 0.3.4 would ignore when "
                           "publishing; archive or restore it first")
    op.drop_column("label_corpus", "lexicon_license")
    op.drop_column("label_corpus", "lexicon_uri")

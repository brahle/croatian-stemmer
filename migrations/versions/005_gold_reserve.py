"""Gold-reserve items (0.3.4): a `reserve` flag on the scheduler's queue rows.

Items prepared with `croatian-stemmer-labels prepare --gold-reserve` (sampling stratum
`gold_reserve_*`) exist only to become known-answer checks; a decoy shows a suggestion
the corpus contradicts on purpose. The queue reads label_item_state alone, so the flag
lives there, next to `kind`, and the import sets it from the immutable payload. Adding
the column with a constant default rewrites nothing; the backfill marks reserve items
imported before this revision (none on a database that never imported a reserve).
downgrade() drops the column (the 0.3.3 image then serves reserve items as ordinary work
again, so remove them from the queue first if any were imported).
"""
from alembic import op
from sqlalchemy import Boolean, Column, text

revision = "005_gold_reserve"
down_revision = "004_two_vote_params"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("label_item_state", Column("reserve", Boolean, nullable=False, server_default=text("false")))
    op.execute(text("""
        UPDATE label_item_state s SET reserve = true FROM label_item i
        WHERE i.corpus_id = s.corpus_id AND i.id = s.item_id
          AND starts_with(coalesce(i.payload ->> 'sampling_stratum', ''), 'gold_reserve_')"""))


def downgrade():
    op.drop_column("label_item_state", "reserve")

"""Gold-reserve items (0.3.4): a `reserve` flag on the scheduler's queue rows.

Items prepared with `croatian-stemmer-labels prepare --gold-reserve` (sampling stratum
`gold_reserve_*`) exist only to become known-answer checks; a decoy shows a suggestion
the corpus contradicts on purpose. The queue reads label_item_state alone, so the flag
lives there, next to `kind`, and the import sets it from the immutable payload. Adding
the column with a constant default rewrites nothing; the backfill marks reserve items
imported before this revision (none on a database that never imported a reserve).

downgrade() refuses while any reserve item exists: 0.3.3 knows no reserve and would serve
the decoys as ordinary work. With LABELING_MIGRATION_RETIRE_RESERVE=true it first retires
every reserve item (label_item.status = retired: no version serves a retired item) and its
active gold (a `gold.retired` event, reason `rollback`), then drops the column. Retired
items are not reactivated by a later upgrade; prepare a new reserve instead.
"""
import json
import os

from alembic import op
from sqlalchemy import Boolean, Column, text

revision = "005_gold_reserve"
down_revision = "004_two_vote_params"
branch_labels = None
depends_on = None

MODERATION_LOCK = 7266002
GUARD = ("005 downgrade: gold-reserve items exist and 0.3.3 would serve their decoys as ordinary work; "
         "set LABELING_MIGRATION_RETIRE_RESERVE=true to retire them first, or restore the backup taken "
         "before they were imported")


def upgrade():
    op.add_column("label_item_state", Column("reserve", Boolean, nullable=False, server_default=text("false")))
    op.execute(text("""
        UPDATE label_item_state s SET reserve = true FROM label_item i
        WHERE i.corpus_id = s.corpus_id AND i.id = s.item_id
          AND starts_with(coalesce(i.payload ->> 'sampling_stratum', ''), 'gold_reserve_')"""))


def downgrade():
    bind = op.get_bind()
    reserve = bind.execute(text("SELECT count(*) FROM label_item_state s JOIN label_item i "
                                "ON i.corpus_id = s.corpus_id AND i.id = s.item_id "
                                "WHERE s.reserve AND i.status = 'active'")).scalar_one()
    if reserve:
        if os.environ.get("LABELING_MIGRATION_RETIRE_RESERVE") != "true":
            raise RuntimeError(GUARD)
        bind.execute(text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": MODERATION_LOCK})
        gold = bind.execute(text("""
            SELECT g.corpus_id, g.item_id FROM label_gold g JOIN label_item_state s
              ON s.corpus_id = g.corpus_id AND s.item_id = g.item_id
            WHERE s.reserve AND g.status = 'active' ORDER BY g.corpus_id, g.item_id""")).all()
        for corpus_id, item_id in gold:
            event = bind.execute(text(
                "INSERT INTO label_trust_event (kind, corpus_id, item_id, details) "
                "VALUES ('gold.retired', :c, :i, CAST(:d AS jsonb)) RETURNING id"),
                {"c": corpus_id, "i": item_id, "d": json.dumps({"reason": "rollback"})}).scalar_one()
            bind.execute(text("UPDATE label_gold SET status = 'retired', last_event_id = :e "
                              "WHERE corpus_id = :c AND item_id = :i"), {"e": event, "c": corpus_id, "i": item_id})
        bind.execute(text("UPDATE label_item i SET status = 'retired' FROM label_item_state s "
                          "WHERE s.corpus_id = i.corpus_id AND s.item_id = i.id AND s.reserve"))
    op.drop_column("label_item_state", "reserve")

"""V1 follow-ups (0.2.3): participation consent and age 18, erasure under a new id.

Forward-only and not destructive: it widens the consent documents, adds the
confirmed age, clears emails that a refresh raced back onto erased profiles and
then forbids them, and replaces two append-only triggers so that erasure can move
a person's judgments and consents to a new random annotator id (or delete them
when the person was blocked or set aside). Rollback is the previous image plus a
restore of the pre-deploy backup; downgrade() refuses.
"""
from alembic import op
from sqlalchemy import Column, SmallInteger

revision = "002a_v1_followups"
down_revision = "002_shared_corpus"
branch_labels = None
depends_on = None

# True when `annotator` is an erased row with no subject: the only owner a moved row may get.
ERASED = "EXISTS (SELECT 1 FROM label_annotator a WHERE a.id = {0} AND a.status = 'erased' AND a.subject IS NULL)"


def upgrade():
    # A refresh paused across an erasure could write the token's email back (fixed in 0.2.3).
    op.execute("UPDATE label_annotator SET email = NULL, email_verified = false WHERE status = 'erased'")
    op.create_check_constraint("label_annotator_erased_email", "label_annotator",
                               "status <> 'erased' OR (email IS NULL AND NOT email_verified)")
    op.drop_constraint("label_consent_document", "label_consent", type_="check")
    op.create_check_constraint("label_consent_document", "label_consent",
                               "document IN ('privacy', 'terms', 'participation')")
    op.add_column("label_consent", Column("age_threshold", SmallInteger, nullable=True))

    erased = ERASED.format("NEW.annotator_id")
    # Same triggers (002), new bodies. Besides V1's elapsed_ms -> NULL, erasure may
    # re-key a row to a new erased annotator (new row id, time cut to the UTC day,
    # no timing, nothing else changed) and delete the rows of an erased annotator.
    op.execute(f"""
CREATE OR REPLACE FUNCTION label_judgment_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.elapsed_ms IS NULL
       AND (to_jsonb(NEW) - 'elapsed_ms') = (to_jsonb(OLD) - 'elapsed_ms') THEN
      RETURN NEW;
    END IF;
    IF NEW.id <> OLD.id AND NEW.annotator_id <> OLD.annotator_id AND NEW.elapsed_ms IS NULL
       AND NEW.created_at = date_trunc('day', OLD.created_at, 'UTC')
       AND (to_jsonb(NEW) - ARRAY['id', 'annotator_id', 'created_at', 'elapsed_ms'])
         = (to_jsonb(OLD) - ARRAY['id', 'annotator_id', 'created_at', 'elapsed_ms'])
       AND {erased} THEN
      RETURN NEW;
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM label_annotator a WHERE a.id = OLD.annotator_id AND a.status = 'erased') THEN
      RETURN OLD;
    END IF;
  END IF;
  RAISE EXCEPTION 'label_judgment is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")
    op.execute(f"""
CREATE OR REPLACE FUNCTION label_consent_append_only() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN
    IF NEW.id <> OLD.id AND NEW.annotator_id <> OLD.annotator_id
       AND NEW.accepted_at = date_trunc('day', OLD.accepted_at, 'UTC')
       AND (to_jsonb(NEW) - ARRAY['id', 'annotator_id', 'accepted_at'])
         = (to_jsonb(OLD) - ARRAY['id', 'annotator_id', 'accepted_at'])
       AND {erased} THEN
      RETURN NEW;
    END IF;
  ELSIF TG_OP = 'DELETE' THEN
    IF EXISTS (SELECT 1 FROM label_annotator a WHERE a.id = OLD.annotator_id AND a.status = 'erased') THEN
      RETURN OLD;
    END IF;
  END IF;
  RAISE EXCEPTION 'label_consent is append-only' USING ERRCODE = 'integrity_constraint_violation';
END $$""")


def downgrade():
    raise RuntimeError("002a is forward-only; roll back by deploying the previous image and restoring "
                       "the pre-deploy database backup")

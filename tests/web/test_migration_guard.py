"""Migration 002 drops the 001 tables and must refuse while human judgments exist;
002a is forward-only and repairs what the 0.2.2 refresh race could leave behind."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
asyncpg = pytest.importorskip("asyncpg")
from labeling_support import alembic, query


def test_002_refuses_to_drop_judgments_without_the_override(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "001_labeling").returncode == 0
    corpus, item = uuid4(), uuid4()
    query(url, f"""
        INSERT INTO label_corpus (owner_id, id, name, sha256, source_uri, license)
          VALUES ('owner', '{corpus}', 'c', '{"a" * 64}', 'urn:test', 'test');
        INSERT INTO label_item (owner_id, corpus_id, id, ordinal, kind, payload, current_revision)
          VALUES ('owner', '{corpus}', '{item}', 0, 'pair', '{{}}', 1);
        INSERT INTO label_judgment (owner_id, corpus_id, item_id, revision, annotation_id, answer, lemma, irregular, created_at)
          VALUES ('owner', '{corpus}', '{item}', 1, '{uuid4()}', 'same', '', false, now());""", script=True)
    for value in (None, "false", "TRUE", "1"):
        refused = alembic(url, "upgrade", "head", allow_drop=value)
        assert refused.returncode != 0
        assert "002 drops label_* tables; export and set LABELING_MIGRATION_ALLOW_DROP=true" in refused.stderr
        assert [tuple(r) for r in query(url, "SELECT owner_id, answer FROM label_judgment")] == [("owner", "same")]
        assert query(url, "SELECT version_num FROM alembic_version")[0][0] == "001_labeling"
    allowed = alembic(url, "upgrade", "head", allow_drop="true")
    assert allowed.returncode == 0, allowed.stderr
    assert query(url, "SELECT count(*) FROM label_judgment")[0][0] == 0
    assert query(url, "SELECT value::text FROM label_setting WHERE key = 'accepting_judgments'")[0][0] == "true"
    assert alembic(url, "check").returncode == 0


def test_002_runs_on_an_empty_database_and_downgrades(scratch_database):
    url = scratch_database
    upgraded = alembic(url, "upgrade", "002_shared_corpus")
    assert upgraded.returncode == 0, upgraded.stderr
    assert alembic(url, "downgrade", "001_labeling").returncode == 0
    columns = {r[0] for r in query(url, "SELECT column_name FROM information_schema.columns "
                                        "WHERE table_name = 'label_judgment'")}
    assert "owner_id" in columns and "annotator_id" not in columns
    assert alembic(url, "upgrade", "head").returncode == 0


def test_002a_clears_raced_emails_and_is_forward_only(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "002_shared_corpus").returncode == 0
    # What the 0.2.2 race could leave: an erased profile with the token's email written back.
    erased, active = uuid4(), uuid4()
    query(url, f"""
        INSERT INTO label_annotator (id, subject, email, email_verified, status)
          VALUES ('{erased}', NULL, 'raced@example.org', true, 'erased'),
                 ('{active}', 'subject-1', 'kept@example.org', true, 'active');""", script=True)
    upgraded = alembic(url, "upgrade", "002a_v1_followups")
    assert upgraded.returncode == 0, upgraded.stderr
    rows = {r[0]: (r[1], r[2]) for r in query(url, "SELECT id, email, email_verified FROM label_annotator")}
    assert rows == {erased: (None, False), active: ("kept@example.org", True)}
    # From now on an erased row cannot hold an email at all.
    with pytest.raises(asyncpg.CheckViolationError):
        query(url, f"UPDATE label_annotator SET email = 'x@example.org' WHERE id = '{erased}'", script=True)
    refused = alembic(url, "downgrade", "002_shared_corpus")
    assert refused.returncode != 0 and "002a is forward-only" in refused.stderr
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == "002a_v1_followups"

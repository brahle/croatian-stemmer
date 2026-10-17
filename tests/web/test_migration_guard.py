"""Migration 002 drops the 001 tables; it must refuse while human judgments exist."""
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
asyncpg = pytest.importorskip("asyncpg")
from labeling_support import database_url_for_tests

ROOT = Path(__file__).resolve().parents[2]


def alembic(url, *args, allow_drop=None):
    env = {k: v for k, v in os.environ.items() if k != "LABELING_MIGRATION_ALLOW_DROP"}
    env["LABELING_DATABASE_URL"] = url
    if allow_drop is not None:
        env["LABELING_MIGRATION_ALLOW_DROP"] = allow_drop
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=120)


@pytest.fixture
def scratch_database():
    """A throwaway database next to the test database (needs CREATEDB), dropped afterwards."""
    import asyncio
    dsn = database_url_for_tests()
    if not dsn:
        pytest.skip("Set LABELING_TEST_DATABASE_URL to a migrated, isolated PostgreSQL test database")
    base, _ = dsn.rsplit("/", 1)
    name = f"labeling_guard_{uuid4().hex[:12]}_test"
    plain = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)

    async def admin(statement):
        connection = await asyncpg.connect(plain)
        try:
            await connection.execute(statement)
        finally:
            await connection.close()
    try:
        asyncio.run(admin(f'CREATE DATABASE "{name}"'))
    except asyncpg.InsufficientPrivilegeError:
        pytest.skip("the test role cannot CREATE DATABASE; the migration guard test needs a scratch database")
    yield f"{base}/{name}"
    asyncio.run(admin(f'DROP DATABASE "{name}" WITH (FORCE)'))


def query(url, statement, script=False):
    import asyncio

    async def run():
        connection = await asyncpg.connect(url.replace("postgresql+asyncpg://", "postgresql://", 1))
        try:
            return await (connection.execute if script else connection.fetch)(statement)
        finally:
            await connection.close()
    return asyncio.run(run())


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
    upgraded = alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert alembic(url, "downgrade", "001_labeling").returncode == 0
    columns = {r[0] for r in query(url, "SELECT column_name FROM information_schema.columns "
                                        "WHERE table_name = 'label_judgment'")}
    assert "owner_id" in columns and "annotator_id" not in columns
    assert alembic(url, "upgrade", "head").returncode == 0

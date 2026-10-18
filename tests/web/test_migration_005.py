"""Migration 005 (0.3.4): the queue's `reserve` flag, backfilled from the item payloads; a
downgrade that refuses while reserve items exist; and the app's refusal to start on a
schema newer than it knows."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import alembic, query

ROOT = Path(__file__).resolve().parents[2]


def seed(url, gold=False):
    owner, corpus, plain, reserve = uuid4(), uuid4(), uuid4(), uuid4()
    query(url, f"""
        INSERT INTO label_annotator (id, subject, status) VALUES ('{owner}', 'so', 'active');
        INSERT INTO label_corpus (id, name, sha256, source_uri, license, created_by)
          VALUES ('{corpus}', 'c', '{"a" * 64}', 'urn:test', 'CC BY-SA 4.0', '{owner}');
        INSERT INTO label_item (corpus_id, id, ordinal, kind, payload) VALUES
          ('{corpus}', '{plain}', 0, 'lemma', '{{"sampling_stratum": "word_suggestion"}}'),
          ('{corpus}', '{reserve}', 1, 'lemma', '{{"sampling_stratum": "gold_reserve_lemma_decoy"}}');
        INSERT INTO label_item_state (corpus_id, item_id, kind)
          SELECT corpus_id, id, kind FROM label_item;""", script=True)
    if gold:
        event = query(url, f"""INSERT INTO label_trust_event (kind, corpus_id, item_id, details)
            VALUES ('gold.set', '{corpus}', '{reserve}', '{{"pool": "audit"}}') RETURNING id""")[0][0]
        query(url, f"""INSERT INTO label_gold (corpus_id, item_id, kind, pool, answer, lemma, source,
            suggestion_agrees, status, last_event_id) VALUES ('{corpus}', '{reserve}', 'lemma', 'audit', 'confirmed',
            'kuća', 'hr500k', false, 'active', {event})""")
    return plain, reserve


def test_005_backfills_reserve_items_and_round_trips(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "004_two_vote_params").returncode == 0
    plain, reserve = seed(url)
    upgraded = alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    flags = {r[0]: r[1] for r in query(url, "SELECT item_id, reserve FROM label_item_state")}
    assert flags == {plain: False, reserve: True}
    assert alembic(url, "check").returncode == 0


def test_005_downgrade_refuses_while_reserve_items_exist(scratch_database, monkeypatch):
    url = scratch_database
    assert alembic(url, "upgrade", "004_two_vote_params").returncode == 0
    plain, reserve = seed(url, gold=True)
    assert alembic(url, "upgrade", "005_gold_reserve").returncode == 0
    refused = alembic(url, "downgrade", "004_two_vote_params")
    assert refused.returncode != 0 and "LABELING_MIGRATION_RETIRE_RESERVE" in refused.stderr
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == "005_gold_reserve"
    monkeypatch.setenv("LABELING_MIGRATION_RETIRE_RESERVE", "true")
    allowed = alembic(url, "downgrade", "004_two_vote_params")
    assert allowed.returncode == 0, allowed.stderr
    status = {r[0]: r[1] for r in query(url, "SELECT id, status FROM label_item")}
    assert status == {plain: "active", reserve: "retired"}  # 0.3.3 never serves a retired item
    assert query(url, "SELECT status FROM label_gold")[0][0] == "retired"
    events = [(r[0], json.loads(r[1])) for r in query(
        url, "SELECT kind, details #>> '{}' FROM label_trust_event ORDER BY id")]
    assert events[-1] == ("gold.retired", {"reason": "rollback"})
    columns = {r[0] for r in query(url, "SELECT column_name FROM information_schema.columns "
                                        "WHERE table_name = 'label_item_state'")}
    assert "reserve" not in columns
    assert alembic(url, "upgrade", "head").returncode == 0


def test_the_schema_guard_knows_every_migration():
    from croatian_stemmer.labeling.web.api import SCHEMA_REVISIONS
    found = set()
    for path in (ROOT / "migrations" / "versions").glob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("revision = "):
                found.add(line.split("=", 1)[1].strip().strip('"'))
    assert set(SCHEMA_REVISIONS) == found


@pytest.mark.asyncio
async def test_the_app_refuses_a_schema_newer_than_it_knows(fresh_api):
    from croatian_stemmer.labeling.web.api import check_schema
    api = await fresh_api()
    assert await check_schema(api.app.state.engine) == "006_lexicon_provenance"
    await api.sql("UPDATE alembic_version SET version_num = '999_future'")
    with pytest.raises(RuntimeError, match="999_future"):
        await check_schema(api.app.state.engine)
    with pytest.raises(RuntimeError, match="does not know"):
        async with api.app.router.lifespan_context(api.app):
            pass


def test_006_adds_lexicon_provenance_and_refuses_to_drop_it(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "head").returncode == 0
    owner = uuid4()
    query(url, f"""
        INSERT INTO label_annotator (id, subject, status) VALUES ('{owner}', 'so', 'active');
        INSERT INTO label_corpus (id, name, sha256, source_uri, license, lexicon_uri, lexicon_license, created_by)
          VALUES ('{uuid4()}', 'w', '{"b" * 64}', 'urn:text', 'CC0 1.0', 'urn:lexicon', 'CC BY-SA 4.0',
                  '{owner}');""", script=True)
    refused = alembic(url, "downgrade", "005_gold_reserve")
    assert refused.returncode != 0 and "lexicon provenance" in refused.stderr
    query(url, "DELETE FROM label_corpus")
    assert alembic(url, "downgrade", "005_gold_reserve").returncode == 0
    assert alembic(url, "upgrade", "head").returncode == 0

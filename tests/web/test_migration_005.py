"""Migration 005 (0.3.4): the queue's `reserve` flag, backfilled from the item payloads,
and its downgrade."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import alembic, query


def test_005_backfills_reserve_items_and_round_trips(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "004_two_vote_params").returncode == 0
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
    upgraded = alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    flags = {r[0]: r[1] for r in query(url, "SELECT item_id, reserve FROM label_item_state")}
    assert flags == {plain: False, reserve: True}
    assert alembic(url, "check").returncode == 0
    assert alembic(url, "downgrade", "004_two_vote_params").returncode == 0
    columns = {r[0] for r in query(url, "SELECT column_name FROM information_schema.columns "
                                        "WHERE table_name = 'label_item_state'")}
    assert "reserve" not in columns
    assert alembic(url, "upgrade", "head").returncode == 0

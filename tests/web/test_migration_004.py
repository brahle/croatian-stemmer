"""Migration 004 (0.3.1 parameters): moves a populated 003 database from the 0.3.0 defaults
to the 0.3.1 defaults with a `params.changed` event, adds only the vote floor to chosen
parameters, and round-trips through its downgrade."""
import importlib.util
import json
from pathlib import Path
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import alembic, query
from test_migration_003 import seed_v1

from croatian_stemmer.labeling.scoring import DEFAULT_PARAMS, params_sha256, validate_params

PATH = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "004_two_vote_params.py"


def migration():
    spec = importlib.util.spec_from_file_location("migration_004", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = migration()


def stored(url):
    return json.loads(query(url, "SELECT value #>> '{}' FROM label_setting WHERE key = 'scoring_params'")[0][0])


def events(url):
    return [(r["actor_id"], json.loads(r["details"])) for r in query(
        url, "SELECT actor_id, details #>> '{}' AS details FROM label_trust_event WHERE kind = 'params.changed' "
             "ORDER BY id")]


def at_003_with_030_defaults(url):
    """A database as 0.3.0 left it: V1 rows, migration 003 with the 0.3.0 defaults, and a
    few trust-system rows written after it."""
    assert alembic(url, "upgrade", "002a_v1_followups").returncode == 0
    ids = seed_v1(url)
    upgraded = alembic(url, "upgrade", "003_trust")
    assert upgraded.returncode == 0, upgraded.stderr
    # 003 stores the DEFAULT_PARAMS of the code that runs it; 0.3.0 stored these.
    query(url, f"UPDATE label_setting SET value = '{json.dumps(M.DEFAULTS_0_3_0)}'::jsonb "
               f"WHERE key = 'scoring_params'", script=True)
    query(url, f"""
        INSERT INTO label_trust_event (kind, annotator_id, details)
          VALUES ('anchor.granted', '{ids["active"]}', '{{"trusted_id": 1}}');
        INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular, item_revision,
                                    client_version, created_at)
          VALUES ('{uuid4()}', '{ids["corpus"]}', '{ids["items"][2]}', '{ids["active"]}', 1, 'same', false, 1,
                  '0.3.0', now());""", script=True)
    return ids


def test_the_frozen_parameter_sets():
    assert M.DEFAULTS_0_3_1 == validate_params(DEFAULT_PARAMS), "a change of DEFAULT_PARAMS needs its own migration"
    # The 0.3.0 defaults: today's without the new key and with the old new-tier ceiling.
    old = {k: v for k, v in validate_params(DEFAULT_PARAMS).items() if k != M.FLOOR}
    assert M.DEFAULTS_0_3_0 == {**old, "theta_max": {**old["theta_max"], "new": 0.75}}
    assert M.params_sha256(M.DEFAULTS_0_3_0) == params_sha256(M.DEFAULTS_0_3_0)
    assert M.params_sha256(M.DEFAULTS_0_3_1) == params_sha256(validate_params(DEFAULT_PARAMS))


def valid(url):
    """What the 0.3.1 app reads must validate (it refuses a set without the new key)."""
    return validate_params(stored(url))


def test_004_moves_untouched_030_defaults_and_round_trips(scratch_database):
    url = scratch_database
    at_003_with_030_defaults(url)
    before = query(url, "SELECT max(id) FROM label_trust_event")[0][0]
    upgraded = alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert alembic(url, "check").returncode == 0
    assert valid(url) == validate_params(DEFAULT_PARAMS)
    assert stored(url)["theta_max"]["new"] == 0.78 and stored(url)["resolve_vote_min_theta"] == 0.70
    assert events(url) == [(None, {"old_sha256": params_sha256(M.DEFAULTS_0_3_0),
                                   "new_sha256": params_sha256(validate_params(DEFAULT_PARAMS)),
                                   "diff": ["resolve_vote_min_theta", "theta_max.new"],
                                   "reason": M.UPGRADE_REASON})]
    # The event is a journal row like any other: stamped after everything before it.
    assert query(url, "SELECT id FROM label_trust_event WHERE kind = 'params.changed'")[0][0] > before
    assert query(url, "SELECT updated_by FROM label_setting WHERE key = 'scoring_params'")[0][0] is None

    # The downgrade (before rolling back to the 0.3.0 image) restores the 0.3.0 defaults ...
    down = alembic(url, "downgrade", "003_trust")
    assert down.returncode == 0, down.stderr
    assert stored(url) == M.DEFAULTS_0_3_0
    assert [d["reason"] for _, d in events(url)] == [M.UPGRADE_REASON, M.DOWNGRADE_REASON]
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == "003_trust"
    # ... and upgrading again moves them forward again.
    assert alembic(url, "upgrade", "head").returncode == 0
    assert valid(url) == validate_params(DEFAULT_PARAMS)
    assert [d["reason"] for _, d in events(url)] == [M.UPGRADE_REASON, M.DOWNGRADE_REASON, M.UPGRADE_REASON]


def test_004_adds_only_the_floor_to_chosen_parameters(scratch_database):
    url = scratch_database
    at_003_with_030_defaults(url)
    curator = query(url, "SELECT id FROM label_annotator WHERE status = 'active' LIMIT 1")[0][0]
    # The curator once changed something and changed it back: equal to the 0.3.0 defaults, but chosen.
    query(url, f"INSERT INTO label_trust_event (actor_id, kind, details) VALUES ('{curator}', 'params.changed', "
               f"'{{\"diff\": [\"resolve_confidence\"]}}')", script=True)
    assert alembic(url, "upgrade", "head").returncode == 0
    assert valid(url) == {**M.DEFAULTS_0_3_0, "resolve_vote_min_theta": 0.70}  # the 0.75 ceiling stays
    assert [d.get("diff") for _, d in events(url)][1:] == [["resolve_vote_min_theta"]]
    assert events(url)[1][1]["reason"] == M.FLOOR_REASON
    # The downgrade removes only what 0.3.0 cannot read.
    assert alembic(url, "downgrade", "003_trust").returncode == 0
    assert stored(url) == M.DEFAULTS_0_3_0 and events(url)[-1][1]["reason"] == M.DOWNGRADE_FLOOR_REASON


def test_004_keeps_other_values(scratch_database):
    url = scratch_database
    at_003_with_030_defaults(url)
    custom = {**M.DEFAULTS_0_3_0, "resolve_confidence": 0.96}
    query(url, f"UPDATE label_setting SET value = '{json.dumps(custom)}'::jsonb WHERE key = 'scoring_params'",
          script=True)
    assert alembic(url, "upgrade", "head").returncode == 0
    assert valid(url) == {**custom, "resolve_vote_min_theta": 0.70}
    assert [(d["diff"], d["reason"]) for _, d in events(url)] == [(["resolve_vote_min_theta"], M.FLOOR_REASON)]
    # A curator then sets exactly the 0.3.1 defaults by hand: the downgrade keeps them, minus the key.
    query(url, f"UPDATE label_setting SET value = '{json.dumps(M.DEFAULTS_0_3_1)}'::jsonb "
               f"WHERE key = 'scoring_params'", script=True)
    assert alembic(url, "downgrade", "003_trust").returncode == 0
    assert stored(url) == {k: v for k, v in M.DEFAULTS_0_3_1.items() if k != M.FLOOR}


def test_004_on_an_empty_database(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "head").returncode == 0
    # 003 already stores the current defaults; 004 has nothing to do.
    assert valid(url) == validate_params(DEFAULT_PARAMS) and events(url) == []
    assert query(url, "SELECT version_num FROM alembic_version")[0][0] == "006_lexicon_provenance"

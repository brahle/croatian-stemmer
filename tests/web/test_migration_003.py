"""Migration 003 (trust system): forward-only, keeps V1 data, backfills the queue and
the membership journal, stamps every later journal row, and keeps the V1 exceptions
to the append-only rules while refusing everything else."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
asyncpg = pytest.importorskip("asyncpg")
from labeling_support import alembic, query


def seed_v1(url):
    """Annotators in every status, a corpus with three items, V1 judgments and consents."""
    a, q, b, e, n = (uuid4() for _ in range(5))
    corpus, i1, i2, i3 = uuid4(), uuid4(), uuid4(), uuid4()
    payload = '{"kind": "pair"}'
    query(url, f"""
        INSERT INTO label_annotator (id, subject, status) VALUES
          ('{a}', 'sa', 'active'), ('{q}', 'sq', 'quarantined'), ('{b}', 'sb', 'blocked'),
          ('{e}', NULL, 'erased'), ('{n}', NULL, 'erased');
        INSERT INTO label_admin_event (kind, target, details) VALUES
          ('annotator.status', '{e}', '{{"from": "active", "to": "blocked", "reason": "spam"}}'),
          ('erasure.requested', '{e}', '{{"keycloak_user_id": "kc-1"}}');
        INSERT INTO label_corpus (id, name, sha256, source_uri, license, labels_license, status, created_by)
          VALUES ('{corpus}', 'c', '{"a" * 64}', 'urn:test', 'CC BY-SA 4.0', 'CC BY-SA 4.0', 'published', '{a}');
        INSERT INTO label_item (corpus_id, id, ordinal, kind, payload) VALUES
          ('{corpus}', '{i1}', 0, 'pair', '{payload}'), ('{corpus}', '{i2}', 1, 'pair', '{payload}'),
          ('{corpus}', '{i3}', 2, 'pair', '{payload}');
        INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular, item_revision,
                                    client_version, elapsed_ms, created_at) VALUES
          ('{uuid4()}', '{corpus}', '{i1}', '{a}', 1, 'same', false, 1, '0.2.3', 900, now()),
          ('{uuid4()}', '{corpus}', '{i1}', '{q}', 1, 'same', false, 1, '0.2.3', 900, now()),
          ('{uuid4()}', '{corpus}', '{i1}', '{b}', 1, 'same', false, 1, '0.2.3', 900, now()),
          ('{uuid4()}', '{corpus}', '{i1}', '{n}', 1, 'different', false, 1, '0.2.3', NULL, date_trunc('day', now())),
          ('{uuid4()}', '{corpus}', '{i2}', '{a}', 1, 'same', false, 1, '0.2.3', 900, now()),
          ('{uuid4()}', '{corpus}', '{i2}', '{a}', 2, 'unsure', false, 1, '0.2.3', 900, now());
        INSERT INTO label_consent (annotator_id, document, version, locale, age_confirmed, age_threshold, ui_version)
          VALUES ('{a}', 'privacy', '1.2', 'hr', true, 18, '0.2.3');""", script=True)
    return {"active": a, "quarantined": q, "blocked": b, "erased_blocked": e, "receiver": n,
            "corpus": corpus, "items": (i1, i2, i3)}


def refused(url, statement):
    with pytest.raises(asyncpg.PostgresError) as exc:
        query(url, statement, script=True)
    assert "append-only" in str(exc.value), statement


def test_003_backfills_and_keeps_the_v1_exceptions(scratch_database):
    url = scratch_database
    assert alembic(url, "upgrade", "002a_v1_followups").returncode == 0
    ids = seed_v1(url)
    upgraded = alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert alembic(url, "check").returncode == 0

    # The queue matches V1's definite_votes(): the blocked voter is left out, the
    # quarantined one and the erased receiver count, a latest `unsure` does not.
    i1, i2, i3 = ids["items"]
    state = {r["item_id"]: (r["n_low"], r["priority"], r["state"], r["run_id"]) for r in query(
        url, "SELECT item_id, n_low, priority, state, run_id FROM label_item_state")}
    assert state == {i1: (3, 0.5, "open", None), i2: (0, 1.0, "open", None), i3: (0, 1.0, "open", None)}
    audit = query(url, "SELECT item_id, seq, audit_sample, review_sample, audit_rank FROM label_item_audit")
    assert {r["item_id"] for r in audit} == {i1, i2, i3}
    assert all(r["seq"] is None and not (r["audit_sample"] and r["review_sample"]) for r in audit)
    settings = {r["key"]: r["value"] for r in query(url, "SELECT key, value #>> '{}' AS value FROM label_setting")}
    assert settings["scoring_enabled"] == "false"
    assert len(settings["audit_key"]) == 64 and int(settings["audit_key"], 16) >= 0
    from croatian_stemmer.labeling.scoring import DEFAULT_PARAMS, validate_params
    import json
    assert json.loads(settings["scoring_params"]) == validate_params(DEFAULT_PARAMS)
    # The backfilled bits follow the keyed rule the import route uses.
    from croatian_stemmer.labeling.web.scheduler import item_bits
    for row in audit:
        assert item_bits(settings["audit_key"], ids["corpus"], row["item_id"], 10, 2) == (
            row["audit_sample"], row["review_sample"], row["audit_rank"])
    # Nothing is written to gold, the trusted list or the run tables; V1 rows keep seq NULL.
    for table in ("label_gold", "label_trusted_email", "label_anchor", "label_trust_event", "label_scoring_run"):
        assert query(url, f"SELECT count(*) FROM {table}")[0][0] == 0, table
    assert query(url, "SELECT count(*) FROM label_judgment WHERE seq IS NOT NULL")[0][0] == 0

    # Every later journal row is stamped from one sequence, without naming the column.
    a, corpus = ids["active"], ids["corpus"]
    query(url, f"""
        INSERT INTO label_consent (annotator_id, document, version, locale, age_confirmed, age_threshold, ui_version)
          VALUES ('{a}', 'terms', '1.1', 'hr', true, 18, '0.3.0');
        INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular, item_revision,
                                    client_version, created_at)
          VALUES ('{uuid4()}', '{corpus}', '{i3}', '{a}', 1, 'same', false, 1, '0.3.0', now());
        INSERT INTO label_admin_event (kind, target, details) VALUES ('setting.update', 'x', '{{}}');
        INSERT INTO label_trust_event (kind, details) VALUES ('params.changed', '{{}}');""", script=True)
    stamped = [r[0] for r in query(url, """
        SELECT seq FROM label_consent WHERE seq IS NOT NULL UNION ALL SELECT seq FROM label_judgment WHERE seq IS NOT NULL
        UNION ALL SELECT seq FROM label_admin_event WHERE seq IS NOT NULL UNION ALL SELECT id FROM label_trust_event""")]
    assert sorted(stamped) == [1, 2, 3, 4]

    # Someone erased under V1 already has the V2 redaction: no reason on their status events; the
    # erasure request keeps its Keycloak id until the curator completes it.
    e = ids["erased_blocked"]
    assert query(url, f"SELECT details #>> '{{}}' FROM label_admin_event WHERE kind = 'annotator.status' "
                      f"AND target = '{e}'")[0][0] == '{"to": "blocked", "from": "active"}'
    assert query(url, f"SELECT details ->> 'keycloak_user_id' FROM label_admin_event WHERE kind = 'erasure.requested' "
                      f"AND target = '{e}'")[0][0] == "kc-1"

    # The V1 statements 003 must still permit.
    q, e, n = ids["quarantined"], ids["erased_blocked"], ids["receiver"]
    query(url, f"UPDATE label_annotator SET status = 'active' WHERE id = '{q}'", script=True)
    query(url, f"UPDATE label_judgment SET elapsed_ms = NULL WHERE annotator_id = '{q}'", script=True)
    m = uuid4()
    query(url, f"INSERT INTO label_annotator (id, status) VALUES ('{m}', 'erased')", script=True)
    query(url, f"""UPDATE label_judgment SET id = gen_random_uuid(), annotator_id = '{m}',
                   created_at = date_trunc('day', created_at, 'UTC'), elapsed_ms = NULL
                   WHERE annotator_id = '{q}'""", script=True)
    query(url, f"UPDATE label_admin_event SET details = '{{}}' WHERE kind = 'erasure.requested' AND target = '{e}'",
          script=True)
    # The erased subject's events may be redacted to the allowlisted keys, and only that.
    query(url, f"UPDATE label_admin_event SET details = label_redact_details(kind, details) "
               f"WHERE kind = 'annotator.status' AND target = '{e}'", script=True)
    assert query(url, f"SELECT details #>> '{{}}' FROM label_admin_event WHERE kind = 'annotator.status' "
                      f"AND target = '{e}'")[0][0] == '{"to": "blocked", "from": "active"}'

    # Anything else on a journal raises.
    for statement in (f"UPDATE label_judgment SET answer = 'different' WHERE annotator_id = '{a}'",
                      f"DELETE FROM label_judgment WHERE annotator_id = '{a}'",
                      f"UPDATE label_judgment SET seq = 99 WHERE annotator_id = '{a}'",
                      f"UPDATE label_consent SET version = '9' WHERE annotator_id = '{a}'",
                      "UPDATE label_admin_event SET details = '{\"x\": 1}' WHERE kind = 'setting.update'",
                      "DELETE FROM label_admin_event WHERE kind = 'setting.update'",
                      "UPDATE label_trust_event SET details = '{\"a\": 1}'",
                      "DELETE FROM label_trust_event",
                      "TRUNCATE label_trust_event",
                      f"UPDATE label_item_audit SET audit_sample = NOT audit_sample WHERE item_id = '{i1}'",
                      f"DELETE FROM label_item_audit WHERE item_id = '{i1}'",
                      "TRUNCATE label_item_audit CASCADE"):
        refused(url, statement)
    # An active subject's events cannot be redacted.
    query(url, f"INSERT INTO label_admin_event (kind, target, details) VALUES "
               f"('annotator.status', '{a}', '{{\"from\": \"active\", \"to\": \"quarantined\", \"reason\": \"x\"}}')",
          script=True)
    refused(url, f"UPDATE label_admin_event SET details = label_redact_details(kind, details) WHERE target = '{a}'")
    refused(url, f"UPDATE label_trust_event SET details = label_redact_details(kind, details)")

    downgrade = alembic(url, "downgrade", "002a_v1_followups")
    assert downgrade.returncode != 0 and "003 is forward-only" in downgrade.stderr


def test_003_on_an_empty_database(scratch_database):
    upgraded = alembic(scratch_database, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert query(scratch_database, "SELECT count(*) FROM label_item_state")[0][0] == 0
    assert query(scratch_database, "SELECT version_num FROM alembic_version")[0][0] == "004_two_vote_params"

"""Append-only invariants enforced by triggers, not only by application code."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from sqlalchemy.exc import DBAPIError
from labeling_support import answer, answer_path

pytestmark = pytest.mark.asyncio


async def refused(api, statement, **params):
    with pytest.raises(DBAPIError) as exc:
        await api.sql(statement, **params)
    assert "append-only" in str(exc.value)


async def test_judgments_are_append_only_except_erasing_elapsed_time(api):
    rows = await api.imported()
    await api.consent("alice")
    payload = answer()
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=payload)).status_code == 200
    jid = payload["request_id"]
    for statement in ("UPDATE label_judgment SET answer = 'different' WHERE id = :id",
                      "UPDATE label_judgment SET elapsed_ms = 1 WHERE id = :id",
                      "UPDATE label_judgment SET elapsed_ms = NULL, lemma = 'x' WHERE id = :id",
                      "DELETE FROM label_judgment WHERE id = :id"):
        await refused(api, statement, id=jid)
    await refused(api, "TRUNCATE label_judgment CASCADE")
    await api.sql("UPDATE label_judgment SET elapsed_ms = NULL WHERE id = :id", id=jid)
    row = (await api.sql("SELECT answer, elapsed_ms FROM label_judgment WHERE id = :id", id=jid)).one()
    assert tuple(row) == ("same", None)


async def test_consents_are_append_only(api):
    await api.consent("alice")
    me = await api.annotator_id("alice")
    await refused(api, "UPDATE label_consent SET version = '0' WHERE annotator_id = :a", a=me)
    await refused(api, "DELETE FROM label_consent WHERE annotator_id = :a", a=me)
    await refused(api, "TRUNCATE label_consent CASCADE")


async def test_admin_events_only_allow_clearing_details(api):
    rows = await api.imported(publish=None)
    event = (await api.sql("SELECT id FROM label_admin_event WHERE kind = 'corpus.import' AND target = :t",
                           t=rows[0]["corpus_id"])).scalar_one()
    await refused(api, "UPDATE label_admin_event SET kind = 'x' WHERE id = :i", i=event)
    await refused(api, "UPDATE label_admin_event SET details = '{\"a\": 1}' WHERE id = :i", i=event)
    await refused(api, "DELETE FROM label_admin_event WHERE id = :i", i=event)
    await api.sql("UPDATE label_admin_event SET details = '{}' WHERE id = :i", i=event)

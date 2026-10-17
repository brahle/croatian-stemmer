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


async def receivers(api):
    """An erased, subject-less annotator (what erasure moves rows to) and an active one."""
    erased = (await api.sql("INSERT INTO label_annotator (status) VALUES ('erased') RETURNING id")).scalar_one()
    assert (await api.request("GET", "/api/me", "bob")).status_code == 200
    return erased, await api.annotator_id("bob")


def move_judgment(time="date_trunc('day', created_at, 'UTC')", elapsed="NULL", extra=""):
    return (f"UPDATE label_judgment SET id = gen_random_uuid(), annotator_id = :to, created_at = {time}, "
            f"elapsed_ms = {elapsed}{extra} WHERE id = :id")


async def test_judgments_may_only_be_moved_as_erasure_moves_them(api):
    rows = await api.imported()
    await api.consent("alice")
    payload = answer()
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=payload)).status_code == 200
    jid, alice = payload["request_id"], await api.annotator_id("alice")
    erased, bob = await receivers(api)
    for statement, to in (
            (move_judgment(), bob),  # only to an erased, subject-less annotator
            (move_judgment(extra=", answer = 'different'"), erased),  # nothing else may change
            (move_judgment(time="created_at"), erased),  # the time is cut to the day
            (move_judgment(time="created_at - interval '1 day'"), erased),
            (move_judgment(elapsed="elapsed_ms"), erased),  # the timing goes
            ("UPDATE label_judgment SET annotator_id = :to, created_at = date_trunc('day', created_at, 'UTC'), "
             "elapsed_ms = NULL WHERE id = :id", erased)):  # the row id must change
        await refused(api, statement, to=to, id=jid)
    # The annotator is active: its judgments cannot be deleted.
    await refused(api, "DELETE FROM label_judgment WHERE annotator_id = :a", a=alice)
    moved = (await api.sql(move_judgment() + " RETURNING id, created_at", to=erased, id=jid)).one()
    assert str(moved.id) != jid and (moved.created_at.hour, moved.created_at.minute) == (0, 0)
    # Rows of an erased annotator may be deleted (erasing a blocked person); TRUNCATE never.
    await refused(api, "TRUNCATE label_judgment CASCADE")
    await api.sql("DELETE FROM label_judgment WHERE id = :id", id=moved.id)


async def test_consents_may_only_be_moved_as_erasure_moves_them(api):
    await api.consent("alice")
    alice = await api.annotator_id("alice")
    erased, bob = await receivers(api)
    cid = (await api.sql("SELECT id FROM label_consent WHERE annotator_id = :a AND document = 'terms'",
                         a=alice)).scalar_one()
    move = ("UPDATE label_consent SET id = nextval(pg_get_serial_sequence('label_consent', 'id')), "
            "annotator_id = :to, accepted_at = {time}{extra} WHERE id = :id")
    day = "date_trunc('day', accepted_at, 'UTC')"
    for statement, to in ((move.format(time=day, extra=""), bob), (move.format(time=day, extra=", version = '9'"), erased),
                          (move.format(time="accepted_at", extra=""), erased),
                          ("UPDATE label_consent SET annotator_id = :to, accepted_at = date_trunc('day', accepted_at, "
                           "'UTC') WHERE id = :id", erased)):
        await refused(api, statement, to=to, id=cid)
    await refused(api, "DELETE FROM label_consent WHERE annotator_id = :a", a=alice)
    moved = (await api.sql(move.format(time=day, extra="") + " RETURNING id", to=erased, id=cid)).scalar_one()
    assert moved != cid
    await api.sql("DELETE FROM label_consent WHERE id = :id", id=moved)


async def test_admin_events_only_allow_clearing_details(api):
    rows = await api.imported(publish=None)
    event = (await api.sql("SELECT id FROM label_admin_event WHERE kind = 'corpus.import' AND target = :t",
                           t=rows[0]["corpus_id"])).scalar_one()
    await refused(api, "UPDATE label_admin_event SET kind = 'x' WHERE id = :i", i=event)
    await refused(api, "UPDATE label_admin_event SET details = '{\"a\": 1}' WHERE id = :i", i=event)
    await refused(api, "DELETE FROM label_admin_event WHERE id = :i", i=event)
    await api.sql("UPDATE label_admin_event SET details = '{}' WHERE id = :i", i=event)

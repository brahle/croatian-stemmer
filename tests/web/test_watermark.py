"""A commit-safe watermark (4.6.3): every journal seq at or below it belongs to a finished
transaction, and item membership is watermarked too."""
import asyncio
from datetime import date
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from sqlalchemy import text
from labeling_support import candidates, profiled

pytestmark = pytest.mark.asyncio

INSERT = text("""INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular,
                 item_revision, client_version, created_at)
                 VALUES (:id, :c, :i, :a, :r, 'same', false, 1, '0.3.0', now()) RETURNING seq""")


async def setup(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    alice = await profiled(api, "alice")
    return api, rows, alice


def values(row, annotator, revision=1):
    return {"id": uuid4(), "c": row["corpus_id"], "i": row["item_id"], "a": annotator, "r": revision}


async def test_the_barrier_waits_for_an_open_writer_and_the_run_includes_it(fresh_api):
    from croatian_stemmer.labeling.web.scoring_run import barrier, load_inputs
    api, rows, alice = await setup(fresh_api)
    engine = api.app.state.engine
    async with engine.connect() as writer:
        transaction = await writer.begin()
        seq = (await writer.execute(INSERT, values(rows[0], alice))).scalar_one()
        waiting = asyncio.create_task(barrier(engine))
        await asyncio.sleep(0.5)
        assert not waiting.done()  # the run cannot take a watermark past an unfinished writer
        await transaction.commit()
    watermark, day = await asyncio.wait_for(waiting, 10)
    assert watermark >= seq
    _, inputs = await load_inputs(engine, watermark, day)
    assert seq in [j["seq"] for j in inputs["judgments"]]


async def test_a_commit_after_the_barrier_waits_for_the_next_run(fresh_api):
    from croatian_stemmer.labeling.web.scoring_run import barrier, load_inputs
    api, rows, alice = await setup(fresh_api)
    engine = api.app.state.engine
    watermark, day = await barrier(engine)
    seq = (await api.sql(INSERT.text, **values(rows[0], alice))).scalar_one()
    assert seq > watermark
    _, inputs = await load_inputs(engine, watermark, day)  # the row is visible but above the watermark
    assert seq not in [j["seq"] for j in inputs["judgments"]]
    later, _ = await barrier(engine)
    _, inputs = await load_inputs(engine, later, day)
    assert seq in [j["seq"] for j in inputs["judgments"]]


async def test_rolled_back_rows_leave_gaps_and_unstamped_inserts_get_a_seq(fresh_api):
    from croatian_stemmer.labeling.web.scoring_run import barrier, load_inputs
    api, rows, alice = await setup(fresh_api)
    engine = api.app.state.engine
    async with engine.connect() as connection:
        transaction = await connection.begin()
        lost = (await connection.execute(INSERT, values(rows[0], alice))).scalar_one()
        await transaction.rollback()
    kept = (await api.sql(INSERT.text, **values(rows[0], alice))).scalar_one()
    assert kept > lost  # a gap, never reused
    watermark, day = await barrier(engine)
    _, inputs = await load_inputs(engine, watermark, day)
    assert [j["seq"] for j in inputs["judgments"]] == [kept]
    # V1 code never mentions seq; the trigger stamps every journal anyway.
    for table in ("label_consent", "label_admin_event", "label_item_audit"):
        assert (await api.sql(f"SELECT count(*) FROM {table} WHERE seq IS NULL")).scalar_one() == 0, table


async def test_membership_is_watermarked(fresh_api):
    from croatian_stemmer.labeling.web.scoring_run import barrier, load_inputs, run_once
    api, rows, alice = await setup(fresh_api)
    engine = api.app.state.engine
    watermark, day = await barrier(engine)
    later = await api.imported(candidates(pairs=2))
    _, inputs = await load_inputs(engine, watermark, day)
    members = {(i["corpus_id"], i["item_id"]) for i in inputs["items"]}
    assert (rows[0]["corpus_id"], rows[0]["item_id"]) in members
    assert (later[0]["corpus_id"], later[0]["item_id"]) not in members
    # A judgment on an item that is not a member at the watermark fails the run.
    corpus, item = rows[0]["corpus_id"], uuid4()
    await api.sql("INSERT INTO label_item (corpus_id, id, ordinal, kind, payload) VALUES (:c, :i, 99, 'pair', "
                  "CAST(:p AS jsonb))", c=corpus, i=item, p='{"sampling_stratum": "x"}')
    await api.sql(INSERT.text, **values({"corpus_id": corpus, "item_id": item}, alice))
    with pytest.raises(ValueError, match="outside the run's membership"):
        await run_once(api.app.state.ctx, as_of_day=date.today())
    failed = (await api.sql("SELECT status, error FROM label_scoring_run ORDER BY started_at DESC LIMIT 1")).one()
    assert failed.status == "failed" and "membership" in failed.error

"""Vote admission at answer time (4.9.2): only served items, per-item budgets per admission
group, the same count a run uses, and one response whatever the decision."""
import asyncio
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, profiled, score_now, scoring_on, unlimited

pytestmark = pytest.mark.asyncio


async def one_pair(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=1))
    await scoring_on(api)
    return api, rows[0]


async def admitted(api, row):
    return [(r.admitted, r.admission_group) for r in (await api.sql(
        "SELECT admitted, admission_group FROM label_judgment WHERE item_id = :i ORDER BY seq", i=row["item_id"])).all()]


async def queue(api, row):
    return (await api.sql("SELECT state, n_low, n_expert FROM label_item_state WHERE item_id = :i",
                          i=row["item_id"])).one()


async def status(api, name, to):
    r = await api.request("PUT", f"/api/admin/annotators/{await api.annotator_id(name)}/status", "curator", True,
                          json={"status": to, "reason": "test"})
    assert r.status_code == 200


async def test_an_item_never_served_cannot_be_answered(fresh_api):
    api, row = await one_pair(fresh_api)
    await profiled(api, "alice")
    r = await api.request("POST", answer_path(row), "alice", fetched=False, json=answer())
    assert r.status_code == 409 and r.json()["detail"] == {"code": "not_assigned"}
    assert await admitted(api, row) == []
    served = (await api.request("GET", f'/api/corpora/{row["corpus_id"]}/next', "alice")).json()["item"]
    assert served["candidate"]["item_id"] == row["item_id"]
    assert (await api.request("POST", answer_path(row), "alice", fetched=False, json=answer())).status_code == 200


async def test_ten_concurrent_first_answers_admit_exactly_five(fresh_api):
    api, row = await one_pair(fresh_api)
    names = [f"p{n}" for n in range(10)]
    for name in names:
        await profiled(api, name)
    results = await asyncio.gather(*(api.request("POST", answer_path(row), name, json=answer()) for name in names))
    assert {r.status_code for r in results} == {200}  # one response whatever the decision
    assert sorted(await admitted(api, row)) == [(False, "low")] * 5 + [(True, "low")] * 5
    # A revision inherits its first answer's decision and is always accepted; a replay returns the stored result.
    first = await api.request("GET", f'/api/corpora/{row["corpus_id"]}/items/{row["item_id"]}', "p0")
    revision = answer(first.json()["assignment"]["current_revision"], "different")
    assert (await api.request("POST", answer_path(row), "p0", json=revision)).status_code == 200
    again = await api.request("POST", answer_path(row), "p0", json=revision)
    assert again.status_code == 200 and again.json()["annotation_id"] == revision["request_id"]
    assert len(await admitted(api, row)) == 11


async def test_quarantined_votes_neither_count_nor_use_the_budget(fresh_api):
    api, row = await one_pair(fresh_api)
    for n in range(7):
        await profiled(api, f"q{n}")
        await status(api, f"q{n}", "quarantined")
        assert (await api.request("POST", answer_path(row), f"q{n}", json=answer())).status_code == 200
    assert {a for a, _ in await admitted(api, row)} == {False}
    await score_now(api)
    current = await queue(api, row)
    assert (current.state, current.n_low) == ("open", 0)


@pytest.mark.parametrize("excluded", ["quarantined", "blocked", "outside_cohort"])
async def test_a_freed_slot_is_refilled_and_the_cap_holds_through_every_change(fresh_api, excluded):
    """Five low voters fill the item; they become ineligible; the next run frees the item and
    five replacements are admitted; the five become eligible again: both the request-time
    count and the run's n_low stay five, the originals counted, the replacements kept."""
    api, row = await one_pair(fresh_api)
    first = [f"o{n}" for n in range(5)]
    for name in first:
        if excluded == "outside_cohort":
            await api.consent(name)  # the 0.2.3 gate only: not profiled, so not counted
        else:
            await profiled(api, name)
        assert (await api.request("POST", answer_path(row), name, json=answer())).status_code == 200
    if excluded != "outside_cohort":
        for name in first:
            await status(api, name, excluded)
    await score_now(api)
    assert (await queue(api, row)).n_low == 0
    second = [f"r{n}" for n in range(5)]
    for name in second:
        await profiled(api, name)
        served = (await api.request("GET", f'/api/corpora/{row["corpus_id"]}/next', name)).json()["item"]
        assert served and served["candidate"]["item_id"] == row["item_id"]
        assert (await api.request("POST", answer_path(row), name, fetched=False, json=answer())).status_code == 200
    replacements = (await api.sql("SELECT admitted FROM label_judgment j JOIN label_annotator a ON a.id = j.annotator_id "
                                  "WHERE j.item_id = :i AND a.subject = ANY(:s)", i=row["item_id"],
                                  s=[api.identity.subjects[n] for n in second])).scalars().all()
    assert replacements == [True] * 5
    # The originals become eligible again.
    for name in first:
        if excluded == "outside_cohort":
            await profiled(api, name)
        else:
            await status(api, name, "active")
    [(run_id, _)] = await score_now(api)
    assert (await queue(api, row)).n_low == 5
    from croatian_stemmer.labeling.web.scheduler import counted_now
    ctx = api.app.state.ctx
    async with ctx.sessions() as db, db.begin():
        used = await counted_now(db, await ctx.serving_params(db), row["corpus_id"], row["item_id"], 0, False, False)
    assert used == {"low": 5, "expert": 0}
    counted = (await api.sql("SELECT n_annotators FROM label_item_posterior WHERE run_id = :r AND item_id = :i",
                             r=run_id, i=row["item_id"])).scalar_one()
    assert counted == 5
    # A sixth low answer now is kept but not admitted.
    await profiled(api, "late")
    assert (await api.request("POST", answer_path(row), "late", json=answer())).status_code == 200
    assert (await api.sql("SELECT j.admitted FROM label_judgment j JOIN label_annotator a ON a.id = j.annotator_id "
                          "WHERE j.item_id = :i AND a.subject = :s", i=row["item_id"],
                          s=api.identity.subjects["late"])).scalar_one() is False


async def test_an_established_answer_uses_the_expert_slots(fresh_api):
    api, row = await one_pair(fresh_api)
    for n in range(5):
        await profiled(api, f"l{n}")
        assert (await api.request("POST", answer_path(row), f"l{n}", json=answer())).status_code == 200
    expert = await profiled(api, "expert")
    # The latest done run says `established` (the run's own tiers come from gold; this test
    # concerns only the admission group, which reads the latest run).
    run_id = uuid4()
    await api.sql("INSERT INTO label_scoring_run (id, scoring_version, params, params_sha256, watermark, as_of_day, "
                  "status, finished_at) VALUES (:r, '2.0', '{}'::jsonb, 'x', 0, current_date, 'done', now())", r=run_id)
    await api.sql("""INSERT INTO label_annotator_score (run_id, annotator_id, kind, tier, base_tier, qualified, alpha0,
                     beta0, gold_seen, gold_hits, disc_seen, disc_hits, wrong_sugg_seen, wrong_sugg_hits, soft_hits,
                     soft_misses, theta_mean, theta_lb_gold, weight, flags, n_definite, n_unsure, n_resolved_agree,
                     n_resolved_total) VALUES (:r, :a, 'pair', 'established', 'established', true, 4, 2, 0, 0, 30, 30,
                     5, 5, 0, 0, 0.9, 0.8, 2.2, '{}'::jsonb, 100, 0, 0, 0)""", r=run_id, a=expert)
    assert (await api.request("POST", answer_path(row), "expert", json=answer())).status_code == 200
    assert (await admitted(api, row))[-1] == (True, "expert")
    await score_now(api)
    current = await queue(api, row)
    assert (current.state, current.n_low, current.n_expert) == ("needs_expert", 5, 1)

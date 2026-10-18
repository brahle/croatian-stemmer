"""Known-answer items from every published corpus with gold, and corpus choice from the qualified
tier up while a kind's knowledge check is served."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, gold_line, make_anchor, profiled, scoring_on, unlimited, unsampled

pytestmark = pytest.mark.asyncio
KEY = "0f" * 32


async def keyed_api(fresh_api):
    api = unlimited(await fresh_api())
    await api.sql("UPDATE label_setting SET value = to_jsonb(CAST(:k AS text)) WHERE key = 'audit_key'", k=KEY)
    return api


async def with_gold(api, pairs=400, qualification=60, audit=140):
    """A corpus whose pair items include qualification and audit gold; returns (rows, gold, qualification ids)."""
    rows = await api.imported(candidates(pairs=pairs))
    free = await unsampled(api, [r for r in rows if r["kind"] == "pair"])
    lines = ([gold_line(r, pool="qualification") for r in free[:qualification]]
             + [gold_line(r) for r in free[qualification:qualification + audit]])
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})
    assert r.status_code == 200, r.text
    api.app.state.ctx.forget_settings()
    return rows, {r["item_id"] for r in free[:qualification + audit]}, {r["item_id"] for r in free[:qualification]}


async def set_tier(api, annotator, tier, base_tier=None, kind="pair"):
    """The latest done run gives the annotator this tier for the kind."""
    run_id = uuid4()
    await api.sql("INSERT INTO label_scoring_run (id, scoring_version, params, params_sha256, watermark, as_of_day, "
                  "status, finished_at) VALUES (:r, '2.0', '{}'::jsonb, 'x', 0, current_date, 'done', now())", r=run_id)
    await api.sql("""INSERT INTO label_annotator_score (run_id, annotator_id, kind, tier, base_tier, qualified, alpha0,
                     beta0, gold_seen, gold_hits, disc_seen, disc_hits, wrong_sugg_seen, wrong_sugg_hits, soft_hits,
                     soft_misses, theta_mean, theta_lb_gold, weight, flags, n_definite, n_unsure, n_resolved_agree,
                     n_resolved_total) VALUES (:r, :a, :k, :t, :b, true, 4, 2, 12, 12, 0, 0, 0, 0, 0, 0, 0.8, 0.7,
                     1.3, '{}'::jsonb, 12, 0, 0, 0)""", r=run_id, a=annotator, k=kind, t=tier, b=base_tier or tier)


async def me(api, name):
    r = await api.request("GET", "/api/me", name)
    assert r.status_code == 200, r.text
    return r.json()["corpus_choice"]


async def test_checks_come_from_a_corpus_with_gold_while_labelling_one_without(fresh_api):
    from croatian_stemmer.labeling.web.scheduler import keyed
    api = await keyed_api(fresh_api)
    plain = await api.imported(candidates(pairs=80))  # first published: /api/next serves its work first
    rows, gold, qualification = await with_gold(api)
    plain_id, gold_id = plain[0]["corpus_id"], rows[0]["corpus_id"]
    alice = await profiled(api, "alice")
    assert await me(api, "alice") == {"pair": "locked", "lemma": "open", "stem": "open"}
    # Below qualified a chosen corpus is refused; a kind without gold anywhere stays open.
    r = await api.request("GET", f"/api/corpora/{plain_id}/next", "alice", params={"kind": "pair"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "corpus_choice_locked"
    assert (await api.request("GET", f"/api/corpora/{plain_id}/next", "alice", params={"kind": "lemma"})).status_code == 200
    # "Any corpus": the knowledge check comes from the corpus with gold.
    for n in range(12):
        served = (await api.request("GET", "/api/next", "alice", params={"kind": "pair"})).json()
        item = served["item"]
        assert served["qualification"] == {"done": n, "of": 12}
        assert item["candidate"]["corpus_id"] == gold_id and item["candidate"]["item_id"] in qualification
        r = await api.request("POST", answer_path(item["candidate"]), "alice", fetched=False, json=answer())
        assert r.status_code == 200, r.text
    # Qualified: the chosen corpus is served, and its checks come from the other corpus at the keyed
    # positions, counted over every corpus's showings.
    await set_tier(api, alice, "qualified")
    assert (await me(api, "alice"))["pair"] == "open"
    checks = []
    for n in range(12, 72):
        r = await api.request("GET", f"/api/corpora/{plain_id}/next", "alice", params={"kind": "pair"})
        assert r.status_code == 200, r.text
        candidate = r.json()["item"]["candidate"]
        check = keyed(KEY, f"audit:{alice}:pair:{n}") % 100 < 10
        assert (candidate["corpus_id"], candidate["item_id"] in gold - qualification) == (
            (gold_id, True) if check else (plain_id, False)), n
        if check:
            checks.append(candidate)
        r = await api.request("POST", answer_path(candidate), "alice", fetched=False, json=answer())
        assert r.status_code == 200, r.text
    assert checks
    served = (await api.sql("SELECT sum(served_count) FROM label_gold WHERE pool = 'audit'")).scalar_one()
    assert served == len(checks)
    # The person's own history reaches a check from the other corpus: detail, "my items", progress.
    check = checks[0]
    r = await api.request("GET", f'/api/corpora/{gold_id}/items/{check["item_id"]}', "alice")
    assert r.status_code == 200 and r.json()["judgment"]["answer"] == "same"
    listed = (await api.request("GET", f"/api/corpora/{gold_id}/items", "alice",
                                params={"kind": "pair", "limit": 50})).json()["items"]
    assert {i["candidate"]["item_id"] for i in listed} >= {c["item_id"] for c in checks}
    progress = (await api.request("GET", f"/api/corpora/{gold_id}/progress", "alice")).json()
    assert progress["kinds"]["pair"]["reviewed"] == 12 + len(checks)


async def test_qualified_and_above_choose_a_quarantine_stays_silent(fresh_api):
    api = await keyed_api(fresh_api)
    rows, _, _ = await with_gold(api)
    corpus = rows[0]["corpus_id"]
    for name, tier, base in (("new", "new", None), ("qualified", "qualified", None),
                             ("established", "established", None), ("paused", "quarantined", "qualified"),
                             ("paused_new", "quarantined", "new")):
        annotator = await profiled(api, name)
        if name != "new":
            await set_tier(api, annotator, tier, base)
        r = await api.request("GET", f"/api/corpora/{corpus}/next", name, params={"kind": "pair"})
        locked = base == "new" or tier == "new"
        assert r.status_code == (403 if locked else 200), (name, r.text)
        assert (await me(api, name))["pair"] == ("locked" if locked else "open")
    await profiled(api, "fresh")
    assert (await api.request("GET", "/api/next", "fresh", params={"kind": "pair"})).status_code == 200
    # The anchor chooses; a curator does not on that account alone.
    await make_anchor(api, "owner")
    assert (await me(api, "owner"))["pair"] == "open"
    assert (await api.request("GET", f"/api/corpora/{corpus}/next", "owner", params={"kind": "pair"})).status_code == 200
    await profiled(api, "curator", curator=True)
    r = await api.request("GET", f"/api/corpora/{corpus}/next", "curator", True, params={"kind": "pair"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "corpus_choice_locked"


async def test_no_lock_without_a_served_knowledge_check(fresh_api):
    api = await keyed_api(fresh_api)
    rows = await api.imported(candidates(pairs=40))
    corpus = rows[0]["corpus_id"]
    await scoring_on(api)
    await profiled(api, "alice")
    # Scoring on but no gold anywhere: choice is open.
    assert await me(api, "alice") == {"pair": "open", "lemma": "open", "stem": "open"}
    assert (await api.request("GET", f"/api/corpora/{corpus}/next", "alice", params={"kind": "pair"})).status_code == 200
    # Audit gold without a qualification pool: no knowledge check is served, so nobody is locked out.
    other, _, _ = await with_gold(api, pairs=200, qualification=0)
    assert (await me(api, "alice"))["pair"] == "open"
    r = await api.request("GET", f'/api/corpora/{other[0]["corpus_id"]}/next', "alice", params={"kind": "pair"})
    assert r.status_code == 200, r.text
    # Gold in a draft corpus is neither served nor a reason to lock.
    draft = await api.imported(candidates(pairs=200), publish=None)
    free = await unsampled(api, [r for r in draft if r["kind"] == "pair"])
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True,
                              json={"rows": [gold_line(r, pool="qualification") for r in free[:60]]})).status_code == 200
    api.app.state.ctx.forget_settings()
    served = (await api.request("GET", "/api/next", "alice", params={"kind": "pair"})).json()
    assert served["qualification"] is None and served["item"]["candidate"]["corpus_id"] != draft[0]["corpus_id"]

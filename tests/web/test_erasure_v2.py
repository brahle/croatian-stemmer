"""Erasure in V2 (4.13.4): the identity goes everywhere the trust system put it; the answers
live on under a new identifier that nothing links to the old one."""
import hashlib

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import (answer, answer_path, candidates, easy_params, make_anchor, pair_rows, profiled,
                              score_now, unlimited, unseeded)

pytestmark = pytest.mark.asyncio
TABLES = ("label_annotator", "label_consent", "label_corpus", "label_judgment", "label_assignment", "label_setting",
          "label_admin_event", "label_erasure_request", "label_trust_event", "label_trusted_email", "label_anchor",
          "label_gold", "label_scoring_run", "label_annotator_score", "label_item_posterior", "label_item_state",
          "label_item_audit")


async def rows_mentioning(api, *values):
    found = {}
    for table in TABLES:
        clause = " AND ".join(f"t::text LIKE :v{n}" for n in range(len(values)))
        rows = (await api.sql(f"SELECT t::text FROM {table} t WHERE {clause}",
                              **{f"v{n}": f"%{v}%" for n, v in enumerate(values)})).scalars().all()
        if rows:
            found[table] = rows
    return found


async def test_erasing_an_anchor_leaves_no_identity_and_no_link(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(40, different_every=0))
    await easy_params(api)
    owner = await make_anchor(api, "owner")
    subject = api.identity.subjects["owner"]
    seeds = (await unseeded(api, rows))[:12]
    for row in seeds:
        assert (await api.request("POST", answer_path(row), "owner", json=answer(value="different"))).status_code == 200
    # A status change with a reason, later undone.
    for to in ("quarantined", "active"):
        r = await api.request("PUT", f"/api/admin/annotators/{owner}/status", "curator", True,
                              json={"status": to, "reason": "provjera vlasnika"})
        assert r.status_code == 200
    [(first, _)] = await score_now(api)
    assert (await api.sql("SELECT count(*) FROM label_gold WHERE source = 'anchor_consensus'")).scalar_one() == 12
    assert (await api.request("POST", f"/api/admin/scoring/runs/{first}/pin", "curator", True)).status_code == 200
    assert (await api.sql("SELECT count(*) FROM label_annotator_score WHERE annotator_id = :a", a=owner)).scalar_one() > 0

    assert (await api.request("POST", "/api/me/erase", "owner", json={"confirm": "DELETE"})).status_code == 200
    new = (await api.sql("SELECT DISTINCT annotator_id::text FROM label_judgment WHERE item_id = :i",
                         i=seeds[0]["item_id"])).scalar_one()
    assert new != owner
    # The consensus gold is retracted in the erasure transaction and its support redacted.
    retracted = (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'gold.retracted' "
                               "AND details ->> 'reason' = 'erasure'")).scalar_one()
    assert retracted == 12
    supports = (await api.sql("SELECT details -> 'support' FROM label_trust_event WHERE kind = 'gold.set'")).scalars().all()
    assert supports and all(s == {"redacted": True} for s in supports)
    assert (await api.sql("SELECT count(*) FROM label_gold WHERE status = 'retracted'")).scalar_one() == 12
    # Anchor, trusted entry, scores: gone, the pinned run included.
    assert (await api.sql("SELECT count(*) FROM label_anchor")).scalar_one() == 0
    entry = (await api.sql("SELECT email, email_sha256, label, removed_at FROM label_trusted_email")).one()
    assert entry.email is None and entry.email_sha256 is None and entry.label is None and entry.removed_at
    assert (await api.sql("SELECT count(*) FROM label_annotator_score WHERE annotator_id = :a", a=owner)).scalar_one() == 0
    # Reasons are redacted from the events about the old identifier.
    reasons = (await api.sql("SELECT details::text FROM label_admin_event WHERE target = :a AND kind = 'annotator.status'",
                             a=owner)).scalars().all()
    assert reasons and not any("provjera" in r for r in reasons)
    # No identity anywhere (the Keycloak id only until the erasure is completed), no row naming both ids.
    digest = hashlib.sha256(b"owner@example.org").hexdigest()
    for value in ("owner@example.org", digest, "Owner"):
        assert await rows_mentioning(api, value) == {}, value
    assert set(await rows_mentioning(api, subject)) == {"label_admin_event"}
    request = (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"][0]
    assert (await api.request("POST", f'/api/admin/erasures/{request["id"]}/complete', "curator", True)).status_code == 200
    assert await rows_mentioning(api, subject) == {}
    assert await rows_mentioning(api, owner, new) == {}
    # Nor any two-hop join: no row naming the old id names an item or corpus the new id answered.
    places = {str(v) for row in (await api.sql("SELECT DISTINCT corpus_id, item_id FROM label_judgment "
                                               "WHERE annotator_id = :n", n=new)).all() for v in row}
    for table, texts in (await rows_mentioning(api, owner)).items():
        for text_ in texts:
            assert not [p for p in places if p in text_], (table, text_)
    # The pinned run's bundle, rebuilt now, holds no identity either.
    bundle = (await api.request("GET", f"/api/admin/scoring/runs/{first}/bundle", "curator", True)).text
    for value in ("owner@example.org", digest, "Owner", subject):
        assert value not in bundle
    # The answers count under the new identifier at the next run.
    [(after, _)] = await score_now(api)
    assert (await api.sql("SELECT count(*) FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a",
                          r=after, a=new)).scalar_one() == 1


@pytest.mark.parametrize("how", ["automatic", "kept"])
async def test_erasing_a_quarantined_person_deletes_their_answers(fresh_api, how):
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=35))
    x = await profiled(api, "x")
    pairs = [r for r in rows if r["kind"] == "pair"][:32]
    for row in pairs:
        assert (await api.request("POST", answer_path(row), "x", json=answer(elapsed_ms=200))).status_code == 200
    await score_now(api)
    assert (await api.sql("SELECT status FROM label_annotator WHERE id = :a", a=x)).scalar_one() == "quarantined"
    if how == "kept":
        r = await api.request("PUT", f"/api/admin/annotators/{x}/status", "curator", True,
                              json={"status": "quarantined", "reason": "zadržano"})
        assert r.status_code == 200
    assert (await api.request("POST", "/api/me/erase", "x", json={"confirm": "DELETE"})).status_code == 200
    assert (await api.sql("SELECT count(*) FROM label_judgment WHERE corpus_id = :c", c=rows[0]["corpus_id"])
            ).scalar_one() == 0
    [(run_id, _)] = await score_now(api)
    assert (await api.sql("SELECT coalesce(sum(n_annotators), 0) FROM label_item_posterior WHERE run_id = :r",
                          r=run_id)).scalar_one() == 0
    flags = (await api.sql("SELECT details::text FROM label_admin_event WHERE target = :a AND kind = 'annotator.status'",
                           a=x)).scalars().all()
    assert flags and not any("fast" in f or "zadržano" in f for f in flags)


async def test_after_a_restore_the_erasure_list_is_applied_again(fresh_api):
    """The runbook's re-application erases a restored profile exactly as the person's own
    erasure did: identity gone, answers under a new identifier, the request recorded."""
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    who = await profiled(api, "restored")
    assert (await api.request("POST", answer_path(rows[0]), "restored", json=answer())).status_code == 200
    subject = api.identity.subjects["restored"]
    r = await api.request("POST", "/api/admin/erasures/reapply", "curator", True,
                          json={"keycloak_user_ids": [subject, subject, "never-seen"]})
    assert r.status_code == 200 and r.json() == {"erased": [who]}
    person = (await api.sql("SELECT subject, email, status FROM label_annotator WHERE id = :a", a=who)).one()
    assert tuple(person) == (None, None, "erased")
    moved = (await api.sql("SELECT annotator_id::text FROM label_judgment WHERE item_id = :i",
                           i=rows[0]["item_id"])).scalar_one()
    assert moved != who
    entry = next(e for e in (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]
                 if e["annotator_id"] == who)
    assert entry["keycloak_user_id"] == subject and entry["reason"] == "restore_reapply"
    again = await api.request("POST", "/api/admin/erasures/reapply", "curator", True, json={"keycloak_user_ids": [subject]})
    assert again.json() == {"erased": []}
    assert (await api.request("POST", "/api/admin/erasures/reapply", "restored2", json={"keycloak_user_ids": ["x"]})
            ).status_code == 403

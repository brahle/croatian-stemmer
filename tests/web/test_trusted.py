"""The trusted list (4.7): verified email to anchor, once; removal revokes in the same
request; the journal never holds an email, a hash or a label."""
import hashlib

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, make_anchor, profiled, score_now, unlimited, unseeded

pytestmark = pytest.mark.asyncio


async def trust_texts(api):
    return [r[0] for r in (await api.sql("SELECT details::text FROM label_trust_event")).all()]


async def test_verified_match_grants_once_and_removal_revokes(fresh_api):
    api = unlimited(await fresh_api())
    r = await api.request("POST", "/api/admin/trusted", "curator", True,
                          json={"email": "  Owner@Example.org ", "label": "Ana"})
    assert r.status_code == 200
    entry = r.json()["id"]
    dup = await api.request("POST", "/api/admin/trusted", "curator", True, json={"email": "owner@example.org",
                                                                                 "label": "Ana"})
    assert dup.status_code == 409 and dup.json()["detail"]["code"] == "already_trusted"
    # An unverified address never matches.
    r = await api.client.get("/api/me", headers=api.headers("owner", email_verified=False))
    assert r.status_code == 200
    owner = await api.annotator_id("owner")
    assert (await api.sql("SELECT count(*) FROM label_anchor")).scalar_one() == 0
    # Fifty requests with the profile refresh due each time: one grant.
    for _ in range(50):
        await api.sql("UPDATE label_annotator SET last_seen_at = now() - interval '1 hour' WHERE id = :a", a=owner)
        assert (await api.request("GET", "/api/me", "owner")).status_code == 200
    assert (await api.sql("SELECT count(*) FROM label_trust_event WHERE kind = 'anchor.granted'")).scalar_one() == 1
    assert (await api.sql("SELECT trusted_id FROM label_anchor WHERE annotator_id = :a", a=owner)).scalar_one() == entry
    listed = (await api.request("GET", "/api/admin/trusted", "curator", True)).json()
    assert listed["items"][0]["annotator_id"] == owner and listed["items"][0]["email"] == "owner@example.org"
    # Removal revokes in the same request and deletes the identity fields.
    r = await api.request("DELETE", f"/api/admin/trusted/{entry}", "curator", True, json={"reason": "left"})
    assert r.status_code == 200
    assert (await api.sql("SELECT count(*) FROM label_anchor")).scalar_one() == 0
    row = (await api.sql("SELECT email, email_sha256, label, removed_at FROM label_trusted_email WHERE id = :i",
                         i=entry)).one()
    assert (row.email, row.email_sha256, row.label) == (None, None, None) and row.removed_at is not None
    kinds = [r[0] for r in (await api.sql("SELECT kind FROM label_trust_event ORDER BY id")).all()]
    assert kinds == ["trusted.added", "anchor.granted", "trusted.removed", "anchor.revoked"]
    digest = hashlib.sha256(b"owner@example.org").hexdigest()
    for details in await trust_texts(api):
        assert "@" not in details and digest not in details and "Ana" not in details
    listed = (await api.request("GET", "/api/admin/trusted", "curator", True)).json()
    assert listed["items"] == [] and listed["removed"][0]["id"] == entry
    assert (await api.request("GET", "/api/admin/trusted", "owner")).status_code == 403


async def test_adding_someone_already_signed_in_grants_at_once(fresh_api):
    api = await fresh_api()
    await profiled(api, "maja")
    anchor = await make_anchor(api, "maja")
    assert anchor == await api.annotator_id("maja")


async def test_after_revocation_the_next_run_drops_the_anchor_tier(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(candidates(pairs=12))
    owner = await make_anchor(api, "owner")
    # Not a keyed sample: there the owner's answer would be a reference check, not a vote.
    pair = (await unseeded(api, [r for r in rows if r["kind"] == "pair"]))[0]
    for name in ("owner", "a", "b"):
        await profiled(api, name)
        assert (await api.request("POST", answer_path(pair), name, json=answer())).status_code == 200
    [(run_id, _)] = await score_now(api)
    state = "SELECT state FROM label_item_state WHERE item_id = :i"
    assert (await api.sql(state, i=pair["item_id"])).scalar_one() in ("resolved", "provisional")
    assert (await api.sql("SELECT tier FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a",
                          r=run_id, a=owner)).scalar_one() == "anchor"
    entry = (await api.sql("SELECT trusted_id FROM label_anchor WHERE annotator_id = :a", a=owner)).scalar_one()
    await api.request("DELETE", f"/api/admin/trusted/{entry}", "curator", True, json={"reason": "test"})
    [(after, _)] = await score_now(api)
    assert (await api.sql("SELECT tier FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a",
                          r=after, a=owner)).scalar_one() == "new"
    assert (await api.sql(state, i=pair["item_id"])).scalar_one() == "open"

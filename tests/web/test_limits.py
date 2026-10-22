"""Abuse limits: token buckets, the daily cap, the kill switch and body bounds."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path

pytestmark = pytest.mark.asyncio


async def test_answer_burst_is_limited_per_annotator(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    statuses = []
    for revision in range(16):
        r = await api.request("POST", answer_path(row), "alice", json=answer(revision, "same"))
        statuses.append(r.status_code)
    assert statuses == [200] * 15 + [429]
    assert r.json()["detail"]["code"] == "rate_limited" and int(r.headers["retry-after"]) >= 1
    # Another person in the same second is unaffected.
    assert (await api.request("POST", answer_path(row), "bob", json=answer())).status_code == 200


async def test_daily_cap(make_api):
    api = await make_api(daily_cap=2)
    rows = await api.imported()
    await api.consent("alice")
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    assert (await api.request("POST", answer_path(rows[1]), "alice", json=answer(0, "unsure"))).status_code == 200
    r = await api.request("POST", answer_path(rows[2]), "alice", json=answer(0, "accept"))
    assert r.status_code == 429 and r.json()["detail"]["code"] == "daily_cap_reached"
    # The cap counts the last 24 hours in the database, so it survives a restart.
    again = await make_api(daily_cap=2)
    again.identity.private, again.identity.subjects = api.identity.private, api.identity.subjects
    again.identity.install(again.app)
    assert (await again.request("POST", answer_path(rows[2]), "alice", json=answer(0, "accept"))).status_code == 429


async def test_kill_switch_setting(api):
    rows = await api.imported()
    await api.consent("alice")
    alice = await api.annotator_id("alice")
    try:
        r = await api.request("PUT", "/api/admin/settings", "curator", True, json={"accepting_judgments": False})
        assert r.status_code == 200 and r.json()["accepting_judgments"] is False
        assert (await api.client.get("/api/config")).json()["acceptingJudgments"] is False
        paused = await api.request("POST", answer_path(rows[0]), "alice", json=answer())
        assert paused.status_code == 503 and paused.json()["detail"]["code"] == "judgments_paused"
        count = (await api.sql("SELECT count(*) FROM label_judgment WHERE annotator_id = :a", a=alice)).scalar_one()
        assert count == 0
        assert (await api.request("GET", "/api/admin/settings", "curator", True)).json()["accepting_judgments"] is False
    finally:
        r = await api.request("PUT", "/api/admin/settings", "curator", True, json={"accepting_judgments": True})
        assert r.status_code == 200
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    event = (await api.sql("SELECT details FROM label_admin_event WHERE kind = 'setting.update' "
                           "ORDER BY id DESC LIMIT 1")).scalar_one()
    assert event == {"value": True}
    assert (await api.request("PUT", "/api/admin/settings", "curator", True,
                              json={"accepting_judgments": "false"})).status_code == 422


async def test_read_only_environment_override(make_api):
    api = await make_api(read_only=True)
    rows = await api.imported()
    await api.consent("alice")
    r = await api.request("POST", answer_path(rows[0]), "alice", json=answer())
    assert r.status_code == 503 and r.json()["detail"]["code"] == "judgments_paused"
    assert (await api.client.get("/api/config")).json()["acceptingJudgments"] is False


async def test_account_routes_are_limited(api):
    for _ in range(10):
        assert (await api.request("GET", "/api/me/export.json", "alice")).status_code == 200
    r = await api.request("GET", "/api/me/export.json", "alice")
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"


async def test_body_limits(api):
    r = await api.client.post("/api/import", headers={**api.headers("curator", True),
                                                      "Content-Length": str(32 * 1024 * 1024 + 1)}, content=b"")
    assert r.status_code == 413

    async def chunks():
        for _ in range(5):
            yield b"x" * 4096
    r = await api.client.post(f"/api/corpora/{uuid4()}/items/{uuid4()}/answer",
                              headers={**api.headers(), "Content-Type": "application/json"}, content=chunks())
    assert r.status_code == 413, r.text
    r = await api.client.post("/api/me/consent", headers={**api.headers(), "Content-Length": "16385"}, content=b"")
    assert r.status_code == 413


async def test_release_authenticates_before_it_parses_the_body(api):
    """F1: the release route used to parse its (32 MiB) JSON body before the curator check,
    so an anonymous `{` got 422 json_invalid. It now refuses the caller first."""
    junk = {"Content-Type": "application/json"}
    for run in ("x", str(uuid4())):
        url = f"/api/admin/scoring/runs/{run}/release"
        r = await api.client.post(url, headers=junk, content=b"{")
        assert r.status_code == 401, r.text
        r = await api.request("POST", url, "alice", headers=junk, content=b"{")
        assert r.status_code == 403 and r.json()["detail"]["code"] == "curator_required", r.text
    # A curator still gets a validation error for a malformed body, in the app's own shape.
    r = await api.request("POST", f"/api/admin/scoring/runs/{uuid4()}/release", "curator", True,
                          headers=junk, content=b"{")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_release", r.text
    r = await api.request("POST", f"/api/admin/scoring/runs/{uuid4()}/release", "curator", True,
                          json={"item_ids": ["not-a-uuid"]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_release", r.text


async def test_large_bodies_need_a_bearer_token(api):
    """Without an Authorization header the 32 MiB import/release limit does not apply."""
    over = {"Content-Length": "16385"}
    for url in ("/api/import", "/api/admin/gold/import", f"/api/admin/scoring/runs/{uuid4()}/release"):
        r = await api.client.post(url, headers=over, content=b"")
        assert r.status_code == 413, (url, r.text)
        r = await api.client.post(url, headers={**over, "Authorization": "Basic eA=="}, content=b"")
        assert r.status_code == 413, (url, r.text)
        # With a bearer the size passes the bound and the token is checked next.
        r = await api.client.post(url, headers={"Authorization": "Bearer junk", "Content-Type": "application/json"},
                                  content=b"{" + b" " * 16385 + b"}")
        assert r.status_code == 401, (url, r.text)


async def test_token_bucket_refills():
    from croatian_stemmer.labeling.web.limits import Limiter, Rate
    from fastapi import HTTPException
    clock = [0.0]
    limiter = Limiter({"answer": Rate(2, 1.0)}, clock=lambda: clock[0])
    limiter.take("answer", "a")
    limiter.take("answer", "a")
    with pytest.raises(HTTPException) as exc:
        limiter.take("answer", "a")
    assert exc.value.headers["Retry-After"] == "1"
    limiter.take("answer", "b")
    clock[0] = 1.0
    limiter.take("answer", "a")
    clock[0] = 100.0
    limiter.prune(clock[0])
    assert limiter.buckets == {}

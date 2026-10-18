"""Self-service export and erasure (data-subject rights), the 30-day expiry of
profiles that never accepted the gate, and erasure-safe profile refresh."""
import asyncio
import hashlib
import io
import logging
from datetime import datetime, timedelta, timezone

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.schema import read_tsv
from labeling_support import answer, answer_path

pytestmark = pytest.mark.asyncio
# Every table that can hold an annotator id, as text (a row "contains" an id if it mentions it).
TABLES = ("label_annotator", "label_consent", "label_corpus", "label_judgment", "label_assignment",
          "label_setting", "label_admin_event", "label_erasure_request")


async def labelled(api, name="alice"):
    rows = await api.imported()
    await api.consent(name)
    assert (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/next', name)).status_code == 200
    assert (await api.request("POST", answer_path(rows[0]), name, json=answer())).status_code == 200
    return rows


async def mentioning(api, value):
    """{table: [row text, ...]} for every row of TABLES whose text contains value."""
    found = {}
    for table in TABLES:
        rows = (await api.sql(f"SELECT t::text FROM {table} t WHERE t::text LIKE :v", v=f"%{value}%")).scalars().all()
        if rows:
            found[table] = rows
    return found


async def test_export_contains_everything_linked_to_the_annotator(api):
    rows = await labelled(api)
    r = await api.request("GET", "/api/me/export.json", "alice")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment;")
    data = r.json()
    me = await api.annotator_id("alice")
    assert data["annotator"]["annotator_id"] == me and data["annotator"]["email"] == "alice@example.org"
    assert "subject" not in data["annotator"] and api.identity.subjects["alice"] not in r.text
    assert [(c["document"], c["age_threshold"]) for c in data["consents"]] == [
        ("privacy", 18), ("terms", 18), ("participation", 18)]
    assert [(j["item_id"], j["revision"], j["elapsed_ms"]) for j in data["judgments"]] == [(rows[0]["item_id"], 1, 1234)]
    assert data["assignments"][0]["shown_count"] == 1 and data["erasure_requests"] == []


async def test_erasure_moves_answers_to_a_new_identifier(api):
    rows = await labelled(api)
    corpus = rows[0]["corpus_id"]
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer(1, "different"))).status_code == 200
    old = await api.annotator_id("alice")
    subject = api.identity.subjects["alice"]
    before = (await api.sql("SELECT id, revision, answer, created_at FROM label_judgment WHERE annotator_id = :a "
                            "ORDER BY revision", a=old)).all()
    consents_before = (await api.sql("SELECT id, document, accepted_at FROM label_consent WHERE annotator_id = :a "
                                     "ORDER BY id", a=old)).all()
    for confirm in ("izbriši", "yes", ""):
        assert (await api.request("POST", "/api/me/erase", "alice", json={"confirm": confirm})).status_code == 422
    r = await api.request("POST", "/api/me/erase", "alice", json={"confirm": "IZBRIŠI"})
    assert r.status_code == 200 and r.json() == {"erased": True, "keycloak_deletion": "pending"}

    person = (await api.sql("SELECT subject, email, email_verified, status, erased_at FROM label_annotator "
                            "WHERE id = :a", a=old)).one()
    assert person.subject is None and person.email is None and person.email_verified is False
    assert person.status == "erased" and person.erased_at is not None
    # Nothing is left under the old id.
    for table in ("label_judgment", "label_consent", "label_assignment"):
        assert (await api.sql(f"SELECT count(*) FROM {table} WHERE annotator_id = :a", a=old)).scalar_one() == 0, table

    # The answers are under one new, subject-less erased id, with new row ids, the day only and no timing.
    after = (await api.sql("SELECT id, annotator_id, revision, answer, created_at, elapsed_ms FROM label_judgment "
                           "WHERE corpus_id = :c ORDER BY revision", c=corpus)).all()
    new = after[0].annotator_id
    assert {j.annotator_id for j in after} == {new} and str(new) != old
    assert [(j.revision, j.answer) for j in after] == [(j.revision, j.answer) for j in before]
    assert not {j.id for j in after} & {j.id for j in before}
    midnight = lambda t: t.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    assert [j.created_at for j in after] == [midnight(j.created_at) for j in before]
    assert all(j.elapsed_ms is None for j in after)
    receiver = (await api.sql("SELECT subject, email, email_verified, status, created_at, last_seen_at, erased_at "
                              "FROM label_annotator WHERE id = :n", n=new)).one()
    assert (receiver.subject, receiver.email, receiver.email_verified, receiver.status) == (None, None, False, "erased")
    assert {receiver.created_at, receiver.last_seen_at, receiver.erased_at} == {midnight(receiver.created_at)}
    consents = (await api.sql("SELECT id, document, accepted_at, age_threshold FROM label_consent "
                              "WHERE annotator_id = :n ORDER BY id", n=new)).all()
    assert sorted((c.document, c.accepted_at) for c in consents) == sorted(
        (c.document, midnight(c.accepted_at)) for c in consents_before)
    assert not {c.id for c in consents} & {c.id for c in consents_before}
    assert all(c.age_threshold == 18 for c in consents)

    # No row anywhere names both ids; nothing but the moved rows names the new one.
    for table, texts in (await mentioning(api, str(new))).items():
        assert table in ("label_annotator", "label_judgment", "label_consent"), table
        assert all(old not in text for text in texts), table
    assert "label_erasure_request" in await mentioning(api, old)

    # The erasure request names only the Keycloak user; signing in again shows the notice.
    details = (await api.sql("SELECT actor_id, details FROM label_admin_event WHERE kind = 'erasure.requested' "
                             "AND target = :t", t=old)).one()
    assert str(details.actor_id) == old and details.details == {"keycloak_user_id": subject}
    again = await api.request("GET", "/api/me", "alice")
    assert again.status_code == 409 and again.json()["detail"] == {"code": "erasure_pending"}
    assert (await api.sql("SELECT count(*) FROM label_annotator WHERE subject = :s", s=subject)).scalar_one() == 0

    # The curator sees the Keycloak user id to delete (nothing else), then completes it.
    pending = (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]
    entry = next(e for e in pending if e["annotator_id"] == old)
    assert entry["keycloak_user_id"] == subject and entry["reason"] is None
    assert "email" not in entry and "preferred_username" not in entry
    done = await api.request("POST", f'/api/admin/erasures/{entry["id"]}/complete', "curator", True)
    assert done.status_code == 200
    request = (await api.sql("SELECT subject_sha256, keycloak_deleted_at FROM label_erasure_request WHERE id = :i",
                             i=entry["id"])).one()
    assert request.subject_sha256 is None and request.keycloak_deleted_at is not None
    details = (await api.sql("SELECT details FROM label_admin_event WHERE kind = 'erasure.requested' AND target = :t",
                             t=old)).scalar_one()
    assert details == {}
    assert await mentioning(api, subject) == {}
    assert (await api.sql("SELECT count(*) FROM label_admin_event WHERE kind = 'erasure.keycloak_deleted' "
                          "AND target = :t", t=old)).scalar_one() == 1
    assert entry["id"] not in [e["id"] for e in (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]]
    twice = await api.request("POST", f'/api/admin/erasures/{entry["id"]}/complete', "curator", True)
    assert twice.status_code == 409 and twice.json()["detail"]["code"] == "erasure_not_pending"
    # The answers still count, under the new id.
    tsv = (await api.request("GET", f"/api/corpora/{corpus}/export.tsv", "curator", True)).text
    assert [x.annotator_id for x in read_tsv(io.StringIO(tsv))] == [str(new)] * len(before)
    # Erased rows cannot be re-activated by a curator.
    for target in (old, str(new)):
        r = await api.request("PUT", f"/api/admin/annotators/{target}/status", "curator", True,
                              json={"status": "active", "reason": "undo"})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "annotator_erased"


async def test_erasing_without_answers_creates_no_new_identifier(api):
    assert (await api.request("GET", "/api/me", "gina")).status_code == 200
    erased_rows = "SELECT count(*) FROM label_annotator WHERE status = 'erased'"
    count = (await api.sql(erased_rows)).scalar_one()
    assert (await api.request("POST", "/api/me/erase", "gina", json={"confirm": "DELETE"})).status_code == 200
    assert (await api.sql(erased_rows)).scalar_one() == count + 1


@pytest.mark.parametrize("status", ["blocked", "quarantined"])
async def test_excluded_annotator_keeps_data_subject_rights_and_answers_are_deleted(api, status):
    rows = await labelled(api, "bob")
    bob = await api.annotator_id("bob")
    r = await api.request("PUT", f"/api/admin/annotators/{bob}/status", "curator", True,
                          json={"status": status, "reason": "synthetic"})
    assert r.status_code == 200
    if status == "blocked":
        assert (await api.request("GET", "/api/corpora", "bob")).status_code == 403
    # A quarantine is silent: the person's own view says active (4.8.2).
    shown = (await api.request("GET", "/api/me", "bob")).json()
    assert shown["status"] == ("blocked" if status == "blocked" else "active")
    assert shown["status_reason"] == ("synthetic" if status == "blocked" else None)
    assert (await api.request("GET", "/api/me/export.json", "bob")).status_code == 200
    erased_rows = "SELECT count(*) FROM label_annotator WHERE status = 'erased'"
    count = (await api.sql(erased_rows)).scalar_one()
    assert (await api.request("POST", "/api/me/erase", "bob", json={"confirm": "DELETE"})).status_code == 200
    # Deleted, not moved: no new identifier, no judgment or consent anywhere.
    assert (await api.sql(erased_rows)).scalar_one() == count + 1
    for table in ("label_judgment", "label_consent"):
        assert (await api.sql(f"SELECT count(*) FROM {table} WHERE annotator_id = :a", a=bob)).scalar_one() == 0
    root = f'/api/corpora/{rows[0]["corpus_id"]}'
    assert (await api.sql("SELECT count(*) FROM label_judgment WHERE corpus_id = :c",
                          c=rows[0]["corpus_id"])).scalar_one() == 0
    everything = await api.request("GET", root + "/export.tsv", "curator", True, params={"include_excluded": "true"})
    assert list(read_tsv(io.StringIO(everything.text))) == []


async def test_overdue_erasures_are_logged_without_identity(api, caplog):
    from croatian_stemmer.labeling.web.api import warn_overdue_erasures
    await labelled(api, "erin")
    erin = await api.annotator_id("erin")
    assert (await api.request("POST", "/api/me/erase", "erin", json={"confirm": "DELETE"})).status_code == 200
    request_id = (await api.sql("SELECT id FROM label_erasure_request WHERE annotator_id = :a", a=erin)).scalar_one()
    assert request_id not in await warn_overdue_erasures(api.app.state.ctx)
    await api.sql("UPDATE label_erasure_request SET requested_at = now() - interval '15 days' WHERE id = :i", i=request_id)
    caplog.set_level(logging.WARNING)
    assert request_id in await warn_overdue_erasures(api.app.state.ctx)
    assert f"erasure request {request_id} has waited 15 days" in caplog.text
    assert "erin" not in caplog.text and api.identity.subjects["erin"] not in caplog.text
    digest = hashlib.sha256(api.identity.subjects["erin"].encode()).hexdigest()
    assert digest not in caplog.text


# ---- 30-day expiry of profiles that never accepted the gate -------------------

async def test_unconsented_profiles_expire_after_30_days(api):
    from croatian_stemmer.labeling.web.api import expire_unconsented_profiles
    ctx = api.app.state.ctx
    assert (await api.request("GET", "/api/me", "late")).status_code == 200
    await labelled(api, "carol")
    await api.consent("curator", True)  # the curator who imported the corpus keeps their profile
    late, carol = await api.annotator_id("late"), await api.annotator_id("carol")
    subject = api.identity.subjects["late"]
    now = datetime.now(timezone.utc)
    # 29 days on, nothing happens to either.
    assert late not in map(str, await expire_unconsented_profiles(ctx, now=now + timedelta(days=29)))
    statuses = "SELECT id::text, status, subject IS NOT NULL FROM label_annotator WHERE id IN (:a, :b)"
    assert set(map(tuple, (await api.sql(statuses, a=late, b=carol)).all())) == {(late, "active", True),
                                                                              (carol, "active", True)}
    # 31 days on, the never-consented profile is erased and queued for Keycloak deletion; the consented one stays.
    erased = list(map(str, await expire_unconsented_profiles(ctx, now=now + timedelta(days=31))))
    assert late in erased and carol not in erased
    assert set(map(tuple, (await api.sql(statuses, a=late, b=carol)).all())) == {(late, "erased", False),
                                                                              (carol, "active", True)}
    request = (await api.sql("SELECT subject_sha256, keycloak_deleted_at FROM label_erasure_request "
                             "WHERE annotator_id = :a", a=late)).one()
    assert request.subject_sha256 == hashlib.sha256(subject.encode()).hexdigest() and request.keycloak_deleted_at is None
    event = (await api.sql("SELECT actor_id, details FROM label_admin_event WHERE kind = 'erasure.requested' "
                           "AND target = :t", t=late)).one()
    assert event.actor_id is None and event.details == {"keycloak_user_id": subject, "reason": "unconsented_expiry"}
    # Idempotent: a second run erases nothing more for this profile.
    assert late not in map(str, await expire_unconsented_profiles(ctx, now=now + timedelta(days=31)))
    assert (await api.sql("SELECT count(*) FROM label_erasure_request WHERE annotator_id = :a", a=late)).scalar_one() == 1
    # Signing in again before the Keycloak deletion shows the notice worded for this case.
    again = await api.request("GET", "/api/me", "late")
    assert again.status_code == 409
    assert again.json()["detail"] == {"code": "erasure_pending", "reason": "unconsented_expiry"}
    entry = next(e for e in (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]
                 if e["annotator_id"] == late)
    assert entry["keycloak_user_id"] == subject and entry["reason"] == "unconsented_expiry"


async def test_expiry_leaves_blocked_and_recent_profiles_alone(api):
    from croatian_stemmer.labeling.web.api import expire_unconsented_profiles
    assert (await api.request("GET", "/api/me", "hank")).status_code == 200
    assert (await api.request("GET", "/api/me", "iris")).status_code == 200
    hank = await api.annotator_id("hank")
    await api.request("PUT", f"/api/admin/annotators/{hank}/status", "curator", True,
                      json={"status": "blocked", "reason": "synthetic"})
    # The database clock: neither profile is 30 days old, and a blocked one is never expired.
    erased = list(map(str, await expire_unconsented_profiles(api.app.state.ctx)))
    assert hank not in erased and await api.annotator_id("iris") not in erased
    await api.sql("UPDATE label_annotator SET created_at = now() - interval '31 days' WHERE id = :a", a=hank)
    assert hank not in map(str, await expire_unconsented_profiles(api.app.state.ctx))
    assert (await api.sql("SELECT status FROM label_annotator WHERE id = :a", a=hank)).scalar_one() == "blocked"


async def test_writes_are_refused_once_the_profile_is_erased(api):
    """still_present() guards /api/me/consent, /next and /answer: a request authenticated just
    before an erasure committed writes nothing to the erased profile."""
    from uuid import UUID
    from fastapi import HTTPException
    from croatian_stemmer.labeling.web.common import Caller
    from croatian_stemmer.labeling.web.erasure import still_present
    await labelled(api, "jade")
    caller = Caller(id=UUID(await api.annotator_id("jade")), status="active", principal=None)
    async with api.app.state.ctx.sessions() as db, db.begin():
        await still_present(db, caller)
    assert (await api.request("POST", "/api/me/erase", "jade", json={"confirm": "DELETE"})).status_code == 200
    async with api.app.state.ctx.sessions() as db, db.begin():
        with pytest.raises(HTTPException) as exc:
            await still_present(db, caller)
    assert exc.value.status_code == 409 and exc.value.detail == {"code": "erasure_pending"}


# ---- erasure-safe profile refresh ---------------------------------------------

async def test_refresh_paused_across_an_erasure_leaves_no_email(api, monkeypatch):
    from croatian_stemmer.labeling.web import api as api_module
    assert (await api.request("GET", "/api/me", "kim")).status_code == 200
    kim = await api.annotator_id("kim")
    await api.sql("UPDATE label_annotator SET last_seen_at = now() - interval '1 hour' WHERE id = :a", a=kim)
    original, paused, resume, calls = api_module.refresh_profile, asyncio.Event(), asyncio.Event(), []

    async def held(db, annotator_id, principal):
        # The first refresh (kim's GET /api/me) stops after its SELECT until the erasure has committed.
        calls.append(annotator_id)
        if len(calls) == 1:
            paused.set()
            await resume.wait()
        return await original(db, annotator_id, principal)
    monkeypatch.setattr(api_module, "refresh_profile", held)
    refresh = asyncio.create_task(api.request("GET", "/api/me", "kim"))
    await asyncio.wait_for(paused.wait(), 10)
    assert (await api.request("POST", "/api/me/erase", "kim", json={"confirm": "DELETE"})).status_code == 200
    resume.set()
    r = await asyncio.wait_for(refresh, 10)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "erasure_pending"
    row = (await api.sql("SELECT subject, email, email_verified, status FROM label_annotator WHERE id = :a", a=kim)).one()
    assert tuple(row) == (None, None, False, "erased")

"""Self-service export and erasure (data-subject rights), including for blocked accounts."""
import hashlib
import io
import logging

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.schema import read_tsv
from labeling_support import answer, answer_path

pytestmark = pytest.mark.asyncio


async def labelled(api, name="alice"):
    rows = await api.imported()
    await api.consent(name)
    assert (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/next', name)).status_code == 200
    assert (await api.request("POST", answer_path(rows[0]), name, json=answer())).status_code == 200
    return rows


async def test_export_contains_everything_linked_to_the_annotator(api):
    rows = await labelled(api)
    r = await api.request("GET", "/api/me/export.json", "alice")
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment;")
    data = r.json()
    me = await api.annotator_id("alice")
    assert data["annotator"]["annotator_id"] == me and data["annotator"]["email"] == "alice@example.org"
    assert "subject" not in data["annotator"] and api.identity.subjects["alice"] not in r.text
    assert [c["document"] for c in data["consents"]] == ["privacy", "terms"]
    assert [(j["item_id"], j["revision"], j["elapsed_ms"]) for j in data["judgments"]] == [(rows[0]["item_id"], 1, 1234)]
    assert data["assignments"][0]["shown_count"] == 1 and data["erasure_requests"] == []


async def test_erasure_severs_identity_and_keeps_pseudonymous_judgments(api, caplog):
    rows = await labelled(api)
    me = await api.annotator_id("alice")
    for confirm in ("izbriši", "yes", ""):
        assert (await api.request("POST", "/api/me/erase", "alice", json={"confirm": confirm})).status_code == 422
    r = await api.request("POST", "/api/me/erase", "alice", json={"confirm": "IZBRIŠI"})
    assert r.status_code == 200 and r.json() == {"erased": True, "keycloak_deletion": "pending"}
    person = (await api.sql("SELECT subject, email, email_verified, status, erased_at FROM label_annotator "
                            "WHERE id = :a", a=me)).one()
    assert person.subject is None and person.email is None and person.email_verified is False
    assert person.status == "erased" and person.erased_at is not None
    judgment = (await api.sql("SELECT annotator_id, elapsed_ms, answer FROM label_judgment WHERE annotator_id = :a",
                              a=me)).one()
    assert judgment.elapsed_ms is None and judgment.answer == "same"
    assert (await api.sql("SELECT count(*) FROM label_assignment WHERE annotator_id = :a", a=me)).scalar_one() == 0
    assert (await api.sql("SELECT count(*) FROM label_consent WHERE annotator_id = :a", a=me)).scalar_one() == 2
    # Signing in again before Keycloak deletion shows a notice instead of a new profile.
    again = await api.request("GET", "/api/me", "alice")
    assert again.status_code == 409 and again.json()["detail"]["code"] == "erasure_pending"
    assert (await api.sql("SELECT count(*) FROM label_annotator WHERE subject = :s",
                          s=api.identity.subjects["alice"])).scalar_one() == 0
    # The curator sees what to delete in Keycloak, then completes it.
    pending = (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]
    entry = next(e for e in pending if e["annotator_id"] == me)
    assert entry["preferred_username"] == "alice@example.org" and entry["email"] == "alice@example.org"
    done = await api.request("POST", f'/api/admin/erasures/{entry["id"]}/complete', "curator", True)
    assert done.status_code == 200
    request = (await api.sql("SELECT subject_sha256, keycloak_deleted_at FROM label_erasure_request WHERE id = :i",
                             i=entry["id"])).one()
    assert request.subject_sha256 is None and request.keycloak_deleted_at is not None
    details = (await api.sql("SELECT details FROM label_admin_event WHERE kind = 'erasure.requested' AND target = :t",
                             t=me)).scalar_one()
    assert details == {}
    assert (await api.sql("SELECT count(*) FROM label_admin_event WHERE kind = 'erasure.keycloak_deleted' "
                          "AND target = :t", t=me)).scalar_one() == 1
    assert entry["id"] not in [e["id"] for e in (await api.request("GET", "/api/admin/erasures", "curator", True)).json()["items"]]
    twice = await api.request("POST", f'/api/admin/erasures/{entry["id"]}/complete', "curator", True)
    assert twice.status_code == 409 and twice.json()["detail"]["code"] == "erasure_not_pending"
    # The pseudonymous judgment is still exported.
    tsv = (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/export.tsv', "curator", True)).text
    assert [x.annotator_id for x in read_tsv(io.StringIO(tsv))] == [me]
    # Erased accounts cannot be re-activated by a curator.
    r = await api.request("PUT", f"/api/admin/annotators/{me}/status", "curator", True,
                          json={"status": "active", "reason": "undo"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "annotator_erased"


async def test_blocked_annotator_keeps_data_subject_rights_and_stays_excluded(api):
    rows = await labelled(api, "bob")
    bob = await api.annotator_id("bob")
    r = await api.request("PUT", f"/api/admin/annotators/{bob}/status", "curator", True,
                          json={"status": "blocked", "reason": "synthetic"})
    assert r.status_code == 200
    assert (await api.request("GET", "/api/corpora", "bob")).status_code == 403
    assert (await api.request("GET", "/api/me", "bob")).json()["status"] == "blocked"
    assert (await api.request("GET", "/api/me/export.json", "bob")).status_code == 200
    assert (await api.request("POST", "/api/me/erase", "bob", json={"confirm": "DELETE"})).status_code == 200
    # Erasing must not bring an excluded account's votes back into the dataset.
    root = f'/api/corpora/{rows[0]["corpus_id"]}'
    assert list(read_tsv(io.StringIO((await api.request("GET", root + "/export.tsv", "curator", True)).text))) == []
    everything = await api.request("GET", root + "/export.tsv", "curator", True, params={"include_excluded": "true"})
    assert [x.annotator_id for x in read_tsv(io.StringIO(everything.text))] == [bob]


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

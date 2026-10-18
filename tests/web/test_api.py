"""Real PostgreSQL acceptance of the shared-corpus API; fixtures are synthetic, never dataset gold."""
import asyncio
import io
import json
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.evaluation import resolve
from croatian_stemmer.labeling.schema import read_tsv
from labeling_support import REQUIRED, answer, answer_path, candidates

pytestmark = pytest.mark.asyncio


def root(row):
    return f'/api/corpora/{row["corpus_id"]}'


async def listed(api, name, curator=False):
    """Every corpus the caller can list, across pages (the test database accumulates corpora)."""
    rows, offset = [], 0
    while offset is not None:
        page = (await api.request("GET", "/api/corpora", name, curator, params={"offset": offset})).json()
        rows += page["items"]
        offset = page["next_offset"]
    return rows


async def next_item(api, row, kind="pair", name="alice"):
    r = await api.request("GET", root(row) + "/next", name, params={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()["item"]


async def test_import_is_curator_only(api):
    rows = candidates()
    r = await api.request("POST", "/api/import", "alice", json={"name": "Nope", "candidates": rows})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "curator_required"
    assert (await api.client.post("/api/import", json={"name": "Nope", "candidates": rows})).status_code == 401
    await api.imported(rows, publish=None)


async def test_draft_corpus_is_invisible_to_annotators(api):
    rows = await api.imported(publish=None)
    row = rows[0]
    await api.consent("alice")
    await api.consent("curator", True)
    assert row["corpus_id"] not in {c["id"] for c in await listed(api, "alice")}
    for tail in ("progress", "next", "items", "items/" + row["item_id"]):
        assert (await api.request("GET", root(row) + "/" + tail, "alice")).status_code == 404
    assert (await api.request("POST", answer_path(row), "alice", json=answer())).status_code == 404
    draft = next(c for c in await listed(api, "curator", True) if c["id"] == row["corpus_id"])
    assert draft["status"] == "draft" and draft["items"] == {"pair": 1, "lemma": 1, "stem": 1}
    r = await api.request("GET", root(row) + "/next", "curator", True)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "corpus_not_published"


@pytest.mark.parametrize("source,requested,status", [
    ("CC BY-NC 4.0", "CC BY-SA 4.0", 409), ("CC BY-NC 4.0", "CC BY 4.0", 409),
    ("CC BY-SA 4.0", "CC BY 4.0", 409), ("CC BY-SA 4.0", "CC0 1.0", 409),
    ("CC BY-SA 4.0", "CC BY-SA 4.0", 200), ("cc-by-sa-4.0", "CC BY-SA 4.0", 200),
    ("CC BY 4.0", "CC BY 4.0", 200), ("CC BY 4.0", "CC0 1.0", 409),
    ("CC0 1.0", "CC0 1.0", 200), ("test fixture, not human gold", "CC BY-SA 4.0", 409),
])
async def test_publish_licence_table(api, source, requested, status):
    rows = await api.imported(candidates(license=source), publish=None)
    r = await api.request("POST", root(rows[0]) + "/publish", "curator", True, json={"labels_license": requested})
    assert r.status_code == status, r.text
    if status == 409:
        assert r.json()["detail"]["code"] == "license_not_publishable"
    else:
        assert r.json()["corpus"]["status"] == "published" and r.json()["corpus"]["labels_license"] == requested


async def test_publish_rejects_unknown_licence_name(api):
    rows = await api.imported(publish=None)
    r = await api.request("POST", root(rows[0]) + "/publish", "curator", True, json={"labels_license": "MIT"})
    assert r.status_code == 422


async def test_next_excludes_answered_recently_shown_and_respects_target_votes(make_api):
    api = await make_api(target_votes=2)
    rows = await api.imported(candidates(pairs=2))
    first, second = rows[0], rows[1]
    for name in ("alice", "bob", "carol"):
        await api.consent(name)
    shown = await next_item(api, first)
    assert shown["candidate"]["item_id"] == first["item_id"] and shown["judgment"] is None
    assert shown["assignment"] == {"current_revision": 0}
    # Shown in the last 30 minutes and not answered: not served again.
    assert (await next_item(api, first))["candidate"]["item_id"] == second["item_id"]
    assert await next_item(api, first) is None
    # Once that window has passed it comes back.
    await api.sql("UPDATE label_assignment SET last_shown_at = now() - interval '31 minutes' "
                  "WHERE annotator_id = :a", a=await api.annotator_id("alice"))
    assert (await next_item(api, first))["candidate"]["item_id"] == first["item_id"]
    assert (await api.request("POST", answer_path(first), "alice", json=answer())).status_code == 200
    await api.sql("UPDATE label_assignment SET last_shown_at = now() - interval '31 minutes' "
                  "WHERE annotator_id = :a", a=await api.annotator_id("alice"))
    # Answered: never served to alice again.
    assert (await next_item(api, first))["candidate"]["item_id"] == second["item_id"]
    # Fewest votes first: bob gets the item nobody voted on yet.
    bob = await next_item(api, first, name="bob")
    assert bob["candidate"]["item_id"] == second["item_id"]
    assert bob["judgment"] is None and "votes" not in json.dumps(bob)
    assert (await api.request("POST", answer_path(first), "bob", json=answer(0, "different"))).status_code == 200
    # first now has two definite votes = target: carol never gets it.
    assert (await next_item(api, first, name="carol"))["candidate"]["item_id"] == second["item_id"]
    assert await next_item(api, first, name="carol") is None
    assert (await api.request("POST", answer_path(second), "carol", json=answer())).status_code == 200
    # Unsure votes do not count toward the target.
    await api.sql("UPDATE label_assignment SET last_shown_at = now() - interval '31 minutes' "
                  "WHERE corpus_id = :c", c=first["corpus_id"])
    assert (await api.request("POST", answer_path(first), "bob", json=answer(1, "unsure"))).status_code == 200
    assert (await next_item(api, first, name="carol"))["candidate"]["item_id"] == first["item_id"]


async def test_items_never_reveal_other_annotators(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    assert (await api.request("POST", answer_path(row), "alice", json=answer(0, "same"))).status_code == 200
    detail = (await api.request("GET", root(row) + "/items/" + row["item_id"], "bob")).json()
    assert detail["judgment"] is None and detail["assignment"] == {"current_revision": 0}
    assert (await api.request("GET", root(row) + "/items", "bob", params={"state": "mine_labelled"})).json()["items"] == []
    mine = (await api.request("GET", root(row) + "/items", "alice", params={"state": "mine_labelled"})).json()
    assert [i["judgment"]["answer"] for i in mine["items"]] == ["same"]
    progress = (await api.request("GET", root(row) + "/progress", "bob")).json()
    assert progress["kinds"]["pair"] == {"total": 1, "reviewed": 0, "unsure": 0, "definite": 0, "items_with_votes": 1}
    assert progress["revision_events"] == 0


async def test_per_annotator_revisions_and_queues(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    a = await api.request("POST", answer_path(row), "alice", json=answer(0, "same"))
    b = await api.request("POST", answer_path(row), "bob", json=answer(0, "different"))
    assert a.json()["revision"] == 1 and b.json()["revision"] == 1
    assert (await api.request("POST", answer_path(row), "alice", json=answer(1, "unsure"))).json()["revision"] == 2
    unsure = (await api.request("GET", root(row) + "/items", "alice", params={"state": "mine_unsure"})).json()["items"]
    assert [(i["judgment"]["answer"], i["assignment"]["current_revision"]) for i in unsure] == [("unsure", 2)]
    assert (await api.request("GET", root(row) + "/items", "alice", params={"state": "mine_labelled"})).json()["items"] == []
    stale = await api.request("POST", answer_path(row), "alice", json=answer(1, "same"))
    assert stale.status_code == 409 and stale.json()["detail"] == {"code": "revision_conflict", "current_revision": 2}


async def test_same_user_concurrency_and_cross_user_parallelism(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    same = await asyncio.gather(*(api.request("POST", answer_path(row), "alice", json=answer(0, value))
                                  for value in ("same", "different")))
    assert sorted(r.status_code for r in same) == [200, 409]
    cross = await asyncio.gather(api.request("POST", answer_path(rows[1]), "alice", json=answer(0, "confirmed", lemma="kuća")),
                                 api.request("POST", answer_path(rows[1]), "bob", json=answer(0, "confirmed", lemma="kuća")))
    assert [r.status_code for r in cross] == [200, 200]


async def test_replay_is_idempotent_and_conflicting_reuse_is_refused(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    payload = answer()
    first = await api.request("POST", answer_path(row), "alice", json=payload)
    assert first.status_code == 200 and first.json()["revision"] == 1
    assert (await api.request("POST", answer_path(row), "alice", json=payload)).json() == first.json()
    changed = await api.request("POST", answer_path(row), "alice", json=dict(payload, answer="different"))
    assert changed.status_code == 409 and changed.json()["detail"]["code"] == "request_id_conflict"
    stolen = await api.request("POST", answer_path(row), "bob", json=payload)
    assert stolen.status_code == 409 and stolen.json()["detail"]["code"] == "request_id_conflict"
    count = (await api.sql("SELECT count(*) FROM label_judgment WHERE id = :id", id=payload["request_id"])).scalar_one()
    assert count == 1


async def test_judgment_provenance_is_recorded(api):
    rows = await api.imported()
    await api.consent("alice")
    payload = answer(0, "accept", client_version="0.2.0", elapsed_ms=4321)
    assert (await api.request("POST", answer_path(rows[2]), "alice", json=payload)).status_code == 200
    stored = (await api.sql("SELECT annotator_id, item_revision, client_version, source, elapsed_ms, created_at "
                            "FROM label_judgment WHERE id = :id", id=payload["request_id"])).one()
    assert str(stored.annotator_id) == await api.annotator_id("alice")
    assert (stored.item_revision, stored.client_version, stored.source, stored.elapsed_ms) == (1, "0.2.0", "web", 4321)
    assert stored.created_at is not None


async def test_unpublish_hides_items_and_retired_items_are_refused(api):
    rows = await api.imported()
    row = rows[0]
    await api.consent("alice")
    await api.sql("UPDATE label_item SET status = 'retired' WHERE corpus_id = :c AND id = :i",
                  c=row["corpus_id"], i=row["item_id"])
    retired = await api.request("POST", answer_path(row), "alice", json=answer())
    assert retired.status_code == 409 and retired.json()["detail"]["code"] == "item_retired"
    assert await next_item(api, row) is None
    assert (await api.request("POST", root(row) + "/unpublish", "curator", True)).status_code == 200
    assert row["corpus_id"] not in {c["id"] for c in await listed(api, "alice")}
    assert (await api.request("GET", root(row) + "/next", "alice", params={"kind": "lemma"})).status_code == 404
    assert (await api.request("POST", answer_path(rows[1]), "alice", json=answer(0, "unsure"))).status_code == 404
    again = await api.request("POST", root(row) + "/unpublish", "curator", True)
    assert again.status_code == 409 and again.json()["detail"]["code"] == "corpus_not_published"
    assert (await api.request("POST", root(row) + "/archive", "curator", True)).json()["corpus"]["status"] == "archived"


async def test_export_tsv_roundtrip_two_annotators_and_excluded(api):
    rows = await api.imported()
    row = rows[0]
    for name in ("alice", "bob"):
        await api.consent(name)
    assert (await api.request("POST", answer_path(row), "alice", json=answer(0, "same"))).status_code == 200
    assert (await api.request("POST", answer_path(row), "alice", json=answer(1, "different"))).status_code == 200
    assert (await api.request("POST", answer_path(row), "bob", json=answer(0, "different"))).status_code == 200
    assert (await api.request("POST", answer_path(rows[1]), "bob",
                              json=answer(0, "confirmed", lemma=" KUĆA ", irregular=True))).status_code == 200
    r = await api.request("GET", root(row) + "/export.tsv", "curator", True)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    exported = list(read_tsv(io.StringIO(r.text)))
    alice, bob = await api.annotator_id("alice"), await api.annotator_id("bob")
    assert len(exported) == 4 and {x.annotator_id for x in exported} == {alice, bob}
    assert all(x.provenance == "human" for x in exported)
    assert next(x for x in exported if x.kind == "lemma").lemma == "kuća"
    accepted, counts = resolve(exported)
    assert counts["annotators"] == 2 and counts["multi_annotator_agreed_items"] == 1
    assert {(a.kind, a.answer) for a in accepted} == {("pair", "different"), ("lemma", "confirmed")}
    # Blocking bob drops his rows unless include_excluded is asked for.
    put = await api.request("PUT", f"/api/admin/annotators/{bob}/status", "curator", True,
                            json={"status": "blocked", "reason": "synthetic test"})
    assert put.status_code == 200
    kept = list(read_tsv(io.StringIO((await api.request("GET", root(row) + "/export.tsv", "curator", True)).text)))
    assert {x.annotator_id for x in kept} == {alice}
    everything = await api.request("GET", root(row) + "/export.tsv", "curator", True, params={"include_excluded": "true"})
    assert len(list(read_tsv(io.StringIO(everything.text)))) == 4
    lines = [json.loads(line) for line in
             (await api.request("GET", root(row) + "/export.jsonl", "curator", True,
                                params={"include_excluded": "true"})).text.splitlines()]
    assert len(lines) == 4
    sample = next(x for x in lines if x["annotator_id"] == bob and x["candidate"]["kind"] == "lemma")
    assert sample["excluded"] is True and sample["annotator_status"] == "blocked"
    assert {"item_revision", "client_version", "source", "elapsed_ms", "created_at"} <= set(sample)
    assert sample["elapsed_ms"] == 1234 and sample["client_version"] == "0.2.0-test"
    for path in ("/export.tsv", "/export.jsonl"):
        assert (await api.request("GET", root(row) + path, "alice")).status_code == 403


async def test_invalid_answers_and_immutable_source_do_not_write(api):
    rows = await api.imported()
    row = rows[0]
    await api.consent("alice")
    invalid = (answer(value="confirmed", lemma="kuća"), answer(owner_id="spoof"), answer(irregular="false"),
               answer(revision=True), answer(client_version=""), answer(client_version="x" * 33),
               answer(client_version="1.0 beta"), answer(elapsed_ms=-1), answer(elapsed_ms=3_600_001),
               answer(elapsed_ms=1.5), answer(annotator_id="spoof"), answer(created_at="2020-01-01T00:00:00Z"))
    for payload in invalid:
        assert (await api.request("POST", answer_path(row), "alice", json=payload)).status_code == 422
    missing = answer()
    del missing["client_version"]
    assert (await api.request("POST", answer_path(row), "alice", json=missing)).status_code == 422
    for key, value in (("word", "dom"), ("source_uri", "urn:other")):
        r = await api.request("POST", "/api/import", "curator", True, json={"name": "Changed", "candidates": [dict(row, **{key: value})]})
        assert r.status_code == 409
    for changed in (dict(row, answer="same"), dict(row, word="x" * 129), dict(row, candidate_schema_version=True)):
        r = await api.request("POST", "/api/import", "curator", True, json={"name": "Invalid", "candidates": [changed]})
        assert r.status_code == 422
    assert (await api.request("GET", root(row) + "/progress", "alice")).json()["revision_events"] == 0


async def test_reimport_preserves_items(api):
    rows = await api.imported()
    changed = [{**r, "algorithm_sha256": "c" * 64} for r in rows]
    r = await api.request("POST", "/api/import", "curator", True, json={"name": "Again", "candidates": changed})
    assert r.json()["added"] == 0 and r.json()["already_present"] == 3
    await api.consent("alice")
    assert (await next_item(api, rows[0]))["candidate"]["algorithm_sha256"] == "b" * 64
    more = rows + [dict(rows[0], item_id=str(uuid4()), word_ref="test:3")]
    assert (await api.request("POST", "/api/import", "curator", True, json={"name": "More", "candidates": more})).json()["added"] == 1
    assert (await api.request("GET", root(rows[0]) + "/progress", "alice")).json()["kinds"]["pair"]["total"] == 2


async def test_import_writes_queue_and_membership_rows_once(api):
    """Every imported item gets its label_item_state row and its journaled label_item_audit
    row in the import's transaction; a re-import keeps both as they are."""
    rows = await api.imported()
    corpus = rows[0]["corpus_id"]
    state = "SELECT item_id::text, kind, state, n_low FROM label_item_state WHERE corpus_id = :c ORDER BY item_id"
    audit = ("SELECT item_id::text, seq, audit_sample, review_sample, audit_rank FROM label_item_audit "
             "WHERE corpus_id = :c ORDER BY item_id")
    first = (await api.sql(state, c=corpus)).all()
    assert sorted((r.item_id, r.kind) for r in first) == sorted((r["item_id"], r["kind"]) for r in rows)
    bits = (await api.sql(audit, c=corpus)).all()
    assert len(bits) == len(rows) and all(r.seq is not None for r in bits)
    await api.sql("UPDATE label_item_state SET n_low = 4 WHERE corpus_id = :c", c=corpus)
    again = await api.request("POST", "/api/import", "curator", True, json={"name": "Again", "candidates": rows})
    assert again.status_code == 200
    assert {r.n_low for r in (await api.sql(state, c=corpus)).all()} == {4}
    assert (await api.sql(audit, c=corpus)).all() == bits


@pytest.mark.parametrize("parameter", ["offset", "after"])
async def test_pagination_rejects_postgres_integer_overflow(api, parameter):
    rows = await api.imported()
    await api.consent("alice")
    route = "/api/corpora" if parameter == "offset" else root(rows[0]) + "/items"
    maximum = 2**31 - 1
    assert (await api.request("GET", route, "alice", params={parameter: maximum})).status_code == 200
    for value in (maximum + 1, 10**20):
        response = await api.request("GET", route, "alice", params={parameter: value})
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["query", parameter]


CURATOR_ROUTES = [
    ("POST", "/api/import", {"name": "x", "candidates": []}),
    ("POST", "/api/corpora/{c}/publish", {"labels_license": "CC BY-SA 4.0"}),
    ("POST", "/api/corpora/{c}/unpublish", None),
    ("POST", "/api/corpora/{c}/archive", None),
    ("GET", "/api/corpora/{c}/export.tsv", None),
    ("GET", "/api/corpora/{c}/export.jsonl", None),
    ("GET", "/api/admin/annotators", None),
    ("PUT", "/api/admin/annotators/{a}/status", {"status": "blocked", "reason": "x"}),
    ("GET", "/api/admin/settings", None),
    ("PUT", "/api/admin/settings", {"accepting_judgments": False}),
    ("GET", "/api/admin/erasures", None),
    ("POST", "/api/admin/erasures/1/complete", None),
]


async def test_every_curator_route_refuses_annotators_and_anonymous_callers(api):
    rows = await api.imported()
    await api.consent("alice")
    alice = await api.annotator_id("alice")
    for method, url, body in CURATOR_ROUTES:
        url = url.format(c=rows[0]["corpus_id"], a=alice)
        # A token with a look-alike group, or the annotator group, is still not a curator.
        for groups in ([], ["annotator"], ["Curator"], ["/curator"]):
            r = await api.request(method, url, "alice", json=body, headers=api.headers("alice", groups=groups))
            assert r.status_code == 403 and r.json()["detail"]["code"] == "curator_required", (method, url, groups)
        assert (await api.client.request(method, url, json=body)).status_code == 401
    # The corpus was not changed by any of the refused calls.
    assert (await api.request("GET", "/api/corpora", "curator", True)).status_code == 200
    status = (await api.sql("SELECT status FROM label_corpus WHERE id = :c", c=rows[0]["corpus_id"])).scalar_one()
    assert status == "published"


async def test_annotator_status_blocks_and_is_journaled(api):
    rows = await api.imported()
    await api.consent("alice")
    alice = await api.annotator_id("alice")
    curator = await api.annotator_id("curator")
    reason = '<img src=x onerror=alert(1)> spam'
    r = await api.request("PUT", f"/api/admin/annotators/{alice}/status", "curator", True,
                          json={"status": "blocked", "reason": reason})
    assert r.status_code == 200
    for method, url in (("GET", "/api/corpora"), ("GET", root(rows[0]) + "/next"), ("POST", answer_path(rows[0]))):
        r = await api.request(method, url, "alice", json=answer() if method == "POST" else None)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "account_blocked"
    me = await api.request("GET", "/api/me", "alice")
    assert me.status_code == 200 and me.json()["status"] == "blocked"
    event = (await api.sql("SELECT actor_id, details FROM label_admin_event WHERE kind = 'annotator.status' "
                           "AND target = :t ORDER BY id DESC LIMIT 1", t=alice)).one()
    assert str(event.actor_id) == curator and event.details == {"from": "active", "to": "blocked", "reason": reason}
    listed = (await api.request("GET", "/api/admin/annotators", "curator", True, params={"status": "blocked"})).json()["items"]
    assert any(a["id"] == alice and a["email"] == "alice@example.org" and a["status_reason"] == reason for a in listed)
    own = await api.request("PUT", f"/api/admin/annotators/{curator}/status", "curator", True,
                            json={"status": "blocked", "reason": "oops"})
    assert own.status_code == 409 and own.json()["detail"]["code"] == "own_status_change"
    erased_status = await api.request("PUT", f"/api/admin/annotators/{alice}/status", "curator", True,
                                      json={"status": "erased", "reason": "x"})
    assert erased_status.status_code == 422
    quarantined = await api.request("PUT", f"/api/admin/annotators/{alice}/status", "curator", True,
                                    json={"status": "quarantined", "reason": "review"})
    assert quarantined.status_code == 200
    # Quarantined accounts keep labeling in V1; the trust model weighs them later.
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200


async def test_unverified_email_is_not_stored(api):
    await api.request("GET", "/api/me", "dana", headers=api.headers("dana", email_verified=False))
    stored = (await api.sql("SELECT email, email_verified FROM label_annotator WHERE subject = :s",
                            s=api.identity.subjects["dana"])).one()
    assert stored == (None, False)


async def test_me_reports_consent_and_counts(api):
    rows = await api.imported()
    me = (await api.request("GET", "/api/me", "alice")).json()
    assert me["consented"] is False and me["consent"] == {"privacy": None, "terms": None, "participation": None}
    assert me["curator"] is False and me["required"] == REQUIRED
    await api.consent("alice")
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    me = (await api.request("GET", "/api/me", "alice")).json()
    assert me["consented"] is True and me["counts"] == {"judgments": 1, "items_labelled": 1}
    assert "subject" not in me and "email" not in me
    assert (await api.request("GET", "/api/me", "curator", True)).json()["curator"] is True

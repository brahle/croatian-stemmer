"""The consent gate: nothing is labeled before the current terms and participation
statement are accepted, the current privacy notice shown and age 18 confirmed."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import REQUIRED, answer, answer_path

pytestmark = pytest.mark.asyncio


def consent_body(settings, **changes):
    return {"privacy_version": settings.privacy_version, "terms_version": settings.terms_version,
            "participation_version": settings.participation_version, "age_confirmed": True,
            "age_threshold": 18, "locale": "hr", "ui_version": "0.2.0", **changes}


async def judgments(api, name):
    return (await api.sql("SELECT count(*) FROM label_judgment WHERE annotator_id = :a",
                          a=await api.annotator_id(name))).scalar_one()


async def consent_rows(api, name, rows):
    """Write consent rows directly (as an older release or a partial gate would have)."""
    annotator = await api.annotator_id(name)
    for document, version, age in rows:
        await api.sql("INSERT INTO label_consent (annotator_id, document, version, locale, age_confirmed, "
                      "age_threshold, ui_version) VALUES (:a, :d, :v, 'hr', true, :age, '0.2.2')",
                      a=annotator, d=document, v=version, age=age)


async def test_gate_blocks_queue_and_answers_until_consent(api):
    rows = await api.imported()
    row = rows[0]
    root = f'/api/corpora/{row["corpus_id"]}'
    for method, url in (("GET", root + "/next"), ("GET", root + "/items"), ("GET", root + "/items/" + row["item_id"]),
                        ("POST", answer_path(row))):
        r = await api.request(method, url, "alice", json=answer() if method == "POST" else None)
        assert r.status_code == 403, (url, r.text)
        assert r.json()["detail"] == {"code": "consent_required", "required": REQUIRED}
    assert await judgments(api, "alice") == 0
    # Signed in but not consented: the account itself and public corpus metadata are reachable.
    assert (await api.request("GET", "/api/me", "alice")).status_code == 200
    assert (await api.request("GET", "/api/corpora", "alice")).status_code == 200
    r = await api.request("POST", "/api/me/consent", "alice", json=consent_body(api.settings))
    assert r.status_code == 200 and r.json() == {"consented": True, "required": REQUIRED}
    assert (await api.request("POST", answer_path(row), "alice", json=answer())).status_code == 200
    rows = (await api.sql("SELECT document, version, locale, age_confirmed, age_threshold, ui_version FROM label_consent "
                          "WHERE annotator_id = :a ORDER BY document", a=await api.annotator_id("alice"))).all()
    assert [tuple(r) for r in rows] == [("participation", "1.0", "hr", True, 18, "0.2.0"),
                                        ("privacy", "1.4", "hr", True, 18, "0.2.0"),
                                        ("terms", "1.1", "hr", True, 18, "0.2.0")]
    # Repeating the consent is idempotent.
    assert (await api.request("POST", "/api/me/consent", "alice", json=consent_body(api.settings))).status_code == 200
    assert len((await api.sql("SELECT id FROM label_consent WHERE annotator_id = :a",
                              a=await api.annotator_id("alice"))).all()) == 3


async def test_participation_consent_is_required_separately(api):
    rows = await api.imported()
    assert (await api.request("GET", "/api/me", "alice")).status_code == 200
    # Notice and terms at the current versions, but no participation consent: refused.
    await consent_rows(api, "alice", [("privacy", "1.4", 18), ("terms", "1.1", 18)])
    r = await api.request("POST", answer_path(rows[0]), "alice", json=answer())
    assert r.status_code == 403 and r.json()["detail"] == {"code": "consent_required", "required": REQUIRED}
    assert (await api.request("GET", "/api/me", "alice")).json()["consented"] is False
    # All three at the configured versions with age 18: the answer is accepted.
    await consent_rows(api, "alice", [("participation", "1.0", 18)])
    assert (await api.request("GET", "/api/me", "alice")).json()["consented"] is True
    assert (await api.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    assert await judgments(api, "alice") == 1


async def test_consent_confirmed_for_age_16_does_not_count(api):
    # Rows like the ones 0.2.2 wrote (16+, no age_threshold) at the current versions are not enough.
    rows = await api.imported()
    assert (await api.request("GET", "/api/me", "bob")).status_code == 200
    await consent_rows(api, "bob", [("privacy", "1.4", None), ("terms", "1.1", None), ("participation", "1.0", None)])
    r = await api.request("POST", answer_path(rows[0]), "bob", json=answer())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    assert (await api.request("GET", "/api/me", "bob")).json()["consented"] is False
    assert await judgments(api, "bob") == 0


async def test_version_mismatch_and_age_are_refused(api):
    for changes in ({"privacy_version": "1.1"}, {"terms_version": "1.0"}, {"participation_version": "0.9"}):
        r = await api.request("POST", "/api/me/consent", "alice", json=consent_body(api.settings, **changes))
        assert r.status_code == 409 and r.json()["detail"]["code"] == "consent_version_mismatch"
        assert r.json()["detail"]["required"] == REQUIRED
    for changes in ({"age_confirmed": False}, {"age_confirmed": "true"}, {"age_confirmed": 1},
                    {"age_threshold": 16}, {"age_threshold": 17}, {"age_threshold": "18"}, {"age_threshold": 18.0},
                    {"locale": "de"}, {"ui_version": "a b"}, {"extra": 1}):
        r = await api.request("POST", "/api/me/consent", "alice", json=consent_body(api.settings, **changes))
        assert r.status_code == 422, changes
    # A 0.2.2 client's body (no participation, no age threshold) is refused too.
    for field in ("age_confirmed", "age_threshold", "participation_version"):
        body = consent_body(api.settings)
        del body[field]
        assert (await api.request("POST", "/api/me/consent", "alice", json=body)).status_code == 422, field
    count = (await api.sql("SELECT count(*) FROM label_consent WHERE annotator_id = :a",
                           a=await api.annotator_id("alice"))).scalar_one()
    assert count == 0


async def test_new_terms_version_regates_and_keeps_old_records(make_api, monkeypatch, tmp_path):
    from croatian_stemmer.labeling.web import api as api_module
    first = await make_api()
    rows = await first.imported()
    await first.consent("alice")
    assert (await first.request("POST", answer_path(rows[0]), "alice", json=answer())).status_code == 200
    # The owner publishes terms 1.2: documents and configuration change together.
    for path in api_module.DOCUMENTS.iterdir():
        text = path.read_text(encoding="utf-8")
        if path.name.startswith("terms."):
            text = text.replace('<meta name="document-version" content="1.1">',
                                '<meta name="document-version" content="1.2">')
        (tmp_path / path.name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(api_module, "DOCUMENTS", tmp_path)
    bumped = await make_api(terms_version="1.2")
    bumped.identity.private, bumped.identity.subjects = first.identity.private, first.identity.subjects
    bumped.identity.install(bumped.app)
    r = await bumped.request("POST", answer_path(rows[1]), "alice", json=answer(0, "unsure"))
    assert r.status_code == 403 and r.json()["detail"]["required"] == {**REQUIRED, "terms": "1.2"}
    me = (await bumped.request("GET", "/api/me", "alice")).json()
    assert me["consented"] is False and me["consent"] == REQUIRED
    await bumped.consent("alice")
    assert (await bumped.request("POST", answer_path(rows[1]), "alice", json=answer(0, "unsure"))).status_code == 200
    versions = (await bumped.sql("SELECT document, version FROM label_consent WHERE annotator_id = :a "
                                 "ORDER BY document, version", a=await bumped.annotator_id("alice"))).all()
    assert [tuple(v) for v in versions] == [("participation", "1.0"), ("privacy", "1.4"),
                                            ("terms", "1.1"), ("terms", "1.2")]

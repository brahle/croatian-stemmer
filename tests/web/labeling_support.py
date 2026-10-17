"""Shared, synthetic fixtures for the web tests. Nothing here is dataset gold."""
import os
import time
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://identity.example/realms/test"
COMPLIANCE = {"controller_name": "Example Controller", "controller_email": "privacy@example.org",
              "hosting_summary": "Example Hosting Ltd, Germany", "edge_log_retention": "7 days",
              "backup_retention": "14 days"}
# The document versions this release ships and requires (config defaults).
REQUIRED = {"privacy": "1.2", "terms": "1.1", "participation": "1.0"}


def make_settings(database_url="postgresql+asyncpg://test@localhost/labeling_test", issuer=ISSUER, **changes):
    from croatian_stemmer.labeling.web.config import Settings
    return Settings(database_url, issuer, **{**COMPLIANCE, **changes})


def database_url_for_tests():
    dsn = os.getenv("LABELING_TEST_DATABASE_URL")
    if not dsn:
        return None
    if not dsn.rsplit("/", 1)[-1].endswith("_test"):
        raise ValueError("Use a dedicated *_test database; do not run against human labels")
    return dsn


def candidates(license="CC BY-SA 4.0", pairs=1):
    corpus = str(uuid4())
    base = {"candidate_schema_version": 1, "corpus_id": corpus, "corpus_sha256": "a" * 64,
            "source_uri": "urn:test:synthetic-only", "license": license,
            "item_id": str(uuid4()), "kind": "pair", "word": "kuće", "other_word": "kuća",
            "proposed_lemma": "kuća", "other_proposed_lemma": "kuća", "proposed_stem": "",
            "upos": "NOUN", "context": "Sintetički primjer kuće.", "other_context": "Sintetički primjer kuća.",
            "word_ref": "test:1", "other_word_ref": "test:2", "sampling_stratum": "test",
            "algorithm_sha256": "b" * 64}
    lemma = {**base, "item_id": str(uuid4()), "kind": "lemma", "other_word": "", "other_context": "",
             "other_word_ref": "", "other_proposed_lemma": ""}
    stem = {**lemma, "item_id": str(uuid4()), "kind": "stem", "proposed_stem": "kuć"}
    extra = [{**base, "item_id": str(uuid4()), "word_ref": f"test:pair:{n}"} for n in range(1, pairs)]
    return [base, *extra, lemma, stem]


class Identity:
    """Signs realm-like access tokens for named synthetic people."""

    def __init__(self, settings):
        self.settings = settings
        self.private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.subjects = {}

    def install(self, app):
        app.state.auth.keys = {"test": self.private.public_key()}
        app.state.auth.loaded_at = time.monotonic()

    def token(self, name="alice", curator=False, **claims):
        subject = self.subjects.setdefault(name, str(uuid4()))
        s = self.settings
        payload = {"sub": subject, "iss": s.issuer, "aud": s.audience, "azp": s.client_id, "typ": "Bearer",
                   "iat": int(time.time()), "exp": int(time.time()) + 300,
                   "preferred_username": f"{name}@example.org", "email": f"{name}@example.org",
                   "email_verified": True, "groups": ["curator"] if curator else []}
        payload.update(claims)
        return jwt.encode(payload, self.private, algorithm="RS256", headers={"kid": "test"})

    def headers(self, name="alice", curator=False, **claims):
        return {"Authorization": "Bearer " + self.token(name, curator, **claims)}


def answer(revision=0, value="same", **extra):
    return {"request_id": str(uuid4()), "base_revision": revision, "answer": value,
            "client_version": "0.2.0-test", "elapsed_ms": 1234, **extra}


def answer_path(row):
    return f'/api/corpora/{row["corpus_id"]}/items/{row["item_id"]}/answer'


class Api:
    """An httpx client on the ASGI app plus helpers for the common flows."""

    def __init__(self, client, identity, app, settings):
        self.client, self.identity, self.app, self.settings = client, identity, app, settings
        self.headers = identity.headers

    def request(self, method, url, name="alice", curator=False, **kwargs):
        return self.client.request(method, url, headers={**self.headers(name, curator), **kwargs.pop("headers", {})},
                                   **kwargs)

    async def consent(self, name="alice", curator=False):
        s = self.settings
        r = await self.request("POST", "/api/me/consent", name, curator,
                               json={"privacy_version": s.privacy_version, "terms_version": s.terms_version,
                                     "participation_version": s.participation_version, "age_confirmed": True,
                                     "age_threshold": 18, "locale": "hr", "ui_version": "0.2.0-test"})
        assert r.status_code == 200, r.text
        return r

    async def imported(self, rows=None, publish="CC BY-SA 4.0", curator="curator"):
        rows = rows or candidates()
        r = await self.request("POST", "/api/import", curator, True, json={"name": "Sintetički test", "candidates": rows})
        assert r.status_code == 200, r.text
        if publish:
            p = await self.request("POST", f'/api/corpora/{rows[0]["corpus_id"]}/publish', curator, True,
                                   json={"labels_license": publish})
            assert p.status_code == 200, p.text
        return rows

    async def sql(self, statement, **params):
        from sqlalchemy import text
        async with self.app.state.engine.begin() as connection:
            return await connection.execute(text(statement), params)

    async def annotator_id(self, name):
        import hashlib
        subject = self.identity.subjects[name]
        row = (await self.sql("SELECT id FROM label_annotator WHERE subject = :s", s=subject)).one_or_none()
        if row is None:
            hashed = hashlib.sha256(subject.encode()).hexdigest()
            row = (await self.sql("SELECT annotator_id FROM label_erasure_request WHERE subject_sha256 = :h",
                                  h=hashed)).one()
        return str(row[0])


async def open_api(settings):
    import httpx
    from croatian_stemmer.labeling.web.api import create_app
    app = create_app(settings)
    identity = Identity(settings)
    identity.install(app)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app.test")
    return Api(client, identity, app, settings)


async def close_api(api):
    await api.client.aclose()
    await api.app.state.engine.dispose()

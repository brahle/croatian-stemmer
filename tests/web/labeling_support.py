"""Shared, synthetic fixtures for the web tests. Nothing here is dataset gold."""
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://identity.example/realms/test"
COMPLIANCE = {"controller_name": "Example Controller", "controller_email": "privacy@example.org",
              "hosting_summary": "Example Hosting Ltd, Germany", "edge_log_retention": "7 days",
              "backup_retention": "14 days"}
# The document versions this release ships and requires (config defaults).
REQUIRED = {"privacy": "1.4", "terms": "1.1", "participation": "1.0"}


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


ROOT = Path(__file__).resolve().parents[2]


def alembic(url, *args, allow_drop=None):
    """Run alembic against `url` in a subprocess (as the init container does)."""
    env = {k: v for k, v in os.environ.items() if k != "LABELING_MIGRATION_ALLOW_DROP"}
    env["LABELING_DATABASE_URL"] = url
    if allow_drop is not None:
        env["LABELING_MIGRATION_ALLOW_DROP"] = allow_drop
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=300)


def plain(url):
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def query(url, statement, script=False):
    """One statement (or a script) on its own asyncpg connection, outside any event loop."""
    import asyncio
    import asyncpg

    async def run():
        connection = await asyncpg.connect(plain(url))
        try:
            return await (connection.execute if script else connection.fetch)(statement)
        finally:
            await connection.close()
    return asyncio.run(run())


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


# Gold is invisible to annotators (4.3.6): no non-curator response anywhere in the suite may
# name gold, the audit machinery or a gold basis. Qualification is announced, so it may appear.
# "ordinal": the import position would single out items imported together (a gold reserve).
HIDDEN = ("gold", "audit", "corpus_unambiguous", "anchor_consensus", "ordinal", "reserve")


def hidden_from_annotators(url, response):
    body = response.text.lower()
    for word in HIDDEN:
        assert word not in body, f"a non-curator response to {url} names {word!r}: {response.text[:300]}"


class Api:
    """An httpx client on the ASGI app plus helpers for the common flows."""

    def __init__(self, client, identity, app, settings):
        self.client, self.identity, self.app, self.settings = client, identity, app, settings
        self.headers = identity.headers

    async def request(self, method, url, name="alice", curator=False, fetched=True, **kwargs):
        """One API call as `name`. Answers count as fetched: unless `fetched=False`, an answer to an
        item the person was never shown gets the assignment /next would have created first (the
        tests that are about what /next serves fetch through /next)."""
        if fetched and method == "POST" and url.endswith("/answer") and name in self.identity.subjects:
            _, _, corpus, _, item, _ = url.rsplit("/", 5)
            await self.sql("""INSERT INTO label_assignment (annotator_id, corpus_id, item_id, first_shown_at,
                                last_shown_at, shown_count, presentation)
                              SELECT a.id, :c, :i, now(), now(), 1, 'shown' FROM label_annotator a
                              WHERE a.subject = :s AND EXISTS (SELECT 1 FROM label_item WHERE corpus_id = :c AND id = :i)
                              ON CONFLICT DO NOTHING""", c=corpus, i=item, s=self.identity.subjects[name])
        response = await self.client.request(method, url, headers={**self.headers(name, curator),
                                                                    **kwargs.pop("headers", {})}, **kwargs)
        if not curator and url.startswith("/api/"):
            hidden_from_annotators(url, response)
        return response

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


async def profiled(api, name="alice", curator=False):
    """Consent through the gate, plus the privacy notice that announces profiling: the
    annotator is in the scoring cohort (4.13.1). Returns the annotator id."""
    await api.consent(name, curator)
    annotator = await api.annotator_id(name)
    await api.sql("INSERT INTO label_consent (annotator_id, document, version, locale, age_confirmed, age_threshold, "
                  "ui_version) VALUES (:a, 'privacy', '1.4', 'hr', true, 18, 'test') ON CONFLICT DO NOTHING", a=annotator)
    return annotator


async def score_now(api, **kwargs):
    """One scoring run (waiting for the scoring lock); returns [(run_id, status)]."""
    from croatian_stemmer.labeling.web.scoring_run import run_now
    return await run_now(api.app.state.ctx, wait=True, **kwargs)


def gold_line(row, answer=None, pool="audit", lemma=None):
    """A gold-builder line for a candidate (synthetic; never dataset gold)."""
    kind = row["kind"]
    answer = answer or {"pair": "same", "lemma": "confirmed", "stem": "accept"}[kind]
    lemma = (row["proposed_lemma"] if lemma is None else lemma) if kind == "lemma" else ""
    return {"gold_schema_version": 1, "corpus_id": row["corpus_id"], "item_id": row["item_id"], "kind": kind,
            "pool": pool, "answer": answer, "lemma": lemma, "basis": "test", "source": "hr500k",
            "corpus_sha256": row["corpus_sha256"], "batch": "test"}


async def sampled(api, rows):
    """The candidates whose keyed calibration bit is set (never gold)."""
    found = {str(r[0]) for r in (await api.sql(
        "SELECT item_id FROM label_item_audit WHERE corpus_id = :c AND audit_sample", c=rows[0]["corpus_id"])).all()}
    return [row for row in rows if row["item_id"] in found]


async def unsampled(api, rows):
    held = {row["item_id"] for row in await sampled(api, rows)}
    return [row for row in rows if row["item_id"] not in held]


def unlimited(api):
    """Lift the per-annotator rate limits (tests that answer many items quickly)."""
    from croatian_stemmer.labeling.web.limits import Rate
    api.app.state.ctx.limiter.rates = {name: Rate(10 ** 9, 10 ** 9) for name in ("answer", "read", "account")}
    return api


async def scoring_on(api):
    """Enable scoring (the curator's switch); /next then uses the trust scheduler."""
    r = await api.request("PUT", "/api/admin/scoring/settings", "curator", True, json={"scoring_enabled": True})
    assert r.status_code == 200, r.text
    api.app.state.ctx.forget_settings()


def pair_rows(n, corpus=None, different_every=2):
    """n pair candidates of one synthetic corpus; every `different_every`-th has different
    proposed lemmas (so the suggestion implies `different`)."""
    corpus = corpus or str(uuid4())
    base = candidates()[0]
    rows = []
    for i in range(n):
        different = different_every and i % different_every == 1
        rows.append({**base, "corpus_id": corpus, "item_id": str(uuid4()), "word_ref": f"test:pair:{i}",
                     "other_proposed_lemma": "kućica" if different else base["other_proposed_lemma"],
                     "other_word": "kućice" if different else base["other_word"]})
    return rows


async def make_anchor(api, name="owner"):
    """Put `name`'s verified email on the trusted list through the curator route; the next
    authenticated request of `name` grants the anchor. Returns the annotator id."""
    r = await api.request("POST", "/api/admin/trusted", "curator", True,
                          json={"email": f"{name}@example.org", "label": name.capitalize()})
    assert r.status_code in (200, 409), r.text
    await profiled(api, name)
    annotator = await api.annotator_id(name)
    granted = (await api.sql("SELECT count(*) FROM label_anchor WHERE annotator_id = :a", a=annotator)).scalar_one()
    assert granted == 1
    api.app.state.ctx.forget_settings()
    return annotator


async def easy_params(api, **changes):
    """Small readiness and promotion thresholds, so a test can promote someone with a dozen
    known answers (the rules are the defaults' rules; only the numbers are smaller)."""
    r = await api.request("GET", "/api/admin/scoring/params", "curator", True)
    params = r.json()["params"]
    params["readiness"].update({"qualification_pool": 1, "audit_pool": 12, "wrong_suggestion_pool": 12,
                                "stem_qualification_pool": 1, "stem_audit_pool": 2, "anchors": 1})
    params.update({"established_disc_gold": 12, "established_votes": 12, "established_wrong_sugg_gold": 12,
                   "qualification_n": 1, "qualification_hits": 1})
    for key, value in changes.items():
        params[key] = value
    r = await api.request("PUT", "/api/admin/scoring/params", "curator", True, json={"params": params})
    assert r.status_code == 200, r.text
    return params


async def wrong_suggestion_gold(api, rows, n=12):
    """Curator gold on n unsampled pair items whose answer differs from the suggestion."""
    free = [r for r in await unsampled(api, rows) if r["kind"] == "pair"
            and r["proposed_lemma"] == r["other_proposed_lemma"]][:n]
    assert len(free) == n
    for row in free:
        r = await api.request("PUT", f'/api/admin/gold/{row["corpus_id"]}/{row["item_id"]}', "curator", True,
                              json={"action": "set", "pool": "audit", "answer": "different", "reason": "test"})
        assert r.status_code == 200, r.text
    return free


async def promote(api, name, gold_rows, value="different"):
    """`name` answers the given gold correctly (twelve discriminating answers)."""
    await profiled(api, name)
    for row in gold_rows:
        r = await api.request("POST", answer_path(row), name, json=answer(value=value))
        assert r.status_code == 200, r.text


def later(days=2):
    """A run's day far enough ahead that today's audit answers are past the gold delay."""
    from datetime import date, timedelta
    return date.today() + timedelta(days=days)


def synthetic_conllu(path, lemmas=120, repeat=6):
    """A synthetic CoNLL-U file: `lemmas` lemmas with five frequent forms each."""
    import string
    letters = string.ascii_lowercase
    lines = []
    for n in range(lemmas):
        lemma = "lem" + letters[n // 26 % 26] + letters[n % 26] + ("x" * (n // 676))
        for _ in range(repeat):
            forms = [lemma + suffix for suffix in ("a", "e", "i", "u", "om")]
            lines.append("# text = " + " ".join(forms))
            lines += [f"{i}\t{form}\t{lemma}\tNOUN" for i, form in enumerate(forms, 1)]
            lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def unseeded(api, rows):
    """Candidates in neither keyed sample (calibration or review): the anchors' seed answers on
    them can become consensus gold."""
    found = {str(r[0]) for r in (await api.sql(
        "SELECT item_id FROM label_item_audit WHERE corpus_id = :c AND (audit_sample OR review_sample)",
        c=rows[0]["corpus_id"])).all()}
    return [row for row in rows if row["item_id"] not in found]

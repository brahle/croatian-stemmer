"""Signed-token tests exercise the production validator without an auth bypass."""
import time

import pytest
jwt = pytest.importorskip("jwt")
pytest.importorskip("fastapi")
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from croatian_stemmer.labeling.web.auth import Authenticator
from croatian_stemmer.labeling.web.config import Settings
from labeling_support import make_settings

@pytest.fixture
def identity():
    settings = make_settings()
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = Authenticator(settings)
    auth.keys, auth.loaded_at = {"test": private.public_key()}, time.monotonic()
    def token(**changes):
        claims = {"sub":"test-human", "iss":settings.issuer,"aud":settings.audience,
                  "azp":settings.client_id,"typ":"Bearer","iat":int(time.time()),
                  "exp":int(time.time())+300,"preferred_username":"synthetic-test-human",
                  "resource_access":{settings.audience:{"roles":[settings.role]}}}
        claims.update(changes)
        return "Bearer "+jwt.encode(claims, private, algorithm="RS256", headers={"kid":"test"})
    return auth, token

@pytest.mark.asyncio
async def test_valid_subject(identity):
    auth,token=identity
    assert (await auth.authenticate(token())).subject == "test-human"

@pytest.mark.parametrize("changes",[
    {"iss":"https://other.example/realms/test"},{"aud":"other"},
    {"exp":int(time.time())-60},{"iat":int(time.time())+60},
    {"azp":"service-client"},{"typ":"ID"},{"preferred_username":"service-account-client"},
    {"sub":""},{"sub":123},{"resource_access":[]},{"resource_access":"bad"},
    {"resource_access":{"croatian-stemmer-labeling-api":[]}},
    {"resource_access":{"croatian-stemmer-labeling-api":{"roles":"annotator"}}},
    {"resource_access":{}},
])
@pytest.mark.asyncio
async def test_reject_claims(identity,changes):
    auth,token=identity
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token(**changes))
    assert exc.value.status_code in (401,403)

@pytest.mark.asyncio
async def test_no_token_or_wrong_signature(identity):
    auth,token=identity
    for value in (None,"Basic xyz","Bearer broken",token()[:-8]+"abcdefgh",
                  "Bearer "+jwt.encode({"sub":"test-human"},"a"*32,algorithm="HS256",headers={"kid":"test"})):
        with pytest.raises(HTTPException) as exc:
            await auth.authenticate(value)
        assert exc.value.status_code==401

@pytest.mark.asyncio
async def test_unknown_key_and_expired_cache_fail_closed(identity,monkeypatch):
    auth,token=identity
    async def unavailable():
        raise HTTPException(503,detail={"code":"identity_unavailable"})
    monkeypatch.setattr(auth,"refresh",unavailable)
    # Older than the 300 s cache window. A literal 0 is not: time.monotonic()
    # counts from boot, so on a runner up for under five minutes 0 looks fresh.
    auth.loaded_at=time.monotonic()-301
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token())
    assert exc.value.status_code==503

@pytest.mark.parametrize("issuer",["http://identity.example/realms/test","https://identity.example/", "https://user:password@identity.example/realms/test","https://identity.example/realms/test?x=1"])
def test_issuer_restrictions(issuer):
    with pytest.raises(ValueError):
        make_settings(issuer=issuer)

@pytest.mark.asyncio
async def test_jwks_refresh_rotation_and_invalid_documents(identity,monkeypatch):
    import json
    import httpx
    from types import SimpleNamespace
    from croatian_stemmer.labeling.web import auth as auth_module
    auth,token=identity
    clock=[1000.0]
    monkeypatch.setattr(auth_module,"time",SimpleNamespace(monotonic=lambda:clock[0]))
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    key={**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key())),"kid":"new","use":"sig","alg":"RS256"}
    original=httpx.AsyncClient
    def document(payload,status=200):
        transport=httpx.MockTransport(lambda request:httpx.Response(status,json=payload))
        monkeypatch.setattr(httpx,"AsyncClient",lambda **kwargs:original(transport=transport,**kwargs))
        auth.loaded_at=0
        clock[0]+=10
    document({"keys":[key]})
    claims=jwt.decode(token()[7:],options={"verify_signature":False})
    rotated="Bearer "+jwt.encode(claims,private,algorithm="RS256",headers={"kid":"new"})
    assert (await auth.authenticate(rotated)).subject=="test-human"
    assert set(auth.keys)=={"new"}
    for payload,status in [({"keys":[]},200),({"keys":[key,key]},200),({"keys":["bad"]},200),({"keys":"bad"},200),({"padding":"x"*262145},200),({},503)]:
        document(payload,status)
        with pytest.raises(HTTPException) as exc:
            await auth.authenticate(rotated)
        assert exc.value.status_code==503


@pytest.mark.parametrize("failure", ["timeout", "status", "document"])
@pytest.mark.asyncio
async def test_failed_jwks_refresh_is_shared_and_recovers_after_cooldown(identity, monkeypatch, failure):
    import asyncio
    import json
    from types import SimpleNamespace

    import httpx
    from croatian_stemmer.labeling.web import auth as auth_module

    auth, token = identity
    clock = [1000.0]
    monkeypatch.setattr(auth_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    auth.loaded_at = 0
    cached_keys = auth.keys.copy()
    kid, public = next(iter(cached_keys.items()))
    key = {**json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public)), "kid": kid}
    started, finish = asyncio.Event(), asyncio.Event()
    calls = 0
    recovered = False

    async def handler(request):
        nonlocal calls
        calls += 1
        if recovered:
            return httpx.Response(200, json={"keys": [key]})
        started.set()
        await finish.wait()
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        if failure == "status":
            return httpx.Response(503)
        return httpx.Response(200, json={"keys": []})

    original = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs))
    callers = [asyncio.create_task(auth.authenticate(token())) for _ in range(5)]
    try:
        await asyncio.wait_for(started.wait(), 2)
        # The timeout completes at this clock value, not at the attempt's start.
        clock[0] += 8
        finish.set()
        results = await asyncio.wait_for(asyncio.gather(*callers, return_exceptions=True), 2)
    finally:
        finish.set()
        for caller in callers:
            if not caller.done():
                caller.cancel()
        await asyncio.gather(*callers, return_exceptions=True)
    assert calls == 1
    assert all(isinstance(result, HTTPException) and result.status_code == 503 for result in results)
    assert auth.keys == cached_keys and auth.loaded_at == 0

    recovered = True
    clock[0] += 9.9
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token())
    assert exc.value.status_code == 503 and calls == 1
    clock[0] = 1018.0
    assert (await auth.authenticate(token())).subject == "test-human"
    assert calls == 2
    assert (await auth.authenticate(token())).subject == "test-human"
    assert calls == 2


def group_identity(role_source="groups", **changes):
    settings = make_settings(role_source=role_source, **changes)
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    auth = Authenticator(settings)
    auth.keys, auth.loaded_at = {"test": private.public_key()}, time.monotonic()
    def token(**changes):
        claims = {"sub":"test-human", "iss":settings.issuer,"aud":settings.audience,
                  "azp":settings.client_id,"typ":"Bearer","iat":int(time.time()),
                  "exp":int(time.time())+300,"preferred_username":"synthetic-test-human",
                  "groups":[settings.role]}
        claims.update(changes)
        claims = {k: v for k, v in claims.items() if v is not ...}
        return "Bearer "+jwt.encode(claims, private, algorithm="RS256", headers={"kid":"test"})
    return auth, token


@pytest.mark.asyncio
async def test_groups_source_accepts_realm_group_membership():
    # Realms that map group membership carry authorization as a flat `groups` claim, not client roles.
    auth, token = group_identity()
    assert (await auth.authenticate(token())).subject == "test-human"
    assert (await auth.authenticate(token(groups=["reader", "annotator"]))).subject == "test-human"


@pytest.mark.parametrize("changes",[
    {"groups":[]},{"groups":"annotator"},{"groups":None},{"groups":["/annotator"]},
    {"groups":["Annotator"]},{"groups":[["annotator"]]},
    {"groups":[], "resource_access":{"croatian-stemmer-labeling-api":{"roles":["annotator"]}}},
    {"aud":"other"},{"azp":"service-client"},{"typ":"ID"},
    {"preferred_username":"service-account-client"},
])
@pytest.mark.asyncio
async def test_groups_source_rejects(changes):
    auth, token = group_identity()
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token(**changes))
    assert exc.value.status_code in (401,403)


@pytest.mark.asyncio
async def test_groups_source_requires_the_claim_to_be_present():
    auth, token = group_identity()
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token(groups=...))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_default_source_ignores_groups(identity):
    # The client-role deployment must not start accepting a realm group as a substitute.
    auth, token = identity
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token(resource_access={}, groups=["annotator"]))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("value", ["", "group", "realm-roles", "GROUPS"])
def test_role_source_must_be_known(value):
    with pytest.raises(ValueError):
        make_settings(role_source=value)


def compliance_environment(monkeypatch):
    import os
    for key in list(os.environ):
        if key.startswith("LABELING_"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("LABELING_DATABASE_URL", "postgresql+asyncpg://test@localhost/labeling_test")
    monkeypatch.setenv("LABELING_OIDC_ISSUER", "https://identity.example/realms/test")
    for key, value in {"CONTROLLER_NAME": "Example Controller", "CONTROLLER_EMAIL": "privacy@example.org",
                       "HOSTING_SUMMARY": "Example Hosting, Germany", "EDGE_LOG_RETENTION": "7 days",
                       "BACKUP_RETENTION": "14 days"}.items():
        monkeypatch.setenv("LABELING_" + key, value)


def test_role_source_from_environment(monkeypatch):
    compliance_environment(monkeypatch)
    monkeypatch.delenv("LABELING_OIDC_ROLE_SOURCE", raising=False)
    assert Settings.from_environment().role_source == "client-role"
    monkeypatch.setenv("LABELING_OIDC_ROLE_SOURCE", "groups")
    assert Settings.from_environment().role_source == "groups"


# ---- Principal, annotator policy and curator detection ---------------------

@pytest.mark.asyncio
async def test_principal_email_only_when_verified():
    auth, token = group_identity()
    principal = await auth.authenticate(token(email="ana@example.org", email_verified=True))
    assert (principal.email, principal.email_verified, principal.curator) == ("ana@example.org", True, False)
    assert principal.username == "synthetic-test-human"
    for verified in (False, "true", 1, None, ...):
        principal = await auth.authenticate(token(email="ana@example.org", email_verified=verified))
        assert principal.email is None and principal.email_verified is False
    assert (await auth.authenticate(token(email=["x@example.org"], email_verified=True))).email is None


@pytest.mark.parametrize("groups,curator", [
    (["annotator"], False), (["annotator", "curator"], True), (["curator"], False),
    (["annotator", "Curator"], False), (["annotator", "/curator"], False),
])
@pytest.mark.asyncio
async def test_curator_from_groups_claim(groups, curator):
    # Group policy: the annotator group is still required; curator is an extra flag.
    auth, token = group_identity()
    if "annotator" not in groups:
        with pytest.raises(HTTPException) as exc:
            await auth.authenticate(token(groups=groups))
        assert exc.value.status_code == 403
        return
    assert (await auth.authenticate(token(groups=groups))).curator is curator


@pytest.mark.asyncio
async def test_curator_from_client_role(identity):
    auth, token = identity
    audience = auth.settings.audience
    assert (await auth.authenticate(token(resource_access={audience: {"roles": ["annotator", "curator"]}}))).curator
    assert not (await auth.authenticate(token())).curator
    # The client-role deployment never reads groups, also not for curators.
    assert not (await auth.authenticate(token(groups=["curator"]))).curator


@pytest.mark.asyncio
async def test_open_policy_accepts_any_realm_human_without_groups():
    auth, token = group_identity(annotator_policy="open")
    principal = await auth.authenticate(token(groups=...))
    assert principal.subject == "test-human" and principal.curator is False
    assert (await auth.authenticate(token(groups=[]))).curator is False
    assert (await auth.authenticate(token(groups=["curator"]))).curator is True
    assert (await auth.authenticate(token(groups="curator"))).curator is False


@pytest.mark.parametrize("changes", [
    {"preferred_username": "service-account-client"}, {"typ": "ID"}, {"azp": "other-client"},
    {"aud": "other"}, {"iss": "https://other.example/realms/test"}, {"exp": int(time.time()) - 60},
    {"sub": ""}, {"sub": "x" * 257},
])
@pytest.mark.asyncio
async def test_open_policy_still_rejects_non_human_or_foreign_tokens(changes):
    auth, token = group_identity(annotator_policy="open")
    with pytest.raises(HTTPException) as exc:
        await auth.authenticate(token(**changes))
    assert exc.value.status_code == 401


@pytest.mark.parametrize("value", ["", "Open", "closed", "groups"])
def test_annotator_policy_must_be_known(value):
    with pytest.raises(ValueError):
        make_settings(annotator_policy=value)


def test_policy_and_compliance_from_environment(monkeypatch):
    compliance_environment(monkeypatch)
    settings = Settings.from_environment()
    assert settings.annotator_policy == "group" and settings.curator_group == "curator"
    assert settings.controller_address == "" and settings.daily_cap == 3000 and settings.target_votes == 3
    monkeypatch.setenv("LABELING_ANNOTATOR_POLICY", "open")
    monkeypatch.setenv("LABELING_DAILY_CAP", "10")
    monkeypatch.setenv("LABELING_READ_ONLY", "true")
    settings = Settings.from_environment()
    assert (settings.annotator_policy, settings.daily_cap, settings.read_only) == ("open", 10, True)
    for key, value in (("LABELING_DAILY_CAP", "-1"), ("LABELING_DAILY_CAP", "0"), ("LABELING_READ_ONLY", "yes")):
        monkeypatch.setenv(key, value)
        with pytest.raises(ValueError):
            Settings.from_environment()
        monkeypatch.delenv(key)


def test_document_versions_from_environment(monkeypatch):
    compliance_environment(monkeypatch)
    assert Settings.from_environment().required_documents == {"privacy": "1.4", "terms": "1.1", "participation": "1.0"}
    monkeypatch.setenv("LABELING_PARTICIPATION_VERSION", "2.0")
    assert Settings.from_environment().participation_version == "2.0"
    for value in ("2 0", "x" * 33):
        monkeypatch.setenv("LABELING_PARTICIPATION_VERSION", value)
        with pytest.raises(ValueError):
            Settings.from_environment()


@pytest.mark.parametrize("key", ["controller_name", "controller_email", "hosting_summary",
                                 "edge_log_retention", "backup_retention"])
def test_compliance_values_are_required(key):
    for value in ("", "   "):
        with pytest.raises(ValueError):
            make_settings(**{key: value})


def test_controller_address_is_optional_and_email_validated():
    assert make_settings(controller_address="").controller_address == ""
    assert make_settings(controller_address="Ulica 1, 10000 Zagreb").controller_address
    for email in ("not-an-email", "a@b", "<a@b.hr>", "a b@c.hr"):
        with pytest.raises(ValueError):
            make_settings(controller_email=email)
    for version in ("", "1 0", "x" * 33, "1.0/2"):
        with pytest.raises(ValueError):
            make_settings(privacy_version=version)


@pytest.mark.asyncio
async def test_failed_authentication_logs_no_claims(caplog):
    import logging
    auth, token = group_identity()
    caplog.set_level(logging.DEBUG)
    for changes in ({"groups": []}, {"aud": "other"}, {"typ": "ID"}):
        with pytest.raises(HTTPException) as exc:
            await auth.authenticate(token(email="secret.person@example.org", email_verified=True, **changes))
        assert "secret.person" not in str(exc.value.detail)
    assert "secret.person" not in caplog.text and "test-human" not in caplog.text

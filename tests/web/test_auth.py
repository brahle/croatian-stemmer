"""Signed-token tests exercise the production validator without an auth bypass."""
import time

import pytest
jwt = pytest.importorskip("jwt")
pytest.importorskip("fastapi")
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from croatian_stemmer.labeling.web.auth import Authenticator
from croatian_stemmer.labeling.web.config import Settings

@pytest.fixture
def identity():
    settings = Settings("postgresql+asyncpg://test@localhost/labeling_test", "https://identity.example/realms/test")
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
    assert await auth.authenticate(token()) == "test-human"

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
        Settings("postgresql+asyncpg://test@localhost/labeling_test",issuer)

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
    assert await auth.authenticate(rotated)=="test-human"
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
    assert await auth.authenticate(token()) == "test-human"
    assert calls == 2
    assert await auth.authenticate(token()) == "test-human"
    assert calls == 2


def group_identity(role_source="groups"):
    settings = Settings("postgresql+asyncpg://test@localhost/labeling_test",
                        "https://identity.example/realms/test", role_source=role_source)
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
    assert await auth.authenticate(token()) == "test-human"
    assert await auth.authenticate(token(groups=["reader", "annotator"])) == "test-human"


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
        Settings("postgresql+asyncpg://test@localhost/labeling_test",
                 "https://identity.example/realms/test", role_source=value)


def test_role_source_from_environment(monkeypatch):
    monkeypatch.setenv("LABELING_DATABASE_URL", "postgresql+asyncpg://test@localhost/labeling_test")
    monkeypatch.setenv("LABELING_OIDC_ISSUER", "https://identity.example/realms/test")
    monkeypatch.delenv("LABELING_OIDC_ROLE_SOURCE", raising=False)
    assert Settings.from_environment().role_source == "client-role"
    monkeypatch.setenv("LABELING_OIDC_ROLE_SOURCE", "groups")
    assert Settings.from_environment().role_source == "groups"

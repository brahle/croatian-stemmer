"""Keycloak access-token validation; subjects come only from verified tokens."""

import asyncio
import time

import httpx
import jwt
from fastapi import HTTPException

from .config import Settings


class Authenticator:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.keys = {}
        self.loaded_at = 0.0
        self.retry_after = 0.0
        self.lock = asyncio.Lock()

    async def refresh(self):
        async with self.lock:
            now = time.monotonic()
            if now < self.retry_after:
                raise HTTPException(503, detail={"code": "identity_unavailable"})
            if self.keys and now - self.loaded_at < 5:
                return
            try:
                async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
                    async with client.stream("GET", self.settings.issuer + "/protocol/openid-connect/certs") as response:
                        response.raise_for_status()
                        raw = bytearray()
                        async for chunk in response.aiter_bytes():
                            raw.extend(chunk)
                            if len(raw) > 262144:
                                raise ValueError("JWKS exceeds bound")
                import json
                data = json.loads(raw)
                keys = {}
                if not isinstance(data, dict) or not isinstance(data.get("keys"), list):
                    raise ValueError("invalid JWKS")
                for key in data["keys"]:
                    if not isinstance(key, dict):
                        raise ValueError("invalid signing key")
                    if key.get("kty") != "RSA" or key.get("use", "sig") != "sig" or key.get("alg", "RS256") != "RS256":
                        continue
                    kid = key["kid"]
                    if not isinstance(kid, str) or kid in keys:
                        raise ValueError("ambiguous signing key")
                    keys[kid] = jwt.PyJWK.from_dict(key, algorithm="RS256").key
                if not keys:
                    raise ValueError("no signing keys")
            except (httpx.HTTPError, ValueError, KeyError, TypeError, jwt.PyJWTError) as exc:
                # Start the cooldown after the failed request finishes, so queued
                # callers do not each spend another timeout fetching the same keys.
                self.retry_after = time.monotonic() + 10
                raise HTTPException(503, detail={"code": "identity_unavailable"}) from exc
            self.keys, self.loaded_at = keys, time.monotonic()
            self.retry_after = 0.0

    async def authenticate(self, authorization: str | None) -> str:
        def refused():
            return HTTPException(401, detail={"code": "invalid_token"}, headers={"WWW-Authenticate": "Bearer"})
        if not authorization or not authorization.startswith("Bearer ") or len(authorization) > 16384:
            raise refused()
        token = authorization[7:]
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as exc:
            raise refused() from exc
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
            raise refused()
        kid = header["kid"]
        if time.monotonic() - self.loaded_at >= 300 or kid not in self.keys:
            await self.refresh()
        if kid not in self.keys:
            raise refused()
        try:
            claims = jwt.decode(token, self.keys[kid], algorithms=["RS256"],
                                audience=self.settings.audience, issuer=self.settings.issuer,
                                leeway=5, options={"require": ["exp", "iat", "sub", "iss", "aud"]})
        except jwt.PyJWTError as exc:
            raise refused() from exc
        subject = claims.get("sub")
        if (not isinstance(subject, str) or not subject or len(subject) > 256
                or claims.get("typ") != "Bearer" or claims.get("azp") != self.settings.client_id
                or str(claims.get("preferred_username", "")).startswith("service-account-")):
            raise refused()
        if self.settings.role_source == "groups":
            # Exact group name only; the realm's groups mapper emits names, not paths.
            roles = claims.get("groups")
        else:
            access = claims.get("resource_access") or {}
            client_access = access.get(self.settings.audience) if isinstance(access, dict) else None
            roles = client_access.get("roles") if isinstance(client_access, dict) else None
        if not isinstance(roles, list) or self.settings.role not in roles:
            raise HTTPException(403, detail={"code": "annotator_role_required"})
        return subject

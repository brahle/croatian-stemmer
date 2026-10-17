"""Keycloak access-token validation; principals come only from verified tokens."""

import asyncio
import time
from dataclasses import dataclass

import httpx
import jwt
from fastapi import HTTPException

from .config import Settings


@dataclass(frozen=True)
class Principal:
    """The verified caller. `email` is set only when the token says it is verified."""
    subject: str
    email: str | None
    email_verified: bool
    curator: bool
    username: str | None = None


def _names(value):
    """A list of exact string names, or None when the claim has another shape."""
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        return None
    return value


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

    async def authenticate(self, authorization: str | None) -> Principal:
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
            # Exact group names only; the realm's groups mapper emits names, not paths.
            roles = _names(claims.get("groups"))
        else:
            access = claims.get("resource_access") or {}
            client_access = access.get(self.settings.audience) if isinstance(access, dict) else None
            roles = _names(client_access.get("roles")) if isinstance(client_access, dict) else None
        if self.settings.annotator_policy == "group" and (roles is None or self.settings.role not in roles):
            raise HTTPException(403, detail={"code": "annotator_role_required"})
        curator_name = self.settings.curator_group if self.settings.role_source == "groups" else self.settings.curator_role
        verified = claims.get("email_verified") is True
        email = claims.get("email")
        email = email if verified and isinstance(email, str) and 0 < len(email) <= 320 else None
        username = claims.get("preferred_username")
        username = username if isinstance(username, str) and 0 < len(username) <= 256 else None
        return Principal(subject=subject, email=email, email_verified=verified,
                         curator=roles is not None and curator_name in roles, username=username)

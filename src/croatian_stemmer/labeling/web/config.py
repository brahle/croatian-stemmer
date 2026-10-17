"""Required runtime configuration; public browser settings contain no secrets."""

import os
from dataclasses import dataclass
from urllib.parse import urlsplit

# Where the annotator authorization is read from. `client-role` is
# resource_access.<audience>.roles (a dedicated API client with a client role);
# `groups` is a flat `groups` claim of group names (e.g. a Keycloak group mapper
# with full path off).
ROLE_SOURCES = ("client-role", "groups")


@dataclass(frozen=True)
class Settings:
    database_url: str
    issuer: str
    audience: str = "croatian-stemmer-labeling-api"
    client_id: str = "croatian-stemmer-labeling-web"
    role: str = "annotator"
    role_source: str = "client-role"
    allow_local_http: bool = False

    def __post_init__(self):
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("LABELING_DATABASE_URL must use PostgreSQL/asyncpg")
        url = urlsplit(self.issuer)
        local = self.allow_local_http and url.hostname in {"localhost", "127.0.0.1"}
        if (url.scheme != "https" and not (local and url.scheme == "http")) or not url.hostname:
            raise ValueError("OIDC issuer must use HTTPS (explicit local HTTP is test-only)")
        if url.query or url.fragment or url.username or url.password:
            raise ValueError("invalid OIDC issuer")
        if "/realms/" not in url.path or not url.path.rsplit("/realms/", 1)[1] or self.issuer.endswith("/"):
            raise ValueError("OIDC issuer must identify a Keycloak realm")
        if not all(v and len(v) <= 256 for v in (self.audience, self.client_id, self.role)):
            raise ValueError("OIDC audience, client and role must be configured")
        if self.role_source not in ROLE_SOURCES:
            raise ValueError("LABELING_OIDC_ROLE_SOURCE must be client-role or groups")

    @classmethod
    def from_environment(cls):
        return cls(database_url=os.environ["LABELING_DATABASE_URL"],
                   issuer=os.environ["LABELING_OIDC_ISSUER"],
                   audience=os.getenv("LABELING_OIDC_AUDIENCE", "croatian-stemmer-labeling-api"),
                   client_id=os.getenv("LABELING_OIDC_CLIENT_ID", "croatian-stemmer-labeling-web"),
                   role=os.getenv("LABELING_OIDC_ROLE", "annotator"),
                   role_source=os.getenv("LABELING_OIDC_ROLE_SOURCE", "client-role"),
                   allow_local_http=os.getenv("LABELING_ALLOW_LOCAL_HTTP") == "true")

    @property
    def identity_origin(self):
        url = urlsplit(self.issuer)
        return f"{url.scheme}://{url.netloc}"

    @property
    def browser(self):
        base, realm = self.issuer.rsplit("/realms/", 1)
        return {"url": base, "realm": realm, "clientId": self.client_id}

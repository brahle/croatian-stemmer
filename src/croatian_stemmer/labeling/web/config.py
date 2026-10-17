"""Required runtime configuration; public browser settings contain no secrets."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

# Where role-like authorization is read from. `client-role` is
# resource_access.<audience>.roles (a dedicated API client with a client role);
# `groups` is a flat `groups` claim of group names (e.g. a Keycloak group mapper
# with full path off).
ROLE_SOURCES = ("client-role", "groups")
# `open`: any human account of the realm may label (a valid browser-client
# access token is enough). `group`: the annotator role/group is required.
ANNOTATOR_POLICIES = ("open", "group")
VERSION = re.compile(r"^[0-9A-Za-z._-]{1,32}$")
EMAIL = re.compile(r"^[^@\s<>\"']+@[^@\s<>\"']+\.[^@\s<>\"']+$")
IDP_HINT = re.compile(r"^[A-Za-z0-9._-]{0,64}$")
# The legal documents shipped with this version declare these versions
# (<meta name="document-version">); a deployment may pin them explicitly.
DEFAULT_PRIVACY_VERSION = "1.2"
DEFAULT_TERMS_VERSION = "1.1"
DEFAULT_PARTICIPATION_VERSION = "1.0"
# The minimum age people confirm at the gate; stored on every consent row.
MINIMUM_AGE = 18


def package_version() -> str:
    """The release version: pyproject.toml in a checkout or the container, else package metadata."""
    pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
    try:
        match = re.search(r'(?m)^version = "([^"]+)"$', pyproject.read_text(encoding="utf-8"))
    except OSError:
        match = None
    if match:
        return match.group(1)
    from importlib.metadata import PackageNotFoundError, version
    try:
        return version("croatian-stemmer")
    except PackageNotFoundError:
        raise ValueError("cannot determine the application version; run from a checkout or the container image") from None


def _bool(name):
    value = os.getenv(name, "false")
    if value not in ("true", "false"):
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def _int(name, default):
    value = os.getenv(name)
    if value is None or value == "":
        return default
    if not value.isdigit():
        raise ValueError(f"{name} must be a positive integer")
    return int(value)


@dataclass(frozen=True)
class Settings:
    database_url: str
    issuer: str
    audience: str = "croatian-stemmer-labeling-api"
    client_id: str = "croatian-stemmer-labeling-web"
    role: str = "annotator"
    role_source: str = "client-role"
    allow_local_http: bool = False
    annotator_policy: str = "group"
    curator_group: str = "curator"
    curator_role: str = "curator"
    idp_hint: str = ""
    privacy_version: str = DEFAULT_PRIVACY_VERSION
    terms_version: str = DEFAULT_TERMS_VERSION
    participation_version: str = DEFAULT_PARTICIPATION_VERSION
    controller_name: str = ""
    controller_address: str = ""
    controller_email: str = ""
    hosting_summary: str = ""
    edge_log_retention: str = ""
    backup_retention: str = ""
    read_only: bool = False
    daily_cap: int = 3000
    target_votes: int = 3
    ui_version: str = field(default_factory=package_version)

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
        if not all(v and len(v) <= 256 for v in (self.audience, self.client_id, self.role,
                                                  self.curator_group, self.curator_role)):
            raise ValueError("OIDC audience, client, annotator and curator roles must be configured")
        if self.role_source not in ROLE_SOURCES:
            raise ValueError("LABELING_OIDC_ROLE_SOURCE must be client-role or groups")
        if self.annotator_policy not in ANNOTATOR_POLICIES:
            raise ValueError("LABELING_ANNOTATOR_POLICY must be open or group")
        if not IDP_HINT.match(self.idp_hint):
            raise ValueError("LABELING_OIDC_IDP_HINT must be an identity provider alias")
        for name in ("privacy_version", "terms_version", "participation_version", "ui_version"):
            if not VERSION.match(getattr(self, name)):
                raise ValueError(f"{name} must match {VERSION.pattern}")
        # The privacy notice must name the controller and a contact; the postal
        # address is optional and its section is left out when unset.
        for name, limit in (("controller_name", 200), ("controller_email", 320),
                            ("hosting_summary", 500), ("edge_log_retention", 200),
                            ("backup_retention", 200)):
            value = getattr(self, name)
            if not value.strip() or len(value) > limit:
                raise ValueError(f"LABELING_{name.upper()} is required (at most {limit} characters)")
        if len(self.controller_address) > 500:
            raise ValueError("LABELING_CONTROLLER_ADDRESS is at most 500 characters")
        if not EMAIL.match(self.controller_email):
            raise ValueError("LABELING_CONTROLLER_EMAIL must be an email address")
        if type(self.daily_cap) is not int or self.daily_cap < 1:
            raise ValueError("LABELING_DAILY_CAP must be a positive integer")
        if type(self.target_votes) is not int or self.target_votes < 1:
            raise ValueError("LABELING_TARGET_VOTES must be a positive integer")

    @classmethod
    def from_environment(cls):
        get = os.getenv
        return cls(database_url=os.environ["LABELING_DATABASE_URL"],
                   issuer=os.environ["LABELING_OIDC_ISSUER"],
                   audience=get("LABELING_OIDC_AUDIENCE", "croatian-stemmer-labeling-api"),
                   client_id=get("LABELING_OIDC_CLIENT_ID", "croatian-stemmer-labeling-web"),
                   role=get("LABELING_OIDC_ROLE", "annotator"),
                   role_source=get("LABELING_OIDC_ROLE_SOURCE", "client-role"),
                   allow_local_http=get("LABELING_ALLOW_LOCAL_HTTP") == "true",
                   annotator_policy=get("LABELING_ANNOTATOR_POLICY", "group"),
                   curator_group=get("LABELING_CURATOR_GROUP", "curator"),
                   curator_role=get("LABELING_CURATOR_ROLE", "curator"),
                   idp_hint=get("LABELING_OIDC_IDP_HINT", ""),
                   privacy_version=get("LABELING_PRIVACY_VERSION", DEFAULT_PRIVACY_VERSION),
                   terms_version=get("LABELING_TERMS_VERSION", DEFAULT_TERMS_VERSION),
                   participation_version=get("LABELING_PARTICIPATION_VERSION", DEFAULT_PARTICIPATION_VERSION),
                   controller_name=get("LABELING_CONTROLLER_NAME", ""),
                   controller_address=get("LABELING_CONTROLLER_ADDRESS", ""),
                   controller_email=get("LABELING_CONTROLLER_EMAIL", ""),
                   hosting_summary=get("LABELING_HOSTING_SUMMARY", ""),
                   edge_log_retention=get("LABELING_EDGE_LOG_RETENTION", ""),
                   backup_retention=get("LABELING_BACKUP_RETENTION", ""),
                   read_only=_bool("LABELING_READ_ONLY"),
                   daily_cap=_int("LABELING_DAILY_CAP", 3000),
                   target_votes=_int("LABELING_TARGET_VOTES", 3))

    @property
    def identity_origin(self):
        url = urlsplit(self.issuer)
        return f"{url.scheme}://{url.netloc}"

    @property
    def required_documents(self):
        """The document versions everyone must have accepted before contributing."""
        return {"privacy": self.privacy_version, "terms": self.terms_version,
                "participation": self.participation_version}

    @property
    def browser(self):
        """Public, static part of GET /api/config (no secrets)."""
        base, realm = self.issuer.rsplit("/realms/", 1)
        return {"url": base, "realm": realm, "clientId": self.client_id, "idpHint": self.idp_hint,
                "uiVersion": self.ui_version,
                "legal": self.required_documents, "minimumAge": MINIMUM_AGE,
                "controller": {"name": self.controller_name}, "locales": ["hr", "en"]}

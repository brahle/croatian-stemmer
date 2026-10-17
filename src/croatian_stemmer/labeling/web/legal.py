"""Legal documents: loading, version guard and placeholder substitution.

Each document declares <meta name="document-version" content="...">. The privacy
notice, the terms and the participation statement must declare the versions the
server requires consent to (LABELING_PRIVACY_VERSION, LABELING_TERMS_VERSION,
LABELING_PARTICIPATION_VERSION); otherwise the app refuses to start, so people are
never asked to accept a text other than the one served.
"""

import html
import re
from pathlib import Path
from urllib.parse import urlsplit

DOCUMENTS = ("privacy", "terms", "participation", "storage")
LANGUAGES = ("hr", "en")
PLACEHOLDERS = ("controller_name", "controller_address", "controller_email", "hosting_summary",
                "edge_log_retention", "backup_retention", "app_host", "identity_host")
OPTIONAL = ("controller_address",)
_VERSION = re.compile(r'<meta name="document-version" content="([^"]+)">')
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
_HOST = re.compile(r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?$")


class LegalDocuments:
    def __init__(self, settings, directory: Path):
        self.settings = settings
        self.texts = {}
        versions = {}
        for doc in DOCUMENTS:
            for lang in LANGUAGES:
                path = directory / f"{doc}.{lang}.html"
                text = path.read_text(encoding="utf-8")
                found = _VERSION.findall(text)
                if len(found) != 1:
                    raise ValueError(f"{path.name} must declare exactly one document-version")
                versions[doc, lang] = found[0]
                unknown = set(_PLACEHOLDER.findall(text)) - set(PLACEHOLDERS)
                if unknown:
                    raise ValueError(f"{path.name} uses unknown placeholders {sorted(unknown)}")
                if text.count("{{") != len(_PLACEHOLDER.findall(text)):
                    raise ValueError(f"{path.name} contains a malformed placeholder")
                self.texts[f"{doc}.{lang}"] = text
        required = settings.required_documents
        for doc in DOCUMENTS:
            hr, en = versions[doc, "hr"], versions[doc, "en"]
            if hr != en:
                raise ValueError(f"{doc}: the Croatian ({hr}) and English ({en}) versions differ")
            if doc in required and hr != required[doc]:
                raise ValueError(f"{doc} document version {hr} does not match the configured version "
                                 f"{required[doc]}; update the document or LABELING_{doc.upper()}_VERSION")
        self.versions = {doc: versions[doc, "hr"] for doc in DOCUMENTS}

    def render(self, name: str, app_host: str) -> str | None:
        text = self.texts.get(name)
        if text is None:
            return None
        s = self.settings
        values = {"controller_name": s.controller_name, "controller_address": s.controller_address,
                  "controller_email": s.controller_email, "hosting_summary": s.hosting_summary,
                  "edge_log_retention": s.edge_log_retention, "backup_retention": s.backup_retention,
                  "app_host": app_host if _HOST.match(app_host or "") else "",
                  "identity_host": urlsplit(s.issuer).hostname or ""}
        for key in OPTIONAL:
            # <!--if:key-->...<!--endif:key--> disappears when the value is unset.
            block = re.compile(r"<!--if:%s-->(.*?)<!--endif:%s-->" % (key, key), re.S)
            text = block.sub(lambda m: m.group(1) if values[key].strip() else "", text)
        return _PLACEHOLDER.sub(lambda m: html.escape(values[m.group(1)].strip(), quote=True), text)

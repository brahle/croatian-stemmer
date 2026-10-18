"""Legal documents: both languages, configured controller values, the version guard."""
import re
from pathlib import Path

import pytest
pytest.importorskip("fastapi")
from labeling_support import make_settings

DOCS = [f"{doc}.{lang}" for doc in ("privacy", "terms", "participation", "storage", "trust") for lang in ("hr", "en")]
VERSIONS = {"privacy": "1.3", "terms": "1.1", "participation": "1.0", "storage": "1.1", "trust": "1.1"}
ROOT = Path(__file__).resolve().parents[2]
FORMULAS = ROOT / "docs" / "trust.md"


def app_client(**changes):
    import httpx
    from croatian_stemmer.labeling.web.api import create_app
    app = create_app(make_settings(**changes))
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://labels.example.org")


@pytest.mark.parametrize("name", DOCS)
@pytest.mark.asyncio
async def test_documents_are_served_with_controller_values(name):
    async with app_client(controller_name='Ana <Example> & Co', controller_address="Ulica 1, 10000 Zagreb") as client:
        r = await client.get("/legal/" + name)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store" and "default-src 'none'" in r.headers["content-security-policy"]
    body = r.text
    assert "{{" not in body and "}}" not in body
    if not name.startswith("trust"):
        assert "Ana &lt;Example&gt; &amp; Co" in body
    assert "<Example>" not in body and "privacy@example.org" in body
    expected = VERSIONS[name.split(".")[0]]
    assert '<meta name="document-version" content="%s">' % expected in body
    assert 'lang="%s"' % name.rsplit(".", 1)[1] in body
    assert "<script" not in body and "style=" not in body
    if name.startswith("privacy"):
        assert "Ulica 1, 10000 Zagreb" in body and "Example Hosting Ltd, Germany" in body
        assert "7 days" in body and "14 days" in body and "identity.example" in body
        assert "AZOP" in body
    if name.startswith("storage"):
        # The app host is printed in the storage notice (the origin whose storage is described).
        assert re.search(r"\blabels\.example\.org\b", body) and "kc-callback-" in body


@pytest.mark.parametrize("name", [n for n in DOCS if n.split(".")[0] in ("privacy", "terms", "participation")])
@pytest.mark.asyncio
async def test_documents_state_age_18_and_the_new_identifier_on_erasure(name):
    async with app_client() as client:
        body = (await client.get("/legal/" + name)).text
    assert re.search(r"\b18\b", body) and not re.search(r"\b16\b", body)
    if not name.startswith("terms"):
        # Erasure keeps the answers under a new random identifier (privacy 1.2+, participation 1.0).
        assert ("novom nasumičnom oznakom" if name.endswith(".hr") else "new random identifier") in body
    if name.startswith("privacy"):
        assert ("30 dana nakon Vaše prve prijave" if name.endswith(".hr") else "30 days after your first sign-in") in body


@pytest.mark.parametrize("lang", ["hr", "en"])
@pytest.mark.asyncio
async def test_address_section_is_omitted_when_unset(lang):
    async with app_client() as client:
        body = (await client.get(f"/legal/privacy.{lang}")).text
    assert "Adresa:" not in body and "Address:" not in body and "<!--if:" not in body


@pytest.mark.asyncio
async def test_unknown_documents_are_404():
    async with app_client() as client:
        for name in ("privacy", "privacy.de", "../config.py", "guidelines.hr", "privacy.hr.html"):
            assert (await client.get("/legal/" + name)).status_code == 404
        # Templates are not reachable raw through /static.
        assert (await client.get("/static/legal/privacy.hr.html")).status_code == 404
        assert (await client.get("/static/guidelines.hr.html")).status_code == 200


@pytest.mark.parametrize("changes", [{"privacy_version": "1.1"}, {"terms_version": "1.0"},
                                     {"participation_version": "2.0"}])
def test_version_guard_refuses_mismatched_configuration(changes):
    from croatian_stemmer.labeling.web.api import create_app
    with pytest.raises(ValueError, match="does not match"):
        create_app(make_settings(**changes))


def test_guard_refuses_languages_with_different_versions(tmp_path, monkeypatch):
    from croatian_stemmer.labeling.web import api as api_module
    for path in api_module.DOCUMENTS.iterdir():
        text = path.read_text(encoding="utf-8")
        if path.name == "storage.en.html":
            text = text.replace('name="document-version" content="1.1"', 'name="document-version" content="1.2"')
        (tmp_path / path.name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(api_module, "DOCUMENTS", tmp_path)
    with pytest.raises(ValueError, match="differ"):
        api_module.create_app(make_settings())


def test_guard_refuses_unknown_placeholders(tmp_path, monkeypatch):
    from croatian_stemmer.labeling.web import api as api_module
    for path in api_module.DOCUMENTS.iterdir():
        text = path.read_text(encoding="utf-8")
        if path.name == "terms.hr.html":
            text = text.replace("</main>", "{{controller_phone}}</main>")
        (tmp_path / path.name).write_text(text, encoding="utf-8")
    monkeypatch.setattr(api_module, "DOCUMENTS", tmp_path)
    with pytest.raises(ValueError, match="unknown placeholders"):
        api_module.create_app(make_settings())


@pytest.mark.asyncio
async def test_public_config_names_versions_and_controller():
    async with app_client(idp_hint="google", read_only=True) as client:
        config = (await client.get("/api/config")).json()
    assert config["legal"] == {"privacy": "1.3", "terms": "1.1", "participation": "1.0"}
    assert config["minimumAge"] == 18 and config["controller"] == {"name": "Example Controller"}
    assert config["idpHint"] == "google" and config["locales"] == ["hr", "en"]
    assert config["acceptingJudgments"] is False and config["uiVersion"]
    assert {"url", "realm", "clientId"} <= set(config)
    assert "controller_email" not in str(config) and "database" not in str(config).lower()


def test_ui_version_comes_from_the_release():
    import re
    from pathlib import Path
    pyproject = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
    assert make_settings().ui_version == re.search(r'(?m)^version = "([^"]+)"$', pyproject).group(1)


@pytest.mark.asyncio
async def test_no_api_docs_and_not_indexed():
    async with app_client() as client:
        for path in ("/docs", "/redoc", "/openapi.json"):
            assert (await client.get(path)).status_code == 404
        r = await client.get("/legal/privacy.en")
    assert r.headers["x-robots-tag"] == "noindex, nofollow"


@pytest.mark.parametrize("lang", ["hr", "en"])
@pytest.mark.asyncio
async def test_privacy_notice_describes_profiling_and_silent_review(lang):
    """Privacy 1.3 (4.13.7): the profiling section, the silent review pause of at most 14 days
    that the export shows, the 90-day timing retention, public releases on GitHub only."""
    async with app_client() as client:
        body = (await client.get(f"/legal/privacy.{lang}")).text
    words = {"hr": ("profiliranje", "14 dana", "90 dana", "GitHub", "/legal/trust.hr", "17. stavka 3."),
             "en": ("profiling", "14 days", "90 days", "GitHub", "/legal/trust.en", "17(3)")}[lang]
    for word in words:
        assert word in body, word


@pytest.mark.parametrize("lang", ["hr", "en"])
@pytest.mark.asyncio
async def test_trust_page_carries_the_formulas_of_docs_trust_md(lang):
    """The trust page's appendix holds the formulas of docs/trust.md, line for line."""
    text = FORMULAS.read_text(encoding="utf-8")
    block = [line for line in text.split("## Formulas", 1)[1].split("```", 2)[1].splitlines()
             if "=" in line or "≤" in line]
    assert len(block) == 8
    async with app_client() as client:
        body = (await client.get(f"/legal/trust.{lang}")).text
    import html
    page = html.unescape(body)
    for line in block:
        assert line in page, line
    assert 'id="appendix"' in body

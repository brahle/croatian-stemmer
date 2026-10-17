"""Legal documents: both languages, configured controller values, the version guard."""
import pytest
pytest.importorskip("fastapi")
from labeling_support import make_settings

DOCS = [f"{doc}.{lang}" for doc in ("privacy", "terms", "storage") for lang in ("hr", "en")]


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
    assert "Ana &lt;Example&gt; &amp; Co" in body and "<Example>" not in body
    assert "privacy@example.org" in body
    assert '<meta name="document-version" content="1.0">' in body
    assert 'lang="%s"' % name.rsplit(".", 1)[1] in body
    assert "<script" not in body and "style=" not in body
    if name.startswith("privacy"):
        assert "Ulica 1, 10000 Zagreb" in body and "Example Hosting Ltd, Germany" in body
        assert "7 days" in body and "14 days" in body and "identity.example" in body
        assert "AZOP" in body
    if name.startswith("storage"):
        assert "labels.example.org" in body and "kc-callback-" in body


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


@pytest.mark.parametrize("changes", [{"privacy_version": "1.1"}, {"terms_version": "2.0"}])
def test_version_guard_refuses_mismatched_configuration(changes):
    from croatian_stemmer.labeling.web.api import create_app
    with pytest.raises(ValueError, match="does not match"):
        create_app(make_settings(**changes))


def test_guard_refuses_languages_with_different_versions(tmp_path, monkeypatch):
    from croatian_stemmer.labeling.web import api as api_module
    for path in api_module.DOCUMENTS.iterdir():
        text = path.read_text(encoding="utf-8")
        if path.name == "storage.en.html":
            text = text.replace('content="1.0"', 'content="1.1"')
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
    assert config["legal"] == {"privacy": "1.0", "terms": "1.0"} and config["controller"] == {"name": "Example Controller"}
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

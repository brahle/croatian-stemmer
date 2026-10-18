"""A raw-text corpus (from-text) imports like any other: a CC BY-SA source publishes only
under CC BY-SA labels, and its items are served (0.4.0)."""
from pathlib import Path

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.text import from_text
from labeling_support import profiled

pytestmark = pytest.mark.asyncio
FIXTURE = Path(__file__).resolve().parents[1] / "labeling" / "fixtures" / "synthetic-wiki.xml"


async def test_a_wikipedia_corpus_imports_and_publishes_share_alike(fresh_api, tmp_path):
    api = await fresh_api()
    lexicon = tmp_path / "lexicon.conllu"
    forms = [("kuće", "kuća"), ("kuću", "kuća"), ("kući", "kuća"), ("kućama", "kuća"), ("gradu", "grad"),
             ("gradovima", "grad"), ("ljudi", "čovjek"), ("žive", "živjeti"), ("grade", "graditi"),
             ("gradili", "graditi")]
    lexicon.write_text("".join(f"{i}\t{f}\t{l}\tNOUN\n" if l not in ("živjeti", "graditi") else
                               f"{i}\t{f}\t{l}\tVERB\n" for i, (f, l) in enumerate(forms, 1)) + "\n",
                       encoding="utf-8")
    rows, receipt = from_text([str(FIXTURE)], lexicon_paths=[lexicon], lexicon_uri="urn:test:lexicon",
                              lexicon_license="CC BY-SA 4.0", pair_count=4, word_count=3)
    assert receipt["license"] == "CC BY-SA 4.0"
    r = await api.request("POST", "/api/import", "curator", True, json={"name": "Wikipedija", "candidates": rows})
    assert r.status_code == 200, r.text
    corpus = rows[0]["corpus_id"]
    r = await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True,
                          json={"labels_license": "CC BY 4.0"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "license_not_publishable"
    r = await api.request("POST", f"/api/corpora/{corpus}/publish", "curator", True,
                          json={"labels_license": "CC BY-SA 4.0"})
    assert r.status_code == 200
    await profiled(api, "alice")
    served = (await api.request("GET", f"/api/corpora/{corpus}/next", "alice", params={"kind": "lemma"})).json()
    assert served["item"]["candidate"]["corpus_id"] == corpus



async def test_the_lexicon_licence_is_stored_and_binds_publication(fresh_api):
    from labeling_support import candidates
    api = await fresh_api()
    base = candidates(license="CC0 1.0")
    rows = [{**row, "candidate_schema_version": 2, "lexicon_uri": "urn:test:lexicon",
             "lexicon_license": "CC BY-SA 4.0"} for row in base]
    for bad in ([{k: v for k, v in rows[0].items() if k != "lexicon_license"}],
                [{**base[0], "lexicon_uri": "urn:test:lexicon", "lexicon_license": "CC0 1.0"}]):
        r = await api.request("POST", "/api/import", "curator", True, json={"name": "x", "candidates": bad})
        assert r.status_code == 422
    r = await api.request("POST", "/api/import", "curator", True, json={"name": "Tekst", "candidates": rows})
    assert r.status_code == 200, r.text
    corpus = r.json()["corpus"]
    assert (corpus["lexicon_uri"], corpus["lexicon_license"]) == ("urn:test:lexicon", "CC BY-SA 4.0")
    other = [{**rows[0], "lexicon_license": "CC BY 4.0"}]
    r = await api.request("POST", "/api/import", "curator", True, json={"name": "x", "candidates": other})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "corpus_provenance_conflict"
    path = f"/api/corpora/{rows[0]['corpus_id']}/publish"
    for labels in ("CC0 1.0", "CC BY 4.0"):  # allowed by the CC0 text, not by the CC BY-SA lexicon
        r = await api.request("POST", path, "curator", True, json={"labels_license": labels})
        assert r.status_code == 409 and r.json()["detail"]["allowed"] == ["CC BY-SA 4.0"]
    assert (await api.request("POST", path, "curator", True, json={"labels_license": "CC BY-SA 4.0"})).status_code \
        == 200
    # A schema-1 corpus keeps its payloads as they were: no lexicon keys.
    plain = await api.imported()
    payload = (await api.sql("SELECT payload FROM label_item WHERE id = :i", i=plain[0]["item_id"])).scalar_one()
    assert "lexicon_uri" not in payload

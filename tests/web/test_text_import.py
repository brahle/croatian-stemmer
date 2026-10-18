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
    rows, receipt = from_text([str(FIXTURE)], lexicon_paths=[lexicon], pair_count=4, word_count=3)
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

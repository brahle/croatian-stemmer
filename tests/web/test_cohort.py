"""Nobody is profiled before being informed (4.13.1): only people who accepted privacy notice
1.3 (with the terms, the participation statement and age 18) are scored or counted."""
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, profiled, score_now

pytestmark = pytest.mark.asyncio


async def test_only_the_profiling_cohort_is_scored(fresh_api):
    api = await fresh_api()
    rows = await api.imported(candidates(pairs=3))
    pair = rows[0]
    # Ana answered under the 0.2.3 gate (privacy 1.2): her rows exist, she is not in the cohort.
    assert (await api.request("GET", "/api/me", "ana")).status_code == 200
    ana = await api.annotator_id("ana")
    for document, version in (("privacy", "1.2"), ("terms", "1.1"), ("participation", "1.0")):
        await api.sql("INSERT INTO label_consent (annotator_id, document, version, locale, age_confirmed, age_threshold, "
                      "ui_version) VALUES (:a, :d, :v, 'hr', true, 18, '0.2.3')", a=ana, d=document, v=version)
    await api.sql("INSERT INTO label_judgment (id, corpus_id, item_id, annotator_id, revision, answer, irregular, "
                  "item_revision, client_version, created_at) VALUES (:id, :c, :i, :a, 1, 'same', false, 1, '0.2.3', now())",
                  id=uuid4(), c=pair["corpus_id"], i=pair["item_id"], a=ana)
    await profiled(api, "bob")
    assert (await api.request("POST", answer_path(pair), "bob", json=answer())).status_code == 200
    [(run_id, _)] = await score_now(api)
    scored = {r[0] for r in (await api.sql("SELECT annotator_id::text FROM label_annotator_score WHERE run_id = :r",
                                           r=run_id)).all()}
    assert ana not in scored and await api.annotator_id("bob") in scored
    assert (await api.sql("SELECT n_annotators FROM label_item_posterior WHERE run_id = :r AND item_id = :i",
                          r=run_id, i=pair["item_id"])).scalar_one() == 1
    # The 0.2.3 gate no longer lets her answer; after the 1.3 gate her earlier answer counts.
    r = await api.request("POST", answer_path(rows[1]), "ana", json=answer())
    assert r.status_code == 403 and r.json()["detail"]["code"] == "consent_required"
    await api.consent("ana")
    [(run_id, _)] = await score_now(api)
    assert (await api.sql("SELECT count(*) FROM label_annotator_score WHERE run_id = :r AND annotator_id = :a",
                          r=run_id, a=ana)).scalar_one() == 1
    assert (await api.sql("SELECT n_annotators FROM label_item_posterior WHERE run_id = :r AND item_id = :i",
                          r=run_id, i=pair["item_id"])).scalar_one() == 2

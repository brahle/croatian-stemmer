"""Gold is invisible to annotators (4.3.6): one shape for every item, no gold vocabulary in
any annotator response (the suite-wide scanner in labeling_support), nothing per item in the
personal export."""
import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, gold_line, pair_rows, profiled, scoring_on, unlimited, unsampled

pytestmark = pytest.mark.asyncio


def shape(value):
    """The key structure at every depth."""
    if isinstance(value, dict):
        return {key: shape(v) for key, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape(v) for v in value[:1]]
    return type(value).__name__ if value is not None else "null"


async def test_gold_and_other_items_have_one_shape(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(40))
    free = await unsampled(api, rows)
    gold, plain = free[0], free[1]
    r = await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": [gold_line(gold)]})
    assert r.status_code == 200
    await scoring_on(api)
    await profiled(api, "alice")
    shapes = {}
    for row in (gold, plain):
        detail = await api.request("GET", f'/api/corpora/{row["corpus_id"]}/items/{row["item_id"]}', "alice")
        assert detail.status_code == 200
        shapes[row["item_id"]] = shape(detail.json())
    assert shapes[gold["item_id"]] == shapes[plain["item_id"]]
    # Through /next: whatever comes (audit pick or not), the shape is the same.
    seen = set()
    for _ in range(30):
        served = (await api.request("GET", f'/api/corpora/{rows[0]["corpus_id"]}/next', "alice")).json()
        if served["item"] is None:
            break
        seen.add(str(shape(served)))
        await api.request("POST", answer_path(served["item"]["candidate"]), "alice", fetched=False, json=answer())
    assert len(seen) == 1
    export = (await api.request("GET", "/api/me/export.json", "alice")).json()
    for judgment in export["judgments"]:
        assert set(judgment) == {"id", "corpus_id", "item_id", "revision", "answer", "lemma", "irregular",
                                 "item_revision", "client_version", "source", "elapsed_ms", "created_at",
                                 "presentation", "checked_against_known_answer"}
        assert judgment["checked_against_known_answer"] is False  # active gold is never marked

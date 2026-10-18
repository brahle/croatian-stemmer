"""The scheduler (4.9.1, 4.9.3): no repeats, capacity, spread, the least-resolved corpus,
the keyed qualification-then-audit sequence, and speed at 50k items."""
import gc
import time
from uuid import uuid4

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from labeling_support import answer, answer_path, candidates, gold_line, profiled, scoring_on, unlimited, unsampled

pytestmark = pytest.mark.asyncio
KEY = "0f" * 32  # a fixed audit key: the keyed rules become reproducible in tests


async def keyed_api(fresh_api):
    api = unlimited(await fresh_api())
    await api.sql("UPDATE label_setting SET value = to_jsonb(CAST(:k AS text)) WHERE key = 'audit_key'", k=KEY)
    return api


async def next_of(api, name, corpus, kind="pair"):
    r = await api.request("GET", f"/api/corpora/{corpus}/next", name, params={"kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


async def test_no_repeats_capacity_and_spread(fresh_api):
    api = await keyed_api(fresh_api)
    rows = await api.imported(candidates(pairs=40))
    corpus = rows[0]["corpus_id"]
    await scoring_on(api)
    for name in ("a", "b"):
        await profiled(api, name)
    seen = []
    for _ in range(10):
        item = (await next_of(api, "a", corpus))["item"]
        seen.append(item["candidate"]["item_id"])
        r = await api.request("POST", answer_path(item["candidate"]), "a", fetched=False, json=answer())
        assert r.status_code == 200
    assert len(set(seen)) == 10
    # Two identical annotators are spread over different items.
    first_a = (await next_of(api, "a", corpus))["item"]["candidate"]["item_id"]
    first_b = (await next_of(api, "b", corpus))["item"]["candidate"]["item_id"]
    assert first_a != first_b
    # Capacity: an item with five admitted low first answers is not offered to a sixth low annotator.
    full = next(r for r in rows if r["kind"] == "pair" and r["item_id"] not in seen + [first_a, first_b])
    for n in range(5):
        await profiled(api, f"f{n}")
        assert (await api.request("POST", answer_path(full), f"f{n}", json=answer())).status_code == 200
    await profiled(api, "sixth")
    offered = set()
    for _ in range(40):
        item = (await next_of(api, "sixth", corpus))["item"]
        if item is None:
            break
        offered.add(item["candidate"]["item_id"])
        await api.request("POST", answer_path(item["candidate"]), "sixth", fetched=False, json=answer(value="different"))
    assert full["item_id"] not in offered


async def test_any_corpus_picks_the_least_resolved(fresh_api):
    api = await keyed_api(fresh_api)
    first = await api.imported(candidates(pairs=3))
    second = await api.imported(candidates(pairs=3))
    await scoring_on(api)
    await profiled(api, "a")
    await api.sql("UPDATE label_item_state SET state = 'resolved', releasable = true WHERE corpus_id = :c AND item_id = :i",
                  c=first[0]["corpus_id"], i=first[0]["item_id"])
    r = await api.request("GET", "/api/next", "a", params={"kind": "pair"})
    assert r.status_code == 200 and r.json()["item"]["candidate"]["corpus_id"] == second[0]["corpus_id"]


async def test_qualification_then_keyed_audit(fresh_api):
    from croatian_stemmer.labeling.web.scheduler import keyed
    api = await keyed_api(fresh_api)
    rows = await api.imported(candidates(pairs=400))
    pairs = await unsampled(api, [r for r in rows if r["kind"] == "pair"])
    lines = [gold_line(r, pool="qualification") for r in pairs[:60]] + [gold_line(r) for r in pairs[60:200]]
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})).status_code == 200
    gold = {r["item_id"] for r in pairs[:200]}
    qualification = {r["item_id"] for r in pairs[:60]}
    alice = await profiled(api, "alice")
    corpus = rows[0]["corpus_id"]
    for n in range(12):
        served = await next_of(api, "alice", corpus)
        item = served["item"]
        assert item["candidate"]["item_id"] in qualification and item["presentation"] == "blind"
        assert item["candidate"]["proposed_lemma"] == "" and served["qualification"] == {"done": n, "of": 12}
        r = await api.request("POST", answer_path(item["candidate"]), "alice", fetched=False, json=answer())
        assert r.status_code == 200
    # After qualification every showing n is a known-answer check exactly when the keyed rule says so.
    for n in range(12, 72):
        served = await next_of(api, "alice", corpus)
        assert served["qualification"] is None
        expected = keyed(KEY, f"audit:{alice}:pair:{n}") % 100 < 10
        assert (served["item"]["candidate"]["item_id"] in gold - qualification) == expected, n
        await api.request("POST", answer_path(served["item"]["candidate"]), "alice", fetched=False, json=answer())


@pytest.mark.slow
async def test_next_is_fast_at_50k_items(fresh_api):
    api = await keyed_api(fresh_api)
    rows = await api.imported(candidates(pairs=2))
    corpus = rows[0]["corpus_id"]
    await api.sql("""
        INSERT INTO label_item (corpus_id, id, ordinal, kind, payload)
        SELECT :c, gen_random_uuid(), 100 + n, 'pair', CAST(:p AS jsonb) FROM generate_series(1, 50000) n""",
                  c=corpus, p=__import__("json").dumps(rows[0]))
    await api.sql("""INSERT INTO label_item_state (corpus_id, item_id, kind)
                     SELECT corpus_id, id, kind FROM label_item WHERE corpus_id = :c ON CONFLICT DO NOTHING""", c=corpus)
    await api.sql("""INSERT INTO label_item_audit (corpus_id, item_id, audit_sample, review_sample, audit_rank)
                     SELECT corpus_id, id, false, false, ordinal FROM label_item WHERE corpus_id = :c
                     ON CONFLICT DO NOTHING""", c=corpus)
    await scoring_on(api)
    alice = await profiled(api, "alice")
    await api.sql("""INSERT INTO label_assignment (annotator_id, corpus_id, item_id, first_shown_at, last_shown_at,
                       shown_count, current_revision, presentation)
                     SELECT :a, corpus_id, id, now(), now(), 1, 1, 'shown' FROM label_item
                     WHERE corpus_id = :c ORDER BY ordinal LIMIT 5000""", a=alice, c=corpus)
    await api.sql("ANALYZE")
    headers = api.headers("alice")  # signed once: the client's own token signing is not server time
    for _ in range(5):  # warm the connection pool and the caches
        await api.client.get(f"/api/corpora/{corpus}/next", headers=headers)
    # The test process carries the whole suite's heap; keep its collector out of the measurement.
    # A loaded developer machine adds stalls that are not the server's: a second sample of 100
    # is taken before failing (CI runs on an otherwise idle runner).
    gc.collect()
    gc.freeze()
    rounds = []
    try:
        for _ in range(2):
            times = []
            for _ in range(100):
                start = time.perf_counter()
                r = await api.client.get(f"/api/corpora/{corpus}/next", headers=headers)
                times.append(time.perf_counter() - start)
                assert r.status_code == 200 and r.json()["item"] is not None
            times.sort()
            rounds.append((times[95], times[50]))
            if times[95] < 0.05:
                break
    finally:
        gc.unfreeze()
    assert rounds[-1][0] < 0.05, rounds  # (p95, median) per round

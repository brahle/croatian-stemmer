"""Gold cannot be passed by copying the screen (4.3.3): a client that echoes the suggestion,
or the corpus when the suggestion is hidden, fails every item where the suggestion is wrong;
audit positions cannot be predicted without the key; blind showings are equally likely on
gold and other items."""
import random
from collections import Counter
from uuid import UUID

import pytest
pytest.importorskip("sqlalchemy")
pytest.importorskip("asyncpg")
from croatian_stemmer.labeling.web.scheduler import blind_by_rule, keyed
from labeling_support import (answer, answer_path, gold_line, later, make_anchor, pair_rows, profiled, score_now,
                              scoring_on, unlimited, unsampled)

def suggestion(row):
    return "same" if row["proposed_lemma"] == row["other_proposed_lemma"] else "different"


@pytest.mark.asyncio
async def test_a_copying_client_never_reaches_established_and_is_flagged(fresh_api):
    api = unlimited(await fresh_api())
    rows = await api.imported(pair_rows(700))
    by_id = {r["item_id"]: r for r in rows}
    free = await unsampled(api, rows)
    # hr500k-style gold agrees with the suggestion; the trusted expert's gold does not.
    lines = [gold_line(r, answer=suggestion(r), pool="qualification") for r in free[:60]]
    lines += [gold_line(r, answer=suggestion(r)) for r in free[60:160]]
    assert (await api.request("POST", "/api/admin/gold/import", "curator", True, json={"rows": lines})).status_code == 200
    for row in free[160:175]:
        opposite = "different" if suggestion(row) == "same" else "same"
        r = await api.request("PUT", f'/api/admin/gold/{row["corpus_id"]}/{row["item_id"]}', "curator", True,
                              json={"action": "set", "pool": "audit", "answer": opposite, "reason": "expert"})
        assert r.status_code == 200
    await make_anchor(api, "owner")
    params = (await api.request("GET", "/api/admin/scoring/params", "curator", True)).json()["params"]
    params["gold_rate"].update({"new": 40, "qualified": 40})  # more checks per answer: a shorter test
    assert (await api.request("PUT", "/api/admin/scoring/params", "curator", True,
                              json={"params": params})).status_code == 200
    await scoring_on(api)
    await profiled(api, "bot")
    corpus = rows[0]["corpus_id"]
    blind = 0
    for _ in range(220):
        served = (await api.request("GET", f"/api/corpora/{corpus}/next", "bot")).json()["item"]
        assert served is not None
        shown = served["candidate"]
        if served["presentation"] == "blind":
            blind += 1
            assert shown["proposed_lemma"] == "" and shown["other_proposed_lemma"] == ""
        # Echo the suggestion; when it is hidden, read it from a copy of the corpus.
        value = suggestion(by_id[shown["item_id"]])
        assert (await api.request("POST", answer_path(shown), "bot", fetched=False,
                                  json=answer(value=value, elapsed_ms=4000))).status_code == 200
    assert blind > 12  # the qualification items and the keyed share
    [(run_id, _)] = await score_now(api, as_of_day=later())
    score = (await api.sql("SELECT tier, wrong_sugg_seen, wrong_sugg_hits, flags FROM label_annotator_score "
                           "WHERE run_id = :r AND annotator_id = :a", r=run_id, a=await api.annotator_id("bot"))).one()
    assert score.wrong_sugg_seen >= 5 and score.wrong_sugg_hits == 0
    assert score.tier != "established" and score.flags["copy"]["on"] is True


def test_audit_positions_cannot_be_predicted_without_the_key():
    """A client that knows the formula but not the key guesses the n-th showing's check with
    its own key: over 5,000 showings its guesses are independent of the truth."""
    rng = random.Random(4)
    key, guess = "%064x" % rng.getrandbits(256), "%064x" % rng.getrandbits(256)
    annotator = "00000000-0000-4000-8000-00000000a11c"
    table = Counter()
    for n in range(5000):
        actual = keyed(key, f"audit:{annotator}:pair:{n}") % 100 < 10
        predicted = keyed(guess, f"audit:{annotator}:pair:{n}") % 100 < 10
        table[(actual, predicted)] += 1
    total = sum(table.values())
    chi = 0.0
    for a in (True, False):
        for p in (True, False):
            expected = (table[(a, True)] + table[(a, False)]) * (table[(True, p)] + table[(False, p)]) / total
            chi += (table[(a, p)] - expected) ** 2 / expected
    assert chi < 3.84  # no association at the 5 % level
    hits = table[(True, True)] / (table[(True, True)] + table[(False, True)])
    assert abs(hits - 0.10) < 0.05  # a guessed check is a check at about the base rate


def test_blind_rate_is_the_same_on_gold_and_other_items():
    rng = random.Random(5)
    key = "%064x" % rng.getrandbits(256)
    params = {"blind_rate": 20}
    fresh = lambda: str(UUID(int=rng.getrandbits(128)))
    people = [fresh() for _ in range(50)]
    gold = [(fresh(), fresh()) for _ in range(100)]
    other = [(fresh(), fresh()) for _ in range(100)]
    rates = []
    for items in (gold, other):
        shows = [blind_by_rule(key, params, a, c, i, "pair") for a in people for c, i in items]
        rates.append(sum(shows) / len(shows))
    standard_error = (0.2 * 0.8 / 5000) ** 0.5
    assert abs(rates[0] - rates[1]) < 4 * standard_error and abs(rates[0] - 0.2) < 4 * standard_error

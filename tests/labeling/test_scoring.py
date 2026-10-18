"""The pure scoring function (4.4-4.5): the worked example, the peer cap, tiers at their
boundaries, tier memory, determinism and the parameter guard. Synthetic data only."""
import math
import random

import pytest

from croatian_stemmer.labeling.scoring import (DEFAULT_PARAMS, OTHER, count_first_answers, fit, model_rule, posterior,
                                               release_rule, score, sha256, theta_lower_bound, validate_params, weight,
                                               wilson_lower_bound)
from scoring_world import World, synthetic, train, worked_example

UNIFORM = [("same", math.log(0.5)), ("different", math.log(0.5))]
# outputs_sha256 of synthetic(seed=1) at SCORING_VERSION 2.0 and the default parameters; it changes
# only with a version bump or a deliberate change of the defaults. 0.3.1 (new ceiling 0.75 -> 0.78):
# was d26574696eaa8f8a2c17306471c6ace88124a2d7d46debcf658a1ad4122f985d. One `new` lemma annotator
# sat at the old ceiling; lemma thetas and posteriors moved and three lemma items went from open to
# provisional; no pair or stem output changed.
GOLDEN = "29d768942a1a363c921d7b06eaeadb72e635626d46d01a789f073b0ee1727ad5"
NEW_CEILING = DEFAULT_PARAMS["theta_max"]["new"]


def params(**changes):
    return validate_params({**DEFAULT_PARAMS, **changes})


def by_name(world, out, kind="pair"):
    ids = {v: k for k, v in world.people.items()}
    return {ids[s["annotator_id"]]: s for s in out["scores"] if s["kind"] == kind}


def posterior_of(out, key):
    return next(p for p in out["posteriors"] if (p["corpus_id"], p["item_id"]) == key)


def state_of(out, key):
    return next(s for s in out["item_states"] if (s["corpus_id"], s["item_id"]) == key)


# ---- the worked example of 4.4.6 ------------------------------------------------

def test_worked_example_em_values():
    p = params(class_prior="uniform")
    # B (new, 0.667 -> 0.619) is below the new ceiling of 0.3.0 (0.75) and of 0.3.1 (0.78).
    people = {"A": (4, 2, 36, 4, 0.95, True), "B": (4, 2, 0, 0, NEW_CEILING, True), "C": (4, 2, 12, 3, 0.80, True)}
    work = [("x", "s", [("A", "same"), ("B", "different"), ("C", "same")], False)]
    first = fit("pair", work, people, {**p, "iterations": 1})
    assert first["theta"] == pytest.approx({"A": 0.866832, "B": 0.618829, "C": 0.762075}, abs=1e-6)
    assert first["soft"]["A"] == pytest.approx((0.307692, 0.192308), abs=1e-6)
    assert first["soft"]["B"] == pytest.approx((0.022388, 0.477612), abs=1e-6)
    assert first["soft"]["C"] == pytest.approx((0.384615, 0.115385), abs=1e-6)
    final = fit("pair", work, people, p)
    assert final["theta"] == pytest.approx({"A": 0.867360, "B": 0.618876, "C": 0.762816}, abs=1e-6)
    assert {a: weight(t, 2) for a, t in final["theta"].items()} == pytest.approx(
        {"A": 1.877817, "B": 0.484781, "C": 1.168179}, abs=1e-6)
    assert final["soft"]["A"] == pytest.approx((0.332248, 0.167752), abs=1e-6)
    assert final["soft"]["B"] == pytest.approx((0.022695, 0.477305), abs=1e-6)
    assert final["soft"]["C"] == pytest.approx((0.400538, 0.099462), abs=1e-6)


def test_worked_example_through_a_run():
    """Requirement (d) for the example item: classes, weights, votes, state (4.5.4)."""
    world, _, x = worked_example()
    out = score(world.inputs(), world.params)
    tiers = {name: s["tier"] for name, s in by_name(world, out).items()}
    assert (tiers["A"], tiers["B"], tiers["C"]) == ("established", "new", "qualified")
    row = posterior_of(out, x)
    assert [(c["answer"], c["votes"], c["established_votes"]) for c in row["classes"]] == [
        ("same", 2, 1), ("different", 1, 0)]
    assert [c["prob"] for c in row["classes"]] == pytest.approx([0.928323, 0.071677], abs=1e-6)
    assert [c["weight"] for c in row["classes"]] == pytest.approx([3.045996, 0.484781], abs=1e-6)
    assert row["state"] == "open" and row["confidence"] == pytest.approx(0.928323, abs=1e-6)
    assert state_of(out, x)["priority"] == pytest.approx(0.143354, abs=1e-6)


def test_worked_example_variants():
    p = params(class_prior="uniform")
    tiers = {"A": "established", "C": "qualified", "E": "established", "F": "established", "N": "anchor"}
    # B quarantined from the start: its vote is not counted; A and C alone meet the rule.
    people = {"A": (4, 2, 36, 4, 0.95, True), "C": (4, 2, 12, 3, 0.80, True)}
    final = fit("pair", [("x", "s", [("A", "same"), ("C", "same")], False)], people, p)
    w = {a: weight(t, 2) for a, t in final["theta"].items()}
    assert w == pytest.approx({"A": 1.887185, "C": 1.176857}, abs=1e-6)
    met, winner, probs = model_rule(UNIFORM, [("A", "same", w["A"]), ("C", "same", w["C"])], 2, tiers, p)
    assert met and winner == "same" and probs["same"] == pytest.approx(0.955385, abs=1e-6)
    two = [("E", "same", weight(0.85, 2)), ("F", "same", weight(0.85, 2))]
    met, _, probs = model_rule(UNIFORM, two, 2, tiers, p)
    assert met and probs["same"] == pytest.approx(0.9698, abs=1e-4)
    # One anchor at its prior mean: one vote, below 0.95. Never resolves alone.
    met, _, probs = model_rule(UNIFORM, [("N", "same", weight(0.9, 2))], 2, tiers, p)
    assert not met and probs["same"] == pytest.approx(0.90, abs=1e-9)
    # Three `new` accounts at their ceiling (0.78): 0.9781 but no established or anchor vote.
    new = [(name, "same", weight(NEW_CEILING, 2)) for name in "XYZ"]
    met, _, probs = model_rule(UNIFORM, new, 2, {}, p)
    assert not met and probs["same"] == pytest.approx(0.978054, abs=1e-6)


def test_two_votes_resolve_established_and_new():
    """Decision 5ee0e7ef q4 (two votes). An established annotator at the promotion floor (27 of
    30 discriminating, theta 31/36) and a new one at the new ceiling agreeing meet the rule:
    0.956487 (0.948980 at the 0.3.0 ceiling 0.75, which needed a third vote)."""
    p = params(class_prior="uniform")
    tiers = {"E": "established", "N": "new", "M": "new", "Q": "qualified", "Z": "new"}
    floor = weight(31 / 36, 2)
    met, _, probs = model_rule(UNIFORM, [("E", "same", floor), ("N", "same", weight(NEW_CEILING, 2))], 2, tiers, p)
    assert met and probs["same"] == pytest.approx(0.956487, abs=1e-6)
    old = params(class_prior="uniform", theta_max={**DEFAULT_PARAMS["theta_max"], "new": 0.75})
    met, _, probs = model_rule(UNIFORM, [("E", "same", floor), ("N", "same", weight(0.75, 2))], 2, tiers, old)
    assert not met and probs["same"] == pytest.approx(0.948980, abs=1e-6)
    # The weakest established theta two votes resolve with: 0.842742 (0.863636 before).
    lowest = 19 / (19 + NEW_CEILING / (1 - NEW_CEILING))
    assert lowest == pytest.approx(0.842742, abs=1e-6)
    assert model_rule(UNIFORM, [("E", "same", weight(lowest + 1e-6, 2)), ("N", "same", weight(NEW_CEILING, 2))],
                      2, tiers, p)[0]
    assert not model_rule(UNIFORM, [("E", "same", weight(lowest - 1e-6, 2)), ("N", "same", weight(NEW_CEILING, 2))],
                          2, tiers, p)[0]
    # A new account with no evidence yet (prior mean 4/6) is not enough next to the floor.
    assert not model_rule(UNIFORM, [("E", "same", floor), ("N", "same", weight(4 / 6, 2))], 2, tiers, p)[0]


def test_two_vote_safety():
    """What the change must not open: two new voters, a single vote, a worthless second vote."""
    p = params(class_prior="uniform")
    tiers = {"E": "established", "N": "new", "M": "new", "B": "new", "A": "anchor"}
    at_new = weight(NEW_CEILING, 2)
    # Two new accounts at the ceiling: 0.9263, below 0.95 even without the established-vote condition.
    met, _, probs = model_rule(UNIFORM, [("N", "same", at_new), ("M", "same", at_new)], 2, tiers, p)
    assert not met and probs["same"] == pytest.approx(0.926309, abs=1e-6)
    # One vote never resolves, whoever casts it (an anchor neither, 4.4.7).
    for name, theta in (("E", 0.95), ("N", NEW_CEILING), ("A", 0.98)):
        assert not model_rule(UNIFORM, [(name, "same", weight(theta, 2))], 2, tiers, p)[0], name
    # A known-bad voter (theta clipped to the 0.5 floor: weight 0) does not tip an established
    # vote, even one at the established ceiling: alone that is 0.95 - 2e-16, just below the rule.
    for theta in (31 / 36, 0.95):
        met, _, probs = model_rule(UNIFORM, [("E", "same", weight(theta, 2)), ("B", "same", weight(0.5, 2))],
                                   2, tiers, p)
        assert not met and probs["same"] < 0.95, theta
    # A low-reliability second vote (theta 0.6) next to the promotion floor does not either.
    assert not model_rule(UNIFORM, [("E", "same", weight(31 / 36, 2)), ("B", "same", weight(0.6, 2))], 2, tiers, p)[0]


def test_lemma_example_and_other_class():
    prior = [("kuća", math.log(1 / 3)), (OTHER, math.log(2 / 3))]
    probs = posterior(prior, {"kuća": 2 * weight(0.8, 3)})
    assert probs["kuća"] == pytest.approx(0.970, abs=1e-3)


# ---- peer evidence --------------------------------------------------------------

def test_peer_cap():
    """30 gold answers (20 hits), plus 1,000 items on which a clique agrees with the account."""
    p = params()
    people = {"X": (4, 2, 20, 10, 0.95, True)}
    work = []
    for n in range(1000):
        clique = [(f"c{i}", "same") for i in range(3)]
        for name, _ in clique:
            people.setdefault(name, (18, 2, 200, 0, 0.98, True))
        work.append((f"i{n:04d}", "s", [("X", "same"), *clique], False))
    out = fit("pair", work, people, p)
    s, u = out["soft"]["X"]
    assert s + u == pytest.approx(30, abs=1e-9)
    assert out["theta"]["X"] <= (4 + 20 + 30) / (6 + 30 + 30) + 1e-9
    assert theta_lower_bound(4, 2, 20, 30) == pytest.approx(0.539, abs=1e-3)


def test_zero_information_and_symmetric_soft_counts():
    p = params(class_prior="uniform")
    # Votes of weight 0 (quarantined, not counted) leave the prior and add no soft counts.
    out = fit("pair", [("x", "s", [("A", "same"), ("B", "different")], False)],
              {"A": (4, 2, 0, 0, 0.75, False), "B": (4, 2, 0, 0, 0.75, False)}, p)
    assert out["soft"] == {"A": (0.0, 0.0), "B": (0.0, 0.0)}
    # A 0.5/0.5 leave-one-out posterior adds equal soft hits and misses.
    people = {"A": (4, 2, 0, 0, 0.95, True), "B": (4, 2, 30, 4, 0.95, True), "C": (4, 2, 30, 4, 0.95, True)}
    out = fit("pair", [("x", "s", [("A", "same"), ("B", "same"), ("C", "different")], False)], people,
              {**p, "iterations": 1})
    s, u = out["soft"]["A"]
    assert s == pytest.approx(u) == pytest.approx(0.25)


# ---- tiers ----------------------------------------------------------------------

def test_promotion_bounds():
    assert theta_lower_bound(4, 2, 27, 30) == pytest.approx(0.767, abs=1e-3)
    assert theta_lower_bound(4, 2, 26, 30) == pytest.approx(0.732, abs=1e-3)
    assert theta_lower_bound(4, 2, 24, 25) == pytest.approx(0.817, abs=1e-3)
    assert wilson_lower_bound(29, 30) == pytest.approx(0.833, abs=1e-3)


@pytest.mark.parametrize("hits, definite, memory, wrong_hits, tier", [
    (27, 100, None, 5, "established"),
    (26, 100, None, 5, "new"),           # bound 0.732 < 0.75
    (27, 99, None, 5, "new"),            # too few definite answers
    (27, 100, None, 2, "new"),           # the hard-item floor: 2/5 suggestion-wrong
    (26, 100, "established", 5, "established"),  # kept: 0.732 >= 0.70
    (26, 100, "established", 2, "new"),  # demoted: 2/5 < 0.5 on the hard items
    (24, 100, "established", 5, "new"),  # 0.66 < 0.70
])
def test_established_at_its_boundaries(hits, definite, memory, wrong_hits, tier):
    w = World()
    pools = w.ready_pools("pair")
    train(w, pools, "X", disc_seen=30, disc_hits=hits - (5 - wrong_hits), wrong_hits=wrong_hits, definite=definite)
    if memory:
        w.event("tier.changed", annotator="X", details={"kind": "pair", "from": "new", "to": memory})
    out = score(w.inputs(), w.params)
    row = by_name(w, out)["X"]
    assert row["tier"] == tier, row
    changed = [e for e in out["events"] if e["kind"] == "tier.changed"]
    if tier != (memory or "new"):
        assert changed == [{"kind": "tier.changed", "annotator_id": w.people["X"], "corpus_id": None, "item_id": None,
                            "details": {"kind": "pair", "from": memory or "new", "to": tier}}]
    else:
        assert changed == []


def test_promotion_waits_for_readiness():
    w = World()
    pools = w.ready_pools("pair", wrong=14)  # one suggestion-wrong item short
    train(w, pools, "X", wrong_seen=5, disc_seen=30, disc_hits=27)
    out = score(w.inputs(), w.params)
    assert out["readiness"]["pair"]["promotion"] is False and out["readiness"]["pair"]["qualification"] is True
    assert by_name(w, out)["X"]["tier"] == "new"


def test_qualification_is_a_fixed_function_of_the_first_answers():
    w = World()
    pools = w.ready_pools("pair")
    w.person("Q")
    for i, key in enumerate(pools["qualification"][:12]):
        w.vote("Q", key, "different" if i in (0, 1, 2) else "same", blind=True)
    for key in pools["qualification"][12:20]:  # later answers, all wrong, change nothing
        w.vote("Q", key, "different", blind=True)
    out = score(w.inputs(), w.params)
    row = by_name(w, out)["Q"]
    assert row["qualified"] and row["tier"] == "qualified"


# ---- counting first answers -----------------------------------------------------

def test_capped_count_skips_ineligible_and_unadmitted_answers():
    caps = {"low": 2, "expert": 1}
    firsts = [("a", True, "low"), ("q", True, "low"), ("b", False, "low"), ("c", True, "low"), ("d", True, "low"),
              ("e", True, "expert"), ("f", True, "expert")]
    used, counted = count_first_answers(firsts, lambda x: x != "q", caps)
    assert used == {"low": 2, "expert": 1} and counted == {"a", "c", "e"}
    # When q becomes eligible again its earlier answer counts first; c is kept but not counted.
    used, counted = count_first_answers(firsts, lambda x: True, caps)
    assert counted == {"a", "q", "e"}
    used, counted = count_first_answers(firsts, lambda x: True, caps, uncapped=True)
    assert counted == {"a", "q", "c", "d", "e", "f"}


def test_release_rule_needs_three_voters_and_no_pivot():
    p = params(class_prior="uniform")
    tiers = {name: "established" for name in "ABCD"}
    w = weight(0.85, 2)
    three = [(n, "same", w) for n in "ABC"]
    assert release_rule(UNIFORM, three, 2, tiers, p)  # 0.9945, and 0.9698 without any one
    assert not release_rule(UNIFORM, three[:2], 2, tiers, p)  # two voters
    flipped = three[:2] + [("C", "different", w)]
    assert not model_rule(UNIFORM, flipped, 2, tiers, p)[0]  # 0.85: no row at all
    pivot = [("A", "same", weight(0.95, 2)), ("B", "same", weight(0.6, 2)), ("C", "different", weight(0.6, 2))]
    assert model_rule(UNIFORM, pivot, 2, tiers, p)[0] is False or not release_rule(UNIFORM, pivot, 2, tiers, p)


# ---- determinism --------------------------------------------------------------------

def test_identical_inputs_give_identical_outputs_and_the_golden_hash():
    world = synthetic()
    first = score(world.inputs(), world.params)
    assert sha256(first) == sha256(score(world.inputs(), world.params))
    shuffled = world.inputs()
    for name in ("judgments", "consents", "items", "trust_events", "admin_events"):
        random.Random(7).shuffle(shuffled[name])
    assert sha256(score(shuffled, world.params)) == sha256(first)
    assert sha256(first) == GOLDEN


def test_parameters_are_complete_and_bounded():
    validate_params(DEFAULT_PARAMS)
    for broken in ({"surprise": 1}, {"resolve_min_votes": 1}, {"resolve_confidence": 0.5}, {"iterations": 0},
                   {"theta_max": {"new": 0.75}}, {"class_prior": "learned"}, {"version": "1.0"},
                   {"corpora": {"00000000-0000-4000-8000-000000000000": {"resolve_min_votes": 1}}},
                   {"corpora": {"00000000-0000-4000-8000-000000000000": {"prior": [1, 1]}}},
                   {"gold_rate": {"new": 10}}, {"quarantine_review_days": 30}):
        with pytest.raises(ValueError):
            validate_params({**DEFAULT_PARAMS, **broken})
    missing = dict(DEFAULT_PARAMS)
    del missing["blind_rate"]
    with pytest.raises(ValueError):
        validate_params(missing)


# ---- states (4.5.2, 4.5.3) ----------------------------------------------------------

def experts(world, pools, *names):
    for name in names:
        train(world, pools, name, disc_seen=30, disc_hits=30, definite=100)


def crowd(world, key, answers, prefix="n", group="low"):
    """Votes from fresh `new` accounts (or the given names)."""
    for n, answer in enumerate(answers):
        name = f"{prefix}{n}"
        if name not in world.people:
            world.person(name)
        world.vote(name, key, answer, group=group)


def test_states():
    w = World(class_prior="uniform")
    pools = w.ready_pools("pair")
    experts(w, pools, "E1", "E2", "E3", "E4", "E5")
    # Contested at both caps, then adjudicated against five votes.
    contested = w.item("pair", stratum="s")
    crowd(w, contested, ["same"] * 5)
    for name, answer in (("E1", "different"), ("E2", "different"), ("E3", "same")):
        w.vote(name, contested, answer, group="expert")
    # Two anchors disagree; three established voters agree at 0.99.
    w.person("second")
    w.anchor("second")
    split = w.item("pair", stratum="s")
    w.vote("owner", split, "same", group="expert")
    w.vote("second", split, "different", group="expert")
    w.vote("E1", split, "same", group="expert")
    crowd(w, split, ["same"] * 3, prefix="c")
    # Ambiguous, then reopened.
    vague = w.item("pair", stratum="s")
    crowd(w, vague, ["same", "different"], prefix="v")
    out = score(w.inputs(), w.params)
    assert state_of(out, contested)["state"] == "contested" and state_of(out, split)["state"] == "contested"

    w.event("item.adjudicated", item=contested, actor="curator", details={"answer": "different", "lemma": "",
                                                                         "irregular": False, "reason": "x"})
    w.event("item.ambiguous", item=vague, actor="curator", details={"reason": "x"})
    out = score(w.inputs(), w.params)
    row = posterior_of(out, contested)
    assert (row["state"], row["resolution_source"], row["resolved_answer"]) == ("resolved", "adjudication", "different")
    assert row["classes"][0]["answer"] == "same"  # the posterior keeps the crowd's view
    assert state_of(out, contested)["releasable"] and state_of(out, vague)["state"] == "ambiguous"

    # Reopening without discard renews the budget: open with n_low = 0; five new low answers -> needs_expert.
    w.event("item.reopened", item=contested, actor="curator", details={"reason": "x", "discard_previous": False})
    w.event("item.reopened", item=vague, actor="curator", details={"reason": "x", "discard_previous": False})
    out = score(w.inputs(), w.params)
    assert (state_of(out, contested)["state"], state_of(out, contested)["n_low"]) == ("open", 0)
    assert state_of(out, vague)["state"] == "open"
    assert posterior_of(out, contested)["n_definite"] == 8  # earlier votes stay in the posterior
    crowd(w, contested, ["same", "different", "same", "different"], prefix="r")
    assert state_of(score(w.inputs(), w.params), contested)["state"] == "open"
    crowd(w, contested, ["same"], prefix="s")
    out = score(w.inputs(), w.params)
    assert (state_of(out, contested)["state"], state_of(out, contested)["n_low"]) == ("needs_expert", 5)

    # A reopen with discard_previous removes the earlier votes from the posterior.
    w.event("item.reopened", item=contested, actor="curator", details={"reason": "x", "discard_previous": True})
    out = score(w.inputs(), w.params)
    assert contested not in [(p["corpus_id"], p["item_id"]) for p in out["posteriors"] if p["n_definite"]]
    assert state_of(out, contested)["state"] == "open"


def test_an_adjudicated_item_whose_voters_are_all_blocked():
    w = World()
    w.ready_pools("pair")
    key = w.item("pair", stratum="s")
    crowd(w, key, ["same", "same"])
    w.event("item.adjudicated", item=key, actor="curator", details={"answer": "same", "lemma": "", "irregular": False})
    for name in ("n0", "n1"):
        w.status(name, "blocked")
    out = score(w.inputs(), w.params)
    row = posterior_of(out, key)
    assert (row["classes"], row["confidence"], row["state"], row["resolution_source"]) == ([], None, "resolved",
                                                                                          "adjudication")
    assert (row["n_definite"], row["n_annotators"]) == (0, 0)
    queue = state_of(out, key)
    assert (queue["state"], queue["confidence"], queue["releasable"]) == ("resolved", None, True)


def test_an_uncalibrated_cell_is_provisional_and_completion_work_stays_servable():
    world, _, x = worked_example()
    world.judgments = [r for r in world.judgments if not (r["item_id"] == x[1] and r["annotator_id"] == world.people["B"])]
    out = score(world.inputs(), world.params)
    queue = state_of(out, x)
    assert queue["state"] == "provisional" and not queue["releasable"] and queue["priority"] == 0.05


# ---- abuse signals (4.8) --------------------------------------------------------------

def flagged(out, world, name, kind="pair"):
    row = by_name(world, out, kind).get(name)
    return {flag for flag, value in row["flags"].items() if isinstance(value, dict) and value.get("on")}


def votes(world, name, answers, elapsed=4000, kind="pair"):
    for answer in answers:
        key = world.item(kind, stratum="filler")
        world.vote(name, key, answer, elapsed=elapsed)


@pytest.mark.parametrize("n, elapsed, on", [(30, 999, True), (30, 1000, False), (29, 500, False)])
def test_fast(n, elapsed, on):
    w = World()
    w.person("F")
    votes(w, "F", ["same", "different"] * (n // 2) + ["same"] * (n % 2), elapsed=elapsed)
    assert ("fast" in flagged(score(w.inputs(), w.params), w, "F")) is on


@pytest.mark.parametrize("run, kind, on", [(12, "pair", True), (11, "pair", False), (12, "stem", True),
                                           (12, "lemma", False)])
def test_straight(run, kind, on):
    w = World()
    w.person("S")
    answer = {"pair": "same", "stem": "accept", "lemma": "confirmed"}[kind]
    for _ in range(run):
        key = w.item(kind, stratum="filler")
        w.vote("S", key, answer, lemma="kuća" if kind == "lemma" else "")
    assert ("straight" in flagged(score(w.inputs(), w.params), w, "S", kind)) is on


@pytest.mark.parametrize("seen, hits, on", [(12, 7, True), (12, 8, False), (11, 0, False)])
def test_gold_accuracy(seen, hits, on):
    w = World()
    pools = w.ready_pools("pair")
    w.person("G")
    for n, key in enumerate(pools["audit"][:seen]):
        w.vote("G", key, "same" if n < hits else "different")
        votes(w, "G", ["different"])  # no straight runs
    assert ("accuracy" in flagged(score(w.inputs(), w.params), w, "G")) is on


@pytest.mark.parametrize("wrong_hits, on", [(2, True), (3, False)])
def test_copy(wrong_hits, on):
    w = World()
    pools = w.ready_pools("pair")
    w.person("C")
    for n, key in enumerate(pools["wrong"][:5]):
        w.vote("C", key, "same" if n < wrong_hits else "different")  # the suggestion says `different`
    for key in pools["audit"][:10]:
        w.vote("C", key, "same")
        votes(w, "C", ["different"])
    assert ("copy" in flagged(score(w.inputs(), w.params), w, "C")) is on


@pytest.mark.parametrize("checked, lost, on", [(10, 4, True), (10, 3, False), (9, 9, False)])
def test_review_loss(checked, lost, on):
    w = World()
    w.ready_pools("pair")
    w.person("R")
    for n in range(checked):
        key = w.item("pair", stratum="s")
        w.vote("owner", key, "same")
        w.vote("R", key, "different" if n < lost else "same")
    assert ("review_loss" in flagged(score(w.inputs(), w.params), w, "R")) is on


def test_two_hard_flags_quarantine_silently_and_anchors_never():
    w = World()
    w.ready_pools("pair")
    for name in ("Q", "owner"):
        if name not in w.people:
            w.person(name)
        votes(w, name, ["same"] * 30, elapsed=200)  # fast and straight
    w.person("one")
    votes(w, "one", ["same", "different"] * 15, elapsed=200)  # fast only
    out = score(w.inputs(), w.params)
    changes = {c["annotator_id"]: c for c in out["status_changes"]}
    assert set(changes) == {w.people["Q"]}
    assert changes[w.people["Q"]]["flags"] == ["fast", "straight"]
    assert [e["kind"] for e in out["events"] if e["annotator_id"] == w.people["Q"]] == ["annotator.quarantined"]
    # The quarantine applies in the same run: Q's votes are not counted, and Q's tier is quarantined.
    assert by_name(w, out)["Q"]["tier"] == "quarantined" and by_name(w, out)["Q"]["base_tier"] == "new"
    assert {"fast", "straight"} <= flagged(out, w, "owner")


@pytest.mark.parametrize("days, automated, released", [(14, True, True), (13, True, False), (20, False, False)])
def test_review_deadline(days, automated, released):
    w = World()
    w.person("P")
    votes(w, "P", ["same", "different"] * 3)
    w.status("P", "quarantined", automated=automated, days_ago=days)
    out = score(w.inputs(), w.params)
    if released:
        assert out["status_changes"] == [{"annotator_id": w.people["P"], "from": "quarantined", "to": "active",
                                          "reason": "review_deadline"}]
        assert [e["details"] for e in out["events"] if e["kind"] == "annotator.cleared"] == [{"reason": "review_deadline"}]
        assert by_name(w, out)["P"]["tier"] == "new"
    else:
        assert out["status_changes"] == [] and by_name(w, out)["P"]["tier"] == "quarantined"


def test_a_promoted_clique_is_caught_by_review_answers():
    """Three established accounts answer gold correctly and resolve ordinary items wrongly
    at 0.9945. The owner's review-sample answers are counted although the expert slots
    are full, build `review_loss` for each, and a second flag quarantines them."""
    w = World(class_prior="uniform")
    pools = w.ready_pools("pair")
    clique = ("K1", "K2", "K3")
    experts(w, pools, *clique)
    sampled, ordinary = [], []
    for n in range(300):
        key = w.item("pair", stratum="s", review=n < 12)
        for name in clique:
            w.vote(name, key, "different", group="expert")  # wrong: the truth is `same`
        (sampled if n < 12 else ordinary).append(key)
    for key in sampled[:9]:
        w.vote("owner", key, "same", group="expert")
    out = score(w.inputs(), w.params)
    assert state_of(out, ordinary[0])["state"] == "resolved" or state_of(out, ordinary[0])["state"] == "provisional"
    first = posterior_of(out, sampled[0])
    assert first["n_anchor_votes"] == 1 and first["n_expert"] == 3  # counted beyond the full expert slots
    assert (first["state"], first["resolution_source"], first["resolved_answer"]) == ("resolved", "review", "same")
    assert out["status_changes"] == []  # one hard flag (straight) is not enough
    for key in sampled[9:]:
        w.vote("owner", key, "same", group="expert")
    out = score(w.inputs(), w.params)
    quarantined = {c["annotator_id"] for c in out["status_changes"] if c["to"] == "quarantined"}
    assert quarantined == {w.people[name] for name in clique}
    for name in clique:
        assert {"review_loss", "straight"} <= flagged(out, w, name)
    # Their votes stop counting in the same run: the ordinary items are open again.
    assert state_of(out, ordinary[0])["state"] == "open"


def test_a_run_resolves_two_votes_of_an_established_and_a_new_annotator():
    """Through score(): E promoted at the floor (27 of 30 discriminating, no other evidence),
    N new with four correct known-answer items (prior 4/6 -> 8/10, clipped to the new ceiling).
    Their two agreeing votes meet the rule; the cell is not calibrated, so `provisional`.
    Two new voters, a known-bad voter (2 of 8 known answers right: theta at the 0.5 floor) or a
    quarantined one next to E do not."""
    w = World(class_prior="uniform")
    pools = w.ready_pools("pair")
    train(w, pools, "E")
    for name, hits, seen in (("N", 4, 4), ("M", 4, 4), ("B", 2, 8), ("Q", 4, 4)):
        w.person(name)
        for n, key in enumerate(pools["audit"][90 - 2 * seen:90 - seen]):
            w.vote(name, key, "same" if n < hits else "different")
    w.status("Q", "quarantined")
    cases = {"en": ("E", "N"), "nm": ("N", "M"), "eb": ("E", "B"), "eq": ("E", "Q"), "e": ("E",)}
    keys = {}
    for case, voters in cases.items():
        keys[case] = w.item("pair", stratum="s")
        for name in voters:
            w.vote(name, keys[case], "same")
    out = score(w.inputs(), w.params)
    rows = by_name(w, out)
    assert (rows["E"]["tier"], rows["N"]["tier"], rows["B"]["tier"], rows["Q"]["tier"]) == (
        "established", "new", "new", "quarantined")
    # E: 31/36 from gold, plus the soft count of agreeing with N (0.39 / 0.11): 31.39 / 36.5 = 0.86.
    assert rows["E"]["theta_mean"] == pytest.approx(0.86, abs=1e-6)
    assert rows["N"]["theta_mean"] == NEW_CEILING and rows["B"]["theta_mean"] == 0.5
    states = {case: posterior_of(out, key) for case, key in keys.items()}
    assert (states["en"]["state"], states["en"]["confidence"]) == ("provisional", pytest.approx(0.956100, abs=1e-6))
    assert states["nm"]["state"] == "open" and states["nm"]["confidence"] == pytest.approx(0.926309, abs=1e-6)
    assert states["eb"]["state"] == "open" and states["eb"]["confidence"] == pytest.approx(0.86, abs=1e-6)
    assert states["eq"]["state"] == "open" and states["eq"]["n_definite"] == 1
    assert states["e"]["state"] == "open"
    # The same journal under the 0.3.0 ceiling needs a third vote.
    old = params(class_prior="uniform", theta_max={**DEFAULT_PARAMS["theta_max"], "new": 0.75})
    assert posterior_of(score(w.inputs(), old), keys["en"])["state"] == "open"

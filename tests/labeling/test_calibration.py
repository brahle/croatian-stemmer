"""The calibration gate (4.4.7): synthetic data generated from the model with fixed seeds.

Items in a cell are `resolved` only once a frozen evaluation set of sampled items,
checked against the owner's reference answers, shows the 0.95 rule holds there."""
from scoring_world import World, calibration_world, train
from croatian_stemmer.labeling.scoring import score


def cells(out, kind="pair"):
    return {key.split("/")[1]: value for key, value in out["calibration"].items() if key.startswith(kind + "/")}


def test_independent_annotators_calibrate_both_cells():
    world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
    out = score(world.inputs(), world.params)
    assert {cell: value["passed"] for cell, value in cells(out).items()} == {"agrees": True, "differs": True}
    resolved = [p for p in out["posteriors"] if p["state"] == "resolved" and p["resolution_source"] == "model"
                and (p["corpus_id"], p["item_id"]) in truth]
    assert len(resolved) > 500
    correct = sum(p["resolved_answer"] == truth[(p["corpus_id"], p["item_id"])] for p in resolved)
    assert correct / len(resolved) >= 0.95


def test_correlated_errors_fail_the_agrees_cell():
    """Half of the crowd echoes the suggestion, which is wrong on 30 % of items. (With 30 %
    copiers and a 20 % wrong suggestion, two-vote items resolve wrongly on about 2 % of the
    agrees cell, which a 29-of-30 gate does not reliably detect; this is the stronger case.)"""
    world, truth = calibration_world(seed=1, items=900, voters=2, copiers=0.5, wrong_rate=0.3, theta=0.97, sampled=0.3)
    out = score(world.inputs(), world.params)
    agrees = cells(out)["agrees"]
    assert agrees["n"] == 30 and agrees["correct"] < 29 and not agrees["passed"]
    rows = [p for p in out["posteriors"] if p["cell"] == "agrees" and p["resolution_source"] != "reference"]
    assert not [p for p in rows if p["state"] == "resolved"]
    assert len([p for p in rows if p["state"] == "provisional"]) > 50


def test_class_imbalance_with_estimated_priors():
    world, truth = calibration_world(seed=3, items=1500, voters=3, theta=0.97, sampled=0.3, same_rate=0.9)
    out = score(world.inputs(), world.params)
    assert cells(out)["agrees"]["passed"]
    resolved = [p for p in out["posteriors"] if p["state"] == "resolved" and p["resolution_source"] == "model"
                and (p["corpus_id"], p["item_id"]) in truth]
    minority = [p for p in resolved if truth[(p["corpus_id"], p["item_id"])] == "different"]
    assert minority and all(p["resolved_answer"] == "different" for p in minority)


def test_one_anchor_reference_is_final_and_isolated():
    world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
    first = score(world.inputs(), world.params)
    member = tuple(cells(first)["agrees"]["items"][0])
    owner = world.people["owner"]
    # The owner answers this evaluation item against the crowd.
    for row in world.judgments:
        if (row["corpus_id"], row["item_id"]) == member and row["annotator_id"] == owner:
            row["answer"] = "different" if truth[member] == "same" else "same"
    out = score(world.inputs(), world.params)
    row = next(p for p in out["posteriors"] if (p["corpus_id"], p["item_id"]) == member)
    assert (row["state"], row["resolution_source"]) == ("resolved", "reference")
    assert row["resolved_answer"] != truth[member]
    assert cells(out)["agrees"]["correct"] == 29
    assert not [e for e in out["events"] if e["kind"] == "gold.set" and (e["corpus_id"], e["item_id"]) == member]
    # Without any owner answer on it, weights, tiers and statuses are identical: references are isolated.
    world.judgments = [r for r in world.judgments
                       if not ((r["corpus_id"], r["item_id"]) == member and r["annotator_id"] == owner)]
    without = score(world.inputs(), world.params)
    crowd = lambda o: [(s["annotator_id"], s["kind"], s["tier"], s["theta_mean"], s["weight"]) for s in o["scores"]
                       if s["annotator_id"] != owner]
    assert crowd(out) == crowd(without)
    assert out["status_changes"] == without["status_changes"]
    assert [e for e in out["events"] if e["kind"].startswith("gold.")] == \
        [e for e in without["events"] if e["kind"].startswith("gold.")]


def test_two_anchors_disagreeing_contest_in_either_order():
    for order in (("owner", "second"), ("second", "owner")):
        world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
        world.person("second")
        world.anchor("second")
        first = score(world.inputs(), world.params)
        member = tuple(cells(first)["agrees"]["items"][0])
        right, wrong = truth[member], "different" if truth[member] == "same" else "same"
        owner = world.people["owner"]
        world.judgments = [r for r in world.judgments
                           if not ((r["corpus_id"], r["item_id"]) == member and r["annotator_id"] == owner)]
        answers = {"owner": right, "second": wrong}
        for name in order:
            world.vote(name, member, answers[name], blind=True)
        out = score(world.inputs(), world.params)
        row = next(p for p in out["posteriors"] if (p["corpus_id"], p["item_id"]) == member)
        assert row["state"] == "contested" and row["resolution_source"] is None, order
        assert cells(out)["agrees"]["correct"] <= 29


def test_a_policy_change_draws_a_new_set_and_a_neutral_one_does_not():
    world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
    first = world.run()
    drawn = [e for e in first["events"] if e["kind"] == "calibration.drawn"]
    assert {e["details"]["cell"] for e in drawn} == {"agrees", "differs"}
    again = world.run()
    assert not [e for e in again["events"] if e["kind"] == "calibration.drawn"]
    assert cells(again)["agrees"]["passed"] and cells(again)["agrees"]["drawn_seq"] is not None
    # A neutral setting keeps the sets.
    world.params = {**world.params, "release_min_voters": 4}
    neutral = world.run()
    assert not [e for e in neutral["events"] if e["kind"] == "calibration.drawn"]
    for change in ({"votes_low_cap": 6}, {"flags": {**world.params["flags"], "straight_run": 13}},
                   {"readiness": {**world.params["readiness"], "minority_class_share": 0.3}}, {"soft_weight": 0.4}):
        world.params = {**world.params, **change}
        out = world.run()
        new = [e for e in out["events"] if e["kind"] == "calibration.drawn"]
        assert new and new[0]["details"]["calibration_key"] != drawn[0]["details"]["calibration_key"], change
        # The owner's existing answers are reused as references.
        assert cells(out)["agrees"]["pending"] == []


def test_coverage_expansion_puts_newly_resolvable_items_into_the_new_set():
    """Under an established ceiling of 0.80 only three-vote items resolve (all correct); two
    agreeing votes give 0.9412. At 0.85 two votes give 0.9698: the new set represents the
    two-vote items, which are wrong, so the cell does not calibrate on old trials."""
    import random
    rng = random.Random(5)
    world = World(class_prior="uniform",
                  theta_max={"new": 0.75, "qualified": 0.80, "established": 0.80, "anchor": 0.98})
    pools = world.ready_pools("pair")
    names = [f"e{n}" for n in range(8)]
    for name in names:
        train(world, pools, name, disc_seen=30, disc_hits=30, definite=100)
    truth, two_vote = {}, set()
    for n in range(400):
        key = world.item("pair", stratum="s", audit=True)  # the suggestion implies `same`
        if n % 2:
            truth[key] = "same"
            for name in rng.sample(names, 3):
                world.vote(name, key, "same")
        else:
            truth[key] = "different"
            for name in rng.sample(names, 2):
                world.vote(name, key, "same")  # wrong, agreeing with each other and the suggestion
            two_vote.add(key)
    before = world.run()
    members = {tuple(m) for m in cells(before)["agrees"]["items"]}
    assert len(members) == 30 and not members & two_vote
    for key in members:
        world.vote("owner", key, truth[key], blind=True)
    assert cells(world.run())["agrees"]["passed"]
    world.params = {**world.params, "theta_max": {**world.params["theta_max"], "established": 0.85}}
    after = world.run()
    new = {tuple(m) for c in cells(after).values() for m in c["items"]}
    assert new & two_vote, "two-vote items now resolve and are represented"
    assert {tuple(m) for m in cells(after)["agrees"]["pending"]} == new - members
    assert not cells(after)["agrees"]["passed"]
    for key in new - members:
        world.vote("owner", key, truth[key], blind=True)
    assert not cells(world.run())["agrees"]["passed"]


def test_the_owner_is_asked_for_one_set_only():
    """The resolvable sampled population grows from 30 to 1,000 under one policy; the owner
    answers everything asked and is asked exactly the 30 items of the first draw."""
    import random
    rng = random.Random(9)
    world = World(class_prior="uniform")
    pools = world.ready_pools("pair")
    names = [f"e{n}" for n in range(6)]
    for name in names:
        train(world, pools, name, disc_seen=30, disc_hits=30, definite=100)
    asked, answered = set(), set()

    def grow(n):
        for _ in range(n):
            key = world.item("pair", stratum="s", audit=True)
            for name in rng.sample(names, 3):
                world.vote(name, key, "same")

    for step in (30, 1, 29, 140, 800):
        grow(step)
        out = world.run()
        cell = cells(out)["agrees"]
        asked |= {tuple(m) for m in cell["pending"]}
        for key in {tuple(m) for m in cell["pending"]} - answered:
            world.vote("owner", key, "same", blind=True)
            answered.add(key)
    assert len(asked) == 30 and cell["population"] >= 1000
    final = cells(world.run())["agrees"]
    assert final["passed"] and final["n"] == 30
    # A frozen member that stops meeting the model rule counts as a failure.
    member = tuple(final["items"][0])
    voters = [name for name in names if (world.people[name], member) in world.revisions]
    for name in voters:
        world.vote(name, member, "different")  # a revision: the crowd no longer agrees with the reference
    assert cells(world.run())["agrees"]["correct"] <= 29


def test_the_draw_is_the_lowest_ranks_and_outcomes_outside_it_do_not_count():
    world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
    owner = world.people["owner"]
    out = score(world.inputs(), world.params)
    agrees = cells(out)["agrees"]
    ranks = {(i["corpus_id"], i["item_id"]): i["audit_rank"] for i in world.items}
    eligible = sorted(agrees["items"], key=lambda key: ranks[tuple(key)])
    assert agrees["items"] == eligible and agrees["population"] > 30
    inside = {tuple(m) for m in agrees["items"]}
    # The owner disagrees with the crowd on many sampled items outside the set: the cell still passes.
    flipped = 0
    for row in world.judgments:
        key = (row["corpus_id"], row["item_id"])
        if row["annotator_id"] == owner and key in truth and key not in inside and flipped < 40:
            row["answer"] = "different" if row["answer"] == "same" else "same"
            flipped += 1
    out = score(world.inputs(), world.params)
    assert cells(out)["agrees"]["passed"] and cells(out)["agrees"]["items"] == agrees["items"]


def test_replay_from_the_bundle_alone_reproduces_the_draw_and_the_cells():
    """No settings, no item-state table, no audit key: the ranks travel in the bundle."""
    from croatian_stemmer.labeling.scoring import inputs_sha256, inputs_summary, replay, sha256
    world, truth = calibration_world(seed=1, items=1200, voters=3, theta=0.97, sampled=0.3)
    inputs = world.inputs()
    out = score(inputs, world.params)
    assert cells(out)["agrees"]["population"] > 30 and cells(out)["agrees"]["passed"]
    bundle = {"run": {"id": "r", "params": world.params, "inputs_sha256": inputs_sha256(inputs),
                      "inputs_summary": inputs_summary(inputs), "outputs_sha256": sha256(out)},
              "inputs": inputs}
    result = replay(bundle)
    assert result["report"]["inputs_match"] and result["report"]["outputs_match"]
    assert result["outputs"]["calibration"] == out["calibration"]

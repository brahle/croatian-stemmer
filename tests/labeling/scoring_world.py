"""A synthetic journal for the pure scoring function: people, items, votes and events.

Every row gets the next journal position, as the database trigger would give it.
Nothing here is dataset gold; ids are deterministic so outputs are reproducible.
"""
from datetime import date, datetime, timedelta, timezone

from croatian_stemmer.labeling.scoring import DEFAULT_PARAMS, validate_params

CORPUS = "00000000-0000-4000-8000-00000000c0de"


def uid(prefix, n):
    return f"{prefix:08x}-0000-4000-8000-{n:012d}"


class World:
    def __init__(self, today="2026-10-18", **params):
        self.today = date.fromisoformat(today)
        self.seq = 0
        self.items, self.judgments, self.consents, self.admin, self.trust = [], [], [], [], []
        self.people, self.revisions, self._n, self.gold_answers = {}, {}, 0, {}
        self.params = validate_params({**DEFAULT_PARAMS, **params})

    def _next(self):
        self.seq += 1
        return self.seq

    def _id(self, prefix):
        self._n += 1
        return uid(prefix, self._n)

    def moment(self, days_ago=3, offset=0):
        base = datetime.combine(self.today - timedelta(days=days_ago), datetime.min.time(), timezone.utc)
        return (base + timedelta(hours=8, seconds=self.seq + offset)).isoformat()

    # ---- people ----
    def person(self, name, cohort=True, privacy="1.3"):
        annotator = self._id(1)
        self.people[name] = annotator
        if cohort:
            for document, version in (("privacy", privacy), ("terms", "1.1"), ("participation", "1.0")):
                self.consents.append({"seq": self._next(), "annotator_id": annotator, "document": document,
                                      "version": version, "age_threshold": 18})
        return annotator

    def consent(self, name, document, version):
        self.consents.append({"seq": self._next(), "annotator_id": self.people[name], "document": document,
                              "version": version, "age_threshold": 18})

    def anchor(self, name):
        self.event("anchor.granted", annotator=name, details={"trusted_id": 1})

    def status(self, name, to, *, previous="active", automated=False, days_ago=0, reason="test"):
        details = {"from": previous, "to": to}
        details.update({"flags": ["fast", "straight"], "run_id": "run"} if automated else {"reason": reason})
        self.admin.append({"seq": self._next(), "id": len(self.admin) + 1, "at": self.moment(days_ago),
                           "actor_id": None if automated else self.people.get("curator", uid(9, 9)),
                           "kind": "annotator.status", "target": self.people[name], "details": details})

    def erase(self, name):
        self.admin.append({"seq": self._next(), "id": len(self.admin) + 1, "at": self.moment(0), "actor_id": None,
                           "kind": "erasure.requested", "target": self.people[name], "details": {}})

    def event(self, kind, *, annotator=None, item=None, details=None, actor=None, run_id=None):
        row = {"id": self._next(), "at": self.moment(0), "actor_id": actor, "kind": kind,
               "annotator_id": self.people.get(annotator, annotator) if annotator else None,
               "corpus_id": item[0] if item else None, "item_id": item[1] if item else None,
               "run_id": run_id, "details": details or {}}
        self.trust.append(row)
        return row["id"]

    # ---- items ----
    def item(self, kind="pair", stratum="s", lemma="kuća", other_lemma=None, audit=False, review=False, rank=None,
             corpus=CORPUS):
        key = (corpus, self._id(2))
        self.items.append({"corpus_id": key[0], "item_id": key[1], "kind": kind, "stratum": stratum,
                           "proposed_lemma": lemma,
                           "other_proposed_lemma": (lemma if other_lemma is None else other_lemma) if kind == "pair" else "",
                           "status": "active", "audit_sample": audit, "review_sample": review,
                           "audit_rank": self._n if rank is None else rank, "seq": self._next()})
        return key

    def gold(self, key, answer, *, pool="audit", lemma="", source="hr500k", agrees=True, support=None, actor=None):
        kind = next(i["kind"] for i in self.items if (i["corpus_id"], i["item_id"]) == key)
        details = {"pool": pool, "answer": answer, "lemma": lemma, "source": source, "basis": "test",
                   "batch": None, "suggestion_agrees": None if kind == "stem" else agrees}
        if support is not None:
            details["support"] = support
        self.gold_answers[key] = lemma if kind == "lemma" else answer
        return self.event("gold.set", item=key, details=details, actor=actor)

    def vote(self, name, key, answer, *, lemma="", blind=False, admitted=True, group="low", days_ago=3,
             elapsed=4000, irregular=False):
        annotator = self.people[name]
        revision = self.revisions.get((annotator, key), 0) + 1
        self.revisions[(annotator, key)] = revision
        jid = self._id(3)
        self.judgments.append({"seq": self._next(), "id": jid, "corpus_id": key[0], "item_id": key[1],
                               "annotator_id": annotator, "revision": revision, "answer": answer, "lemma": lemma,
                               "irregular": irregular, "admitted": admitted, "admission_group": group,
                               "presentation": "blind" if blind else "shown", "elapsed_ms": elapsed,
                               "created_at": self.moment(days_ago)})
        return jid

    def publish(self, out, run_id="run"):
        """What publication appends: the decided events and the automatic status changes."""
        for change in out["status_changes"]:
            details = {"from": change["from"], "to": change["to"], "run_id": run_id,
                       **({"flags": change["flags"]} if "flags" in change else {"reason": change["reason"]})}
            self.admin.append({"seq": self._next(), "id": len(self.admin) + 1, "at": self.moment(0), "actor_id": None,
                               "kind": "annotator.status", "target": change["annotator_id"], "details": details})
        for event in out["events"]:
            self.trust.append({"id": self._next(), "at": self.moment(0), "actor_id": None, "kind": event["kind"],
                               "annotator_id": event["annotator_id"], "corpus_id": event["corpus_id"],
                               "item_id": event["item_id"], "run_id": run_id, "details": event["details"]})

    def run(self, run_id="run"):
        """score() and publish, as one scoring run does."""
        from croatian_stemmer.labeling.scoring import score
        out = score(self.inputs(), self.params)
        self.publish(out, run_id)
        return out

    def inputs(self, watermark=None):
        return {"watermark": self.seq if watermark is None else watermark, "as_of_day": self.today.isoformat(),
                "items": sorted(self.items, key=lambda r: (r["corpus_id"], r["item_id"])),
                "judgments": list(self.judgments), "consents": list(self.consents),
                "admin_events": list(self.admin), "trust_events": list(self.trust)}

    # ---- composite set-ups ----
    def ready_pools(self, kind="pair", qualification=60, audit=100, wrong=15):
        """Enough gold for qualification, audit serving and promotion, and one anchor."""
        made = {"qualification": [], "audit": [], "wrong": []}
        for pool, n, agrees in (("qualification", qualification, True), ("audit", audit, True), ("wrong", wrong, False)):
            for index in range(n):
                if kind == "stem":
                    key = self.item("stem", stratum="word_suggestion")
                    self.gold(key, "accept" if index % 2 else "reject", pool="qualification" if pool == "qualification" else "audit",
                              source="curator")
                elif kind == "lemma":
                    key = self.item("lemma", stratum="word_suggestion", lemma="kuća" if agrees else "kuć")
                    self.gold(key, "confirmed", lemma="kuća", pool="audit" if pool == "wrong" else pool, agrees=agrees)
                else:
                    key = self.item("pair", stratum="corpus_same_lemma_suggestion", other_lemma=None if agrees else "kuće")
                    self.gold(key, "same", pool="audit" if pool == "wrong" else pool, agrees=agrees)
                made[pool].append(key)
        if "owner" not in self.people:
            self.person("owner")
            self.anchor("owner")
        return made


def synthetic(seed=1, judgments=2000, annotators=8, kinds=("pair", "lemma", "stem")):
    """A reproducible mixed journal of about `judgments` answers from annotators of known accuracy."""
    import random
    rng = random.Random(seed)
    readiness = {"qualification_pool": 20, "audit_pool": 40, "wrong_suggestion_pool": 6, "stem_qualification_pool": 16,
                 "stem_audit_pool": 30, "minority_class_share": 0.25, "anchors": 1}
    # Low promotion floors so a small journal exercises every tier.
    w = World(readiness=readiness, established_votes=20, established_disc_gold=10, established_wrong_sugg_gold=2,
              qualification_n=4, qualification_hits=3)
    pools = {kind: w.ready_pools(kind, qualification=20, audit=40, wrong=6) for kind in kinds}
    people = []
    for n in range(annotators):
        name = f"p{n}"
        w.person(name)
        people.append((name, rng.choice((0.6, 0.75, 0.85, 0.95))))
    items = []
    for n in range(max(1, judgments // 8)):
        kind = kinds[n % len(kinds)]
        if kind == "pair":
            same = rng.random() < 0.6
            key = w.item("pair", stratum=rng.choice(("corpus_same_lemma_suggestion", "random_different_lemma_suggestion")),
                         other_lemma=None if same else "drugo", audit=rng.random() < 0.1)
            truth = "same" if same else "different"
        elif kind == "lemma":
            key = w.item("lemma", stratum="word_suggestion", audit=rng.random() < 0.1)
            truth = "kuća"
        else:
            key = w.item("stem", stratum="word_suggestion", audit=rng.random() < 0.1)
            truth = rng.choice(("accept", "reject"))
        items.append((key, kind, truth))
    gold_keys = [(key, kind) for kind in kinds for pool in pools[kind].values() for key in pool]
    made = 0
    while made < judgments:
        name, theta = rng.choice(people)
        if rng.random() < 0.5:
            key, kind = rng.choice(gold_keys)
            truth = w.gold_answers[key]
        else:
            key, kind, truth = rng.choice(items)
        right = rng.random() < theta
        if kind == "pair":
            answer, lemma = (truth if right else ("different" if truth == "same" else "same")), ""
        elif kind == "lemma":
            answer, lemma = "confirmed", truth if right else rng.choice(("kuć", "kuće"))
        else:
            answer, lemma = (truth if right else ("reject" if truth == "accept" else "accept")), ""
        if rng.random() < 0.05:
            answer, lemma = "unsure", ""
        w.vote(name, key, answer, lemma=lemma, blind=rng.random() < 0.5, days_ago=rng.randint(0, 5),
               elapsed=rng.randint(800, 9000))
        made += 1
    return w


def train(w, pools, name, disc_seen=30, disc_hits=27, wrong_seen=5, wrong_hits=5, definite=100, kind="pair"):
    """Give `name` discriminating gold evidence (blind audit answers plus answers on gold whose
    answer differs from the suggestion) and enough other definite answers, without long
    runs of identical answers (which would raise `straight`)."""
    if name not in w.people:
        w.person(name)
    answers = {"pair": ("same", "different"), "stem": ("accept", "reject")}[kind] if kind != "lemma" else None
    plan = [(key, n < wrong_hits) for n, key in enumerate(pools["wrong"][:wrong_seen])]
    plan += [(key, n < disc_hits - wrong_hits) for n, key in enumerate(pools["audit"][:disc_seen - wrong_seen])]
    made = 0
    for n, (key, hit) in enumerate(plan):
        truth = w.gold_answers[key]
        if kind == "lemma":
            w.vote(name, key, "confirmed", lemma=truth if hit else "kriva", blind=True)
        else:
            w.vote(name, key, truth if hit else answers[1 - answers.index(truth)], blind=True)
        made += 1
        if n % 5 == 4:
            filler(w, name, kind, made)
            made += 1
    while made < definite:
        filler(w, name, kind, made)
        made += 1


def filler(w, name, kind, n):
    """One definite answer on a fresh single-vote item, alternating classes."""
    key = w.item(kind, stratum="filler")
    if kind == "lemma":
        w.vote(name, key, "confirmed", lemma="kuća" if n % 2 else "kuće")
    else:
        w.vote(name, key, {"pair": ("same", "different"), "stem": ("accept", "reject")}[kind][n % 2])


def worked_example():
    """The worked example of 4.4.6 (uniform class prior): A established (40 hard gold, 36 hits),
    B new, C qualified (15, 12); one non-gold item X voted same / different / same."""
    w = World(class_prior="uniform")
    pools = w.ready_pools("pair")
    train(w, pools, "A", disc_seen=40, disc_hits=36, wrong_seen=10, wrong_hits=8, definite=100)
    w.person("B")
    w.person("C")
    for i, key in enumerate(pools["qualification"][:12]):
        w.vote("C", key, "same" if i not in (2, 6, 10) else "different", blind=True)
    for key in pools["audit"][60:63]:
        w.vote("C", key, "same", blind=True)
    x = w.item("pair", stratum="s")
    w.vote("A", x, "same")
    w.vote("B", x, "different")
    w.vote("C", x, "same")
    return w, pools, x


def calibration_world(seed=1, items=300, voters=3, crowd=10, theta=0.97, copiers=0.0, wrong_rate=0.2,
                      reference=True, sampled=1.0, same_rate=0.5, **params):
    """Established annotators of accuracy `theta` vote on calibration-sampled pair items;
    a share `copiers` of them echo the suggestion, which is wrong on `wrong_rate` of items.
    The owner (the one anchor) answers every sampled item correctly when `reference`."""
    import random
    rng = random.Random(seed)
    w = World(**params)
    pools = w.ready_pools("pair")
    names = [f"e{n}" for n in range(crowd)]
    copying = set(names[:round(copiers * crowd)])
    for name in names:
        train(w, pools, name, disc_seen=30, disc_hits=30, wrong_seen=5, wrong_hits=5, definite=100)
    truth = {}
    for _ in range(items):
        same = rng.random() < same_rate
        suggestion_right = rng.random() >= wrong_rate
        suggests_same = same if suggestion_right else not same
        key = w.item("pair", stratum="s", other_lemma=None if suggests_same else "drugo",
                     audit=rng.random() < sampled)
        truth[key] = "same" if same else "different"
        suggestion = "same" if suggests_same else "different"
        for name in rng.sample(names, voters):
            if name in copying:
                answer = suggestion
            else:
                answer = truth[key] if rng.random() < theta else ("different" if same else "same")
            w.vote(name, key, answer)
        if reference and next(i for i in w.items if (i["corpus_id"], i["item_id"]) == key)["audit_sample"]:
            w.vote("owner", key, truth[key], blind=True)
    return w, truth

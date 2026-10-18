"""What an annotator is shown next, and the keyed rules behind it.

Every rule that must not be predictable from anything a person can see (which
items are calibration or review samples, which showings are known-answer checks
or shown without a suggestion, in which order) is a keyed hash of the server-side
audit key, which never leaves the database.
"""

import hashlib
import hmac
from collections import defaultdict
from uuid import UUID

from sqlalchemy import and_, exists, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert

from ..scoring import corpus_params, count_first_answers, in_profiling_cohort, readiness
from .common import trust_event
from .models import (Anchor, Annotator, Assignment, Consent, Gold, Item, ItemAudit, ItemState, Judgment,
                     Setting)


def keyed(key_hex: str, message: str) -> int:
    """The first 8 bytes of HMAC-SHA256(audit key, message) as an unsigned integer.
    Migration 003 backfills item bits with the same rule."""
    return int.from_bytes(hmac.new(bytes.fromhex(key_hex), message.encode("utf-8"), hashlib.sha256).digest()[:8], "big")


def item_bits(key_hex, corpus_id, item_id, audit_rate, review_rate):
    """(audit_sample, review_sample, audit_rank) of one item, decided once at import."""
    audit = keyed(key_hex, f"sample:{corpus_id}:{item_id}") % 100 < audit_rate
    review = not audit and keyed(key_hex, f"review:{corpus_id}:{item_id}") % 100 < review_rate
    return audit, review, keyed(key_hex, f"rank:{corpus_id}:{item_id}") - 2 ** 63


async def audit_key(db) -> str:
    return (await db.execute(select(Setting.value).where(Setting.key == "audit_key"))).scalar_one()


# Fields an annotator never needs to answer: provenance for exports, and the sampling
# stratum, which encodes whether the proposed lemmas agree (4.3.3).
STRIPPED = ("sampling_stratum", "word_ref", "other_word_ref", "algorithm_sha256")
# A blind showing has no suggestion; the keys stay, so every response has one shape.
BLINDED = ("proposed_lemma", "other_proposed_lemma")
RESHOW = text("now() - interval '30 minutes'")
SUGGESTED = ("pair", "lemma")  # kinds whose showing can carry a suggestion


def candidate_view(payload, presentation):
    view = {key: value for key, value in payload.items() if key not in STRIPPED}
    if presentation == "blind":
        view.update({key: "" for key in BLINDED})
    return view


def blind_by_rule(key_hex, params, annotator_id, corpus_id, item_id, kind) -> bool:
    """The keyed 20 % of showings without a suggestion, the same for gold and other items."""
    return kind in SUGGESTED and keyed(key_hex, f"blind:{annotator_id}:{corpus_id}:{item_id}") % 100 < params["blind_rate"]


async def gold_pools(db, kind):
    """Live pool counts from the label_gold mirror, in the shape scoring.readiness() takes."""
    pools = {"qualification": {}, "audit": {}, "wrong": 0}
    rows = await db.execute(select(Gold.pool, Gold.answer, Gold.suggestion_agrees, func.count())
                            .where(Gold.kind == kind, Gold.status == "active")
                            .group_by(Gold.pool, Gold.answer, Gold.suggestion_agrees))
    for pool, answer, agrees, n in rows:
        bucket = answer if kind == "stem" else "all"
        pools[pool][bucket] = pools[pool].get(bucket, 0) + n
        if pool == "audit" and agrees is False:
            pools["wrong"] += n
    return pools


async def live_readiness(db, params, kind):
    anchors = (await db.execute(select(func.count()).select_from(Anchor))).scalar_one()
    return readiness(kind, await gold_pools(db, kind), anchors, params)


async def eligible_now(db, annotator_ids):
    """The eligibility predicate on current rows (4.4.2): active status and the profiling cohort."""
    ids = list(annotator_ids)
    if not ids:
        return set()
    active = set((await db.execute(select(Annotator.id).where(Annotator.id.in_(ids),
                                                             Annotator.status == "active"))).scalars())
    rows = defaultdict(list)
    for annotator_id, document, version, age in await db.execute(
            select(Consent.annotator_id, Consent.document, Consent.version, Consent.age_threshold)
            .where(Consent.annotator_id.in_(list(active)))):
        rows[annotator_id].append((document, version, age))
    return {a for a in active if in_profiling_cohort(rows[a])}


async def counted_now(db, params, corpus_id, item_id, epoch, sampled, gold_active, without=None, with_lease=False):
    """{"low": n, "expert": n}: the capped count of admitted first answers in the item's epoch
    from annotators whose votes are eligible now (the same rule a run applies: before any
    reopen the epoch is 0 and holds every answer, those written before 003 with seq NULL
    included). With
    `with_lease`, also other annotators' unanswered showings of the last 30 minutes."""
    firsts = (await db.execute(text("""
        SELECT f.*, a.status, EXISTS (SELECT 1 FROM label_anchor x WHERE x.annotator_id = f.annotator_id) AS anchor,
               (SELECT count(*) FROM label_assignment l WHERE l.corpus_id = :c AND l.item_id = :i
                AND l.annotator_id IS DISTINCT FROM CAST(:w AS uuid) AND l.current_revision = 0
                AND l.last_shown_at > now() - interval '30 minutes') AS lease,
               coalesce((SELECT array_agg(ARRAY[c.document, c.version, c.age_threshold::text])
                         FROM label_consent c WHERE c.annotator_id = f.annotator_id), '{}') AS consents
        FROM (SELECT DISTINCT ON (annotator_id) annotator_id, admitted, admission_group, coalesce(seq, 0) AS seq, id
              FROM label_judgment WHERE corpus_id = :c AND item_id = :i AND (:e = 0 OR coalesce(seq, 0) > :e)
              ORDER BY annotator_id, coalesce(seq, 0), revision, id) f
        RIGHT JOIN (SELECT 1) one ON true
        LEFT JOIN label_annotator a ON a.id = f.annotator_id"""),
        {"c": corpus_id, "i": item_id, "e": epoch, "w": without})).all()
    lease = firsts[0].lease if firsts else 0
    firsts = [r for r in firsts if r.annotator_id is not None]
    firsts = sorted((r for r in firsts if r.annotator_id != without), key=lambda r: (r.seq, str(r.id)))
    eligible = {r.annotator_id for r in firsts if r.status == "active" and in_profiling_cohort(
        (document, version, int(age) if age is not None else None) for document, version, age in r.consents)}
    anchors = {r.annotator_id for r in firsts if r.anchor}
    caps = corpus_params(params, corpus_id)
    used, _ = count_first_answers(
        [(r.annotator_id, True if r.admitted is None else r.admitted, r.admission_group or "low") for r in firsts],
        eligible.__contains__, {"low": caps["votes_low_cap"], "expert": caps["votes_expert_cap"]},
        exempt=lambda a: sampled and a in anchors, uncapped=gold_active)
    return (used, lease) if with_lease else used


def _unseen(caller_id):
    """Join condition and filter: items the caller has not answered and not been shown in 30 minutes."""
    join = and_(Assignment.annotator_id == caller_id, Assignment.corpus_id == Item.corpus_id,
                Assignment.item_id == Item.id)
    unseen = or_(Assignment.annotator_id.is_(None),
                 and_(Assignment.current_revision == 0, Assignment.last_shown_at < RESHOW))
    return join, unseen


class Pick:
    """An item to show, why, and how (shown or blind)."""
    def __init__(self, corpus_id, item_id, presentation=None, qualification=None):
        self.corpus_id, self.item_id = corpus_id, item_id
        self.presentation, self.qualification = presentation, qualification


async def standing(db, annotator_id, kind):
    """(anchor, tier) of an annotator for a kind: the anchor mirror and the latest done run."""
    row = (await db.execute(text("""
        SELECT EXISTS (SELECT 1 FROM label_anchor WHERE annotator_id = :a) AS anchor,
               (SELECT s.tier FROM label_annotator_score s JOIN label_scoring_run r ON r.id = s.run_id
                WHERE s.annotator_id = :a AND s.kind = :k AND r.status = 'done'
                ORDER BY r.finished_at DESC LIMIT 1) AS tier"""), {"a": annotator_id, "k": kind})).one()
    return row.anchor, "anchor" if row.anchor else (row.tier or "new")


async def pick(ctx, db, caller, corpus_ids, kind, expert_work=True):
    """The next item for the caller among corpus_ids (4.9.1), or None."""
    params, key = await ctx.serving_params(db), await ctx.audit_key(db)
    a = caller.id
    anchor, tier = await standing(db, a, kind)
    group = "expert" if tier in ("anchor", "established") else "low"
    ready = await ctx.readiness(db, kind)
    blind_forced = "blind" if kind in SUGGESTED else "shown"
    join, unseen = _unseen(a)

    # 1. Qualification, announced, until the person has the first definite answers on it.
    qualification = None
    if ready["qualification"] and not anchor:
        done = (await db.execute(select(func.count(func.distinct(tuple_(Judgment.corpus_id, Judgment.item_id))))
                                 .select_from(Judgment).join(Gold, (Gold.corpus_id == Judgment.corpus_id)
                                                             & (Gold.item_id == Judgment.item_id))
                                 .where(Judgment.annotator_id == a, Judgment.answer != "unsure", Gold.kind == kind,
                                        Gold.pool == "qualification"))).scalar_one()
        if done < params["qualification_n"]:
            qualification = {"done": done, "of": params["qualification_n"]}
            rows = (await db.execute(select(Gold.corpus_id, Gold.item_id)
                                     .join(Item, (Item.corpus_id == Gold.corpus_id) & (Item.id == Gold.item_id))
                                     .outerjoin(Assignment, join)
                                     .where(Gold.kind == kind, Gold.pool == "qualification", Gold.status == "active",
                                            Gold.corpus_id.in_(corpus_ids), Item.status == "active",
                                            # An unanswered check comes back at once: the knowledge
                                            # check is announced and must be answered to finish.
                                            or_(Assignment.annotator_id.is_(None),
                                                Assignment.current_revision == 0)))).all()
            if rows:
                corpus_id, item_id = min(rows, key=lambda r: keyed(key, f"qual:{a}:{kind}:{r[1]}"))
                return Pick(corpus_id, item_id, blind_forced, qualification)

    # 2. Unannounced known-answer checks at the tier's rate.
    rate = params["gold_rate"].get(tier, 10)
    if ready["audit"] and rate:
        n = (await db.execute(select(func.count()).select_from(Assignment).join(
            Item, (Item.corpus_id == Assignment.corpus_id) & (Item.id == Assignment.item_id))
            .where(Assignment.annotator_id == a, Item.kind == kind, Item.corpus_id.in_(corpus_ids)))).scalar_one()
        if keyed(key, f"audit:{a}:{kind}:{n}") % 100 < rate:
            shown = select(Assignment.item_id).where(Assignment.annotator_id == a, Assignment.corpus_id == Gold.corpus_id,
                                                     Assignment.item_id == Gold.item_id)
            rows = (await db.execute(select(Gold.corpus_id, Gold.item_id, Gold.answer, Gold.suggestion_agrees)
                                     .join(Item, (Item.corpus_id == Gold.corpus_id) & (Item.id == Gold.item_id))
                                     .where(Gold.kind == kind, Gold.pool == "audit", Gold.status == "active",
                                            Gold.corpus_id.in_(corpus_ids), Item.status == "active",
                                            ~exists(shown)))).all()
            sub = keyed(key, f"sub:{a}:{kind}:{n}")
            if kind == "stem":
                wanted = ("accept", "reject")[sub % 2]
                first = [r for r in rows if r.answer == wanted]
            else:
                wrong = sub % 100 < round(params["wrong_suggestion_pick"] * 100)
                first = [r for r in rows if (r.suggestion_agrees is False) == wrong]
            chosen = first or rows
            if chosen:
                row = min(chosen, key=lambda r: keyed(key, f"pick:{a}:{r.item_id}"))
                await _served(db, params, row.corpus_id, row.item_id)
                return Pick(row.corpus_id, row.item_id)

    # 3. The anchors' expert queues (4.16.2), unless they chose to label normally.
    if anchor and expert_work:
        found = await _expert_queues(db, key, params, a, corpus_ids, kind, ready, join, unseen)
        if found is not None:
            return found

    # 4. The normal pick: highest priority first, then spread across annotators.
    # Each state group is read in queue-index order (corpus, kind, state, priority) and stops at
    # 200 servable rows, so the cost does not grow with the corpus; ties within one priority
    # follow the index (import order), and the 200 are then ordered as 4.9.1 says.
    servable = """
          SELECT s.corpus_id, s.item_id, s.priority, s.state, s.epoch FROM label_item_state s
          WHERE s.corpus_id = :corpus AND s.kind = :k AND {state}
            AND (CASE WHEN :group = 'low' THEN s.n_low < :low_cap ELSE s.n_expert < :expert_cap END)
            -- Known-answer items are served only by the keyed audit and qualification picks.
            AND NOT EXISTS (SELECT 1 FROM label_gold g WHERE g.corpus_id = s.corpus_id AND g.item_id = s.item_id
                            AND g.status = 'active')
            AND NOT EXISTS (SELECT 1 FROM label_assignment a
                            WHERE a.annotator_id = :a AND a.corpus_id = s.corpus_id AND a.item_id = s.item_id
                              AND NOT (a.current_revision = 0 AND a.last_shown_at < now() - interval '30 minutes')
                              AND NOT (s.epoch_discard AND a.last_answer_at < s.epoch_at))
          ORDER BY s.priority DESC LIMIT 200"""
    groups = ["s.state = 'open'", "s.state = 'resolved' AND NOT s.releasable",
              "s.state = 'provisional' AND NOT s.releasable"]
    if group == "expert":
        groups.insert(0, "s.state = 'needs_expert'")
    union = " UNION ALL ".join(f"({servable.format(state=state)})" for state in groups)
    candidates = []
    for corpus_id in corpus_ids:
        candidates += (await db.execute(text(f"""
        WITH candidates AS (
          SELECT u.*, i.ordinal, x.audit_sample, x.review_sample,
                 EXISTS (SELECT 1 FROM label_gold g WHERE g.corpus_id = u.corpus_id AND g.item_id = u.item_id
                         AND g.status IN ('active', 'retired')) AS gold
          FROM ({union}) u
          JOIN label_item i ON i.corpus_id = u.corpus_id AND i.id = u.item_id AND i.status = 'active'
          JOIN label_item_audit x ON x.corpus_id = u.corpus_id AND x.item_id = u.item_id
          ORDER BY (u.state = 'needs_expert') DESC, u.priority DESC, i.ordinal
          LIMIT 200
        ), scored AS (
          SELECT c.*, c.priority
                 - 0.2 * (SELECT count(*) FROM label_assignment l
                          WHERE l.corpus_id = c.corpus_id AND l.item_id = c.item_id
                            AND l.current_revision = 0 AND l.last_shown_at > now() - interval '30 minutes') AS effective,
                 md5(CAST(:a AS text) || c.item_id::text) AS spread
          FROM candidates c
        )
        SELECT corpus_id, item_id, epoch, audit_sample, review_sample, gold FROM scored
        ORDER BY (state = 'needs_expert') DESC, effective DESC, spread
        LIMIT 5"""), {"a": a, "corpus": corpus_id, "k": kind, "group": group,
                     "low_cap": params["votes_low_cap"], "expert_cap": params["votes_expert_cap"]})).all()
    for row in candidates:
        caps = corpus_params(params, row.corpus_id)
        cap = caps["votes_expert_cap" if group == "expert" else "votes_low_cap"]
        sampled = row.audit_sample or row.review_sample
        if row.gold or (anchor and sampled):
            return Pick(row.corpus_id, row.item_id)
        used, lease = await counted_now(db, params, row.corpus_id, row.item_id, row.epoch, sampled, False, without=a,
                                        with_lease=True)
        if used[group] + lease < cap:
            return Pick(row.corpus_id, row.item_id)
    return None


async def _served(db, params, corpus_id, item_id):
    """Count a known-answer showing; at gold_max_serves the item retires in the same transaction."""
    count, status = (await db.execute(update(Gold).where(Gold.corpus_id == corpus_id, Gold.item_id == item_id)
                                      .values(served_count=Gold.served_count + 1)
                                      .returning(Gold.served_count, Gold.status))).one()
    if count >= params["gold_max_serves"] and status == "active":
        event_id = await trust_event(db, "gold.retired", corpus_id=corpus_id, item_id=item_id,
                                     details={"reason": "served_out"})
        await db.execute(update(Gold).where(Gold.corpus_id == corpus_id, Gold.item_id == item_id)
                         .values(status="retired", last_event_id=event_id))


async def _expert_queues(db, key, params, a, corpus_ids, kind, ready, join, unseen):
    blind = "blind" if kind in SUGGESTED else "shown"
    base = (select(Item.corpus_id, Item.id).outerjoin(Assignment, join)
            .join(ItemAudit, (ItemAudit.corpus_id == Item.corpus_id) & (ItemAudit.item_id == Item.id))
            .join(ItemState, (ItemState.corpus_id == Item.corpus_id) & (ItemState.item_id == Item.id))
            .where(Item.corpus_id.in_(corpus_ids), Item.kind == kind, Item.status == "active", unseen))
    # (1) needs_expert items.
    row = (await db.execute(base.where(ItemState.state == "needs_expert")
                            .order_by(ItemState.priority.desc(), Item.ordinal).limit(1))).first()
    if row:
        return Pick(row[0], row[1])
    # (2) The seed queue while a pool this work fills is below its target; never calibration items.
    seeding = (not ready["qualification"] or not ready["audit"]) if kind == "stem" else not ready["wrong_suggestion"]
    if seeding:
        no_gold = ~exists(select(Gold.item_id).where(Gold.corpus_id == Item.corpus_id, Gold.item_id == Item.id))
        seed = base.where(no_gold, ~ItemAudit.audit_sample, ~ItemAudit.review_sample)
        if kind in SUGGESTED:
            # Items whose current crowd winner differs from the suggestion first: likeliest suggestion-wrong.
            differs = select(text("1")).select_from(text("label_item_posterior p")).where(text(
                "p.corpus_id = label_item.corpus_id AND p.item_id = label_item.id AND p.cell = 'differs' AND "
                "p.run_id = (SELECT id FROM label_scoring_run WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1)"))
            row = (await db.execute(seed.where(exists(differs)).order_by(Item.ordinal).limit(1))).first()
            if row:
                return Pick(row[0], row[1], blind)
            if kind == "pair":
                seed = seed.where(Item.payload["sampling_stratum"].astext.in_(
                    ("random_different_lemma_suggestion", "stem_collision_different_lemma_suggestion")))
        row = (await db.execute(seed.order_by(func.md5(func.concat(key, ":seed:", Item.corpus_id, ":", Item.id)))
                                .limit(1))).first()
        if row:
            return Pick(row[0], row[1], blind)
    # (3) The audit queue: evaluation-set items still waiting for a reference.
    calibration = (await db.execute(text(
        "SELECT calibration FROM label_scoring_run WHERE status = 'done' ORDER BY finished_at DESC LIMIT 1"))).scalar()
    pending = [tuple(item) for cell in (calibration or {}).values() if cell.get("kind") == kind
               for item in cell.get("pending", ())]
    wanted = {(UUID(c), UUID(i)) for c, i in pending if UUID(c) in set(corpus_ids)}
    if wanted:
        rows = (await db.execute(base.where(tuple_(Item.corpus_id, Item.id).in_(list(wanted)))
                                 .order_by(Item.ordinal).limit(1))).first()
        if rows:
            return Pick(rows[0], rows[1], blind)
    # (4) The review queue: sampled items completed without an anchor vote, oldest first.
    anchor_answered = exists(select(Judgment.id).join(Anchor, Anchor.annotator_id == Judgment.annotator_id).where(
        Judgment.corpus_id == Item.corpus_id, Judgment.item_id == Item.id))
    row = (await db.execute(base.where(ItemAudit.review_sample, ItemState.state.in_(("resolved", "provisional")),
                                       ~anchor_answered).order_by(Item.ordinal).limit(1))).first()
    if row:
        return Pick(row[0], row[1])
    return None


async def show(db, key, params, caller_id, item, presentation=None):
    """Upsert the assignment (the presentation is decided at the first showing) and return it."""
    if presentation is None:
        presentation = "blind" if blind_by_rule(key, params, caller_id, item.corpus_id, item.id, item.kind) else "shown"
    now = func.now()
    return (await db.execute(insert(Assignment).values(
        annotator_id=caller_id, corpus_id=item.corpus_id, item_id=item.id, first_shown_at=now, last_shown_at=now,
        shown_count=1, presentation=presentation).on_conflict_do_update(
        index_elements=[Assignment.annotator_id, Assignment.corpus_id, Assignment.item_id],
        set_={"last_shown_at": now, "shown_count": Assignment.shown_count + 1,
              "presentation": func.coalesce(Assignment.presentation, presentation)})
        .returning(Assignment))).scalar_one()

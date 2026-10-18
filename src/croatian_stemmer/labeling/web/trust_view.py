"""What a person sees of their own trust data (4.10, 4.13.5).

The card (/api/me/trust) is a simplified view: a band and rounded counts, and a
quarantine is silent there (status `active`, the tier their evidence gives). The
self-service export is complete: every retained run's numbers, every flag with its
signal values, every status and trust event about the person. Neither names which
answers were known-answer checks on items still in use.
"""

from sqlalchemy import select, text

from ..scoring import HARD_FLAGS, REPORTED_FLAGS
from .models import AdminEvent, AnnotatorScore, ScoringRun, TrustEvent

BANDS = (("visoka", 0.85), ("dobra", 0.75), ("treba_paznje", 0.0))
MIN_CHECKS = 12  # fewer known-answer checks than this: not enough data for a band

MEANINGS = {
    "tier": ("Razina za vrstu zadatka: new (nova), qualified (prošla provjeru znanja), established (pouzdana), "
             "anchor (stručnjak s popisa pouzdanih adresa), quarantined (odgovori privremeno izdvojeni).",
             "Level for the task kind: new, qualified (passed the knowledge check), established (reliable), "
             "anchor (an expert on the trusted list), quarantined (answers temporarily set aside)."),
    "qualified": ("Jeste li prošli najavljenu provjeru znanja za tu vrstu zadatka.",
                  "Whether you passed the announced knowledge check for the kind."),
    "theta": ("Procijenjena vjerojatnost da je Vaš odgovor točan (0,5 do 1).",
              "Estimated probability that your answer is correct (0.5 to 1)."),
    "weight": ("Koliko se Vaš glas broji u izračunu oznake (0 = ne broji se).",
               "How much your vote counts when a label is computed (0 = it does not count)."),
    "theta_lb_checks": ("Donja granica točnosti procijenjena samo iz provjera s poznatim odgovorom, prikazanih bez "
                        "prijedloga ili s krivim prijedlogom; o njoj ovisi napredovanje.",
                        "Lower bound of accuracy from known-answer checks shown without a suggestion or with a wrong "
                        "one only; promotion depends on it."),
    "known_answer_checks": ("Broj odgovora na primjere s unaprijed poznatim odgovorom i koliko je bilo točno "
                            "(računaju se dan nakon odgovora).",
                            "Answers on items whose answer was known in advance, and how many were right "
                            "(counted from the day after the answer)."),
    "peer_agreement": ("Slaganje s drugima, ponderirano i ograničeno (ne može nadjačati provjere).",
                       "Agreement with others, weighted and capped (it cannot outweigh the checks)."),
    "flags": ("Signali neobičnog ponašanja s vrijednostima: fast (prebrzi odgovori), straight (dug niz istih "
              "odgovora), accuracy (niska točnost na provjerama), copy (prepisivanje prijedloga), review_loss "
              "(neslaganje s provjerom stručnjaka), burst (nagli val odgovora), unsure_heavy, disagree. Dva signala "
              "u istom izračunu automatski izdvajaju odgovore najdulje 14 dana, bez obavijesti na stranici.",
              "Signals of unusual behaviour with their values: fast, straight (long runs of one answer), accuracy "
              "(low on checks), copy (echoing the suggestion), review_loss (losing to an expert's check), burst, "
              "unsure_heavy, disagree. Two signals in one run set the answers aside automatically for at most 14 "
              "days, without a notice on the site."),
    "checked_against_known_answer": ("Odgovor na primjer s poznatim odgovorom koji se više ne koristi za provjere.",
                                     "An answer on a known-answer item that is no longer used for checks."),
}
NOT_INCLUDED = ("Ova datoteka ne navodi koji su Vaši odgovori bili provjere na primjerima koji se još koriste, jer bi "
                "inače otkrila te primjere. Na zahtjev poslan voditelju obrade te primjere povlačimo i šaljemo Vam "
                "rezultat za svaki odgovor u roku od mjesec dana. / This file does not say which of your answers were "
                "checks on items still in use, since that would reveal them. On a request to the controller we retire "
                "those items and send you the result for each answer within one month.")


def band(theta, checks):
    if checks < MIN_CHECKS:
        return "nedovoljno_podataka"
    return next(name for name, floor in BANDS if theta >= floor)


def _checks(row):
    return row.gold_seen + row.flags.get("qualification_done", 0)


async def latest_scores(db, annotator_id):
    """(run, {kind: score row}) of the latest done run that scored the person."""
    run = (await db.execute(select(ScoringRun).where(ScoringRun.status == "done")
                            .order_by(ScoringRun.finished_at.desc()).limit(1))).scalar_one_or_none()
    if run is None:
        return None, {}
    rows = (await db.execute(select(AnnotatorScore).where(AnnotatorScore.run_id == run.id,
                                                          AnnotatorScore.annotator_id == annotator_id))).scalars()
    return run, {row.kind: row for row in rows}


async def block_reason(db, annotator_id, status):
    """The curator's reason, shown only for a block (a quarantine is never shown, 4.8.4)."""
    if status != "blocked":
        return None
    return (await db.execute(select(AdminEvent.details["reason"].astext).where(
        AdminEvent.kind == "annotator.status", AdminEvent.target == str(annotator_id))
        .order_by(AdminEvent.id.desc()).limit(1))).scalar()


def shown_status(status):
    return "active" if status == "quarantined" else status


async def card(db, caller, anchor, language="hr"):
    run, rows = await latest_scores(db, caller.id)
    status = caller.status
    base = {"status": shown_status(status), "status_reason": await block_reason(db, caller.id, status),
            "anchor": anchor, "explanation_url": f"/legal/trust.{language}"}
    if run is None:
        return {"run": None, **base}
    kinds = {}
    for kind, row in sorted(rows.items()):
        checks = _checks(row)
        total = row.n_resolved_total
        kinds[kind] = {"tier": row.base_tier, "qualified": row.qualified, "band": band(row.theta_mean, checks),
                       "checks_approx": checks // 10 * 10,
                       "agreement_approx": round(row.n_resolved_agree / total / 0.05) * 0.05 if total >= 20 else None,
                       "n_definite": row.n_definite, "n_unsure": row.n_unsure}
    return {"run": {"run_at": run.finished_at.isoformat()}, "run_at": run.finished_at.isoformat(), **base,
            "kinds": kinds}


async def export_section(db, annotator_id):
    """The complete trust data of the export (4.13.5)."""
    runs = {}
    rows = (await db.execute(select(AnnotatorScore, ScoringRun).join(ScoringRun, ScoringRun.id == AnnotatorScore.run_id)
                             .where(AnnotatorScore.annotator_id == annotator_id)
                             .order_by(ScoringRun.finished_at, AnnotatorScore.kind))).all()
    for row, run in rows:
        entry = runs.setdefault(str(run.id), {"run_id": str(run.id), "run_at": run.finished_at.isoformat(),
                                              "as_of_day": run.as_of_day.isoformat(), "kinds": {}})
        entry["kinds"][row.kind] = {
            "tier": row.tier, "qualified": row.qualified, "theta": row.theta_mean, "weight": row.weight,
            "theta_lb_checks": row.theta_lb_gold,
            "known_answer_checks": {"total": _checks(row), "unannounced": row.gold_seen,
                                    "unannounced_hits": row.gold_hits,
                                    "discriminating": row.disc_seen, "discriminating_hits": row.disc_hits,
                                    "suggestion_differs": row.wrong_sugg_seen,
                                    "suggestion_differs_hits": row.wrong_sugg_hits},
            "peer_agreement": row.soft_hits, "peer_disagreement": row.soft_misses,
            "flags": {name: row.flags[name] for name in HARD_FLAGS + REPORTED_FLAGS if name in row.flags},
            "n_definite": row.n_definite, "n_unsure": row.n_unsure,
            "resolved_agreement": {"agree": row.n_resolved_agree, "total": row.n_resolved_total}}
    events = []
    for event in (await db.execute(select(AdminEvent).where(
            AdminEvent.kind == "annotator.status", AdminEvent.target == str(annotator_id))
            .order_by(AdminEvent.id))).scalars():
        events.append({"at": event.at.isoformat(), "kind": event.kind, "automatic": event.actor_id is None,
                       "details": {k: v for k, v in event.details.items() if k != "run_id"}})
    for event in (await db.execute(select(TrustEvent).where(
            TrustEvent.annotator_id == annotator_id,
            TrustEvent.kind.in_(("annotator.quarantined", "annotator.cleared", "anchor.granted", "anchor.revoked",
                                 "tier.changed"))).order_by(TrustEvent.id))).scalars():
        details = {k: v for k, v in event.details.items() if k not in ("trusted_id",)}
        events.append({"at": event.at.isoformat(), "kind": event.kind, "automatic": event.actor_id is None,
                       "details": details})
    events.sort(key=lambda e: e["at"])
    return {"runs": list(runs.values()), "events": events,
            "meanings": {key: {"hr": hr, "en": en} for key, (hr, en) in MEANINGS.items()},
            "not_included": NOT_INCLUDED}


async def checked_items(db, annotator_id):
    """Items the person answered whose known answer is no longer in use (retired or retracted)."""
    return {(r[0], r[1]) for r in (await db.execute(text("""
        SELECT DISTINCT j.corpus_id, j.item_id FROM label_judgment j
        JOIN label_gold g ON g.corpus_id = j.corpus_id AND g.item_id = j.item_id
        WHERE j.annotator_id = :a AND g.status IN ('retired', 'retracted')"""), {"a": annotator_id})).all()}

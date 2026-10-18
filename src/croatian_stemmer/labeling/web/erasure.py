"""Erasing a profile: the self-service route and the expiry of never-consented profiles.

The identity goes at once. The answers stay in the dataset under a new random
annotator id that nothing links to the old one: each moved judgment and consent
gets a fresh row id, its time is cut to the (UTC) day and its timing is dropped.
A blocked or set-aside person's answers are deleted instead; they are not counted
now, and moving them would either carry the exclusion over to the new id (a link)
or lift it (erasure as a way out of a block).

The trust system adds (4.13.4): the person's anchor is revoked and a trusted-list
entry for their verified email loses its identity fields; consensus gold they
supported is retracted and its support redacted, so no live row joins the old and
the new identifier; their score rows go from every run; and the details of every
other event about them are reduced to what label_redact_details() keeps.
"""

import hashlib

from sqlalchemy import String, cast, delete, exists, func, insert, or_, select, text, update

from .common import failure, trust_event
from .models import (AdminEvent, Annotator, AnnotatorScore, Assignment, Consent, ErasureRequest, Gold, Judgment,
                     TrustedEmail)

EXCLUDED_STATUSES = ("blocked", "quarantined")
DAY = text("'day'")
UTC = text("'UTC'")


def _day(column):
    return func.date_trunc(DAY, column, UTC)


async def erase_profile(db, person, *, actor_id, details):
    """Erase `person` (an Annotator row locked FOR UPDATE, not yet erased) in the caller's transaction.

    `details` go on the erasure.requested event: only what the curator needs to
    find the sign-in account ({keycloak_user_id}, plus a reason for system
    erasures); they are cleared when the erasure is completed."""
    previous, email = person.status, person.email
    await db.execute(insert(ErasureRequest).values(
        annotator_id=person.id, subject_sha256=hashlib.sha256(person.subject.encode()).hexdigest(),
        requested_at=func.now(), app_erased_at=func.now()))
    db.add(AdminEvent(actor_id=actor_id, kind="erasure.requested", target=str(person.id), details=details))
    await db.execute(update(Annotator).where(Annotator.id == person.id).values(
        subject=None, email=None, email_verified=False, status="erased", erased_at=func.now()))
    await db.execute(delete(Assignment).where(Assignment.annotator_id == person.id))
    await erase_trust(db, person.id, email, actor_id)
    if previous in EXCLUDED_STATUSES:
        await db.execute(delete(Judgment).where(Judgment.annotator_id == person.id))
        await db.execute(delete(Consent).where(Consent.annotator_id == person.id))
        return
    owns = (await db.execute(select(or_(exists().where(Judgment.annotator_id == person.id),
                                        exists().where(Consent.annotator_id == person.id))))).scalar_one()
    if not owns:
        return  # nothing to keep (e.g. a profile that never accepted the gate)
    # The receiving row carries only the day, like the rows it receives.
    today = _day(func.now())
    receiver = (await db.execute(insert(Annotator).values(
        subject=None, email=None, email_verified=False, status="erased",
        created_at=today, last_seen_at=today, erased_at=today).returning(Annotator.id))).scalar_one()
    unsynchronized = {"synchronize_session": False}
    await db.execute(update(Judgment).where(Judgment.annotator_id == person.id).values(
        id=func.gen_random_uuid(), annotator_id=receiver, created_at=_day(Judgment.created_at),
        elapsed_ms=None).execution_options(**unsynchronized))
    await db.execute(update(Consent).where(Consent.annotator_id == person.id).values(
        id=func.nextval(func.pg_get_serial_sequence("label_consent", "id")), annotator_id=receiver,
        accepted_at=_day(Consent.accepted_at)).execution_options(**unsynchronized))


async def erase_trust(db, annotator_id, email, actor_id):
    """The trust system's part of an erasure, in the erasure's (moderation) transaction."""
    from .trusted import email_digest, normalized_email, revoke_anchors
    await revoke_anchors(db, None, "erasure", actor_id=actor_id, annotator_id=annotator_id)
    normalized = normalized_email(email) if email else None
    if normalized:
        entry = (await db.execute(select(TrustedEmail).where(TrustedEmail.email_sha256 == email_digest(normalized),
                                                             TrustedEmail.removed_at.is_(None)).with_for_update())).scalar_one_or_none()
        if entry is not None:
            entry.removed_at, entry.email, entry.email_sha256, entry.label = func.now(), None, None, None
            await trust_event(db, "trusted.removed", actor_id=actor_id, details={"trusted_id": entry.id, "reason": "erasure"})
            await revoke_anchors(db, entry.id, "erasure", actor_id=actor_id)
    # Consensus gold the person supported: no longer certified by anyone, and its support
    # (annotator and judgment ids) goes, since the judgments now live under the new id.
    supported = (await db.execute(text(
        "SELECT id, corpus_id, item_id FROM label_trust_event WHERE kind = 'gold.set' "
        "AND details -> 'support' -> 'annotators' ? :a"), {"a": str(annotator_id)})).all()
    for event_id, corpus_id, item_id in supported:
        await db.execute(text("UPDATE label_trust_event SET details = jsonb_set(details, '{support}', "
                              "'{\"redacted\": true}'::jsonb) WHERE id = :i"), {"i": event_id})
        status = (await db.execute(select(Gold.status).where(Gold.corpus_id == corpus_id, Gold.item_id == item_id)
                                   .with_for_update())).scalar_one_or_none()
        if status in ("active", "retired"):
            retracted = await trust_event(db, "gold.retracted", actor_id=actor_id, corpus_id=corpus_id, item_id=item_id,
                                          details={"reason": "erasure"})
            await db.execute(update(Gold).where(Gold.corpus_id == corpus_id, Gold.item_id == item_id)
                             .values(status="retracted", last_event_id=retracted))
    await db.execute(delete(AnnotatorScore).where(AnnotatorScore.annotator_id == annotator_id))
    # Reasons, flags and signal values go from every other event about the person.
    await db.execute(text("UPDATE label_trust_event SET details = label_redact_details(kind, details) "
                          "WHERE annotator_id = :a AND details <> label_redact_details(kind, details)"),
                     {"a": annotator_id})
    await db.execute(text("UPDATE label_admin_event SET details = label_redact_details(kind, details) "
                          "WHERE target = :a AND kind <> 'erasure.requested' "
                          "AND details <> label_redact_details(kind, details)"), {"a": str(annotator_id)})


async def pending_erasure(db, subject):
    """The 409 for a sign-in account whose erasure awaits Keycloak deletion, else None.

    `reason` (when set, e.g. unconsented_expiry) lets the UI word the notice."""
    digest = hashlib.sha256(subject.encode()).hexdigest()
    row = (await db.execute(
        select(ErasureRequest.id, AdminEvent.details["reason"].astext)
        .outerjoin(AdminEvent, (AdminEvent.kind == "erasure.requested")
                   & (AdminEvent.target == cast(ErasureRequest.annotator_id, String)))
        .where(ErasureRequest.subject_sha256 == digest, ErasureRequest.keycloak_deleted_at.is_(None))
        .order_by(ErasureRequest.id.desc()).limit(1))).first()
    if row is None:
        return None
    return failure(409, "erasure_pending", **({"reason": row[1]} if row[1] else {}))


async def still_present(db, caller):
    """Share-lock the caller's row for this transaction; 409 if it was erased since the
    request was authenticated, so nothing is written to an erased profile."""
    status = (await db.execute(select(Annotator.status).where(Annotator.id == caller.id)
                               .with_for_update(read=True))).scalar_one_or_none()
    if status in (None, "erased"):
        raise failure(409, "erasure_pending")

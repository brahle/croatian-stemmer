"""Erasing a profile: the self-service route and the expiry of never-consented profiles.

The identity goes at once. The answers stay in the dataset under a new random
annotator id that nothing links to the old one: each moved judgment and consent
gets a fresh row id, its time is cut to the (UTC) day and its timing is dropped.
A blocked or set-aside person's answers are deleted instead; they are not counted
now, and moving them would either carry the exclusion over to the new id (a link)
or lift it (erasure as a way out of a block).
"""

import hashlib

from sqlalchemy import String, cast, delete, exists, func, insert, or_, select, text, update

from .common import failure
from .models import AdminEvent, Annotator, Assignment, Consent, ErasureRequest, Judgment

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
    previous = person.status
    await db.execute(insert(ErasureRequest).values(
        annotator_id=person.id, subject_sha256=hashlib.sha256(person.subject.encode()).hexdigest(),
        requested_at=func.now(), app_erased_at=func.now()))
    db.add(AdminEvent(actor_id=actor_id, kind="erasure.requested", target=str(person.id), details=details))
    await db.execute(update(Annotator).where(Annotator.id == person.id).values(
        subject=None, email=None, email_verified=False, status="erased", erased_at=func.now()))
    await db.execute(delete(Assignment).where(Assignment.annotator_id == person.id))
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

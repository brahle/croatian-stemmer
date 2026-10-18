"""The trusted list and anchors (4.7): identity stays in one erasable table; the journal
only ever sees `trusted_id`.

A person becomes an anchor when they sign in with a verified email that matches an
active entry (on profile creation and on the 10-minute refresh), or at once when the
curator adds an address someone already signed in with. Removing the entry, or the
person's erasure, revokes the anchor; runs read anchors from the events, so a
revocation is retroactive at the next run.
"""

import hashlib
import unicodedata

from sqlalchemy import delete, select

from .common import trust_event
from .config import EMAIL
from .models import Anchor, Annotator, TrustedEmail
from .scoring_run import moderation_tx


def normalized_email(value: str) -> str | None:
    email = unicodedata.normalize("NFC", value.strip()).lower()
    return email if len(email) <= 320 and EMAIL.match(email) else None


def email_digest(email: str) -> str:
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


async def grant_anchor(db, annotator_id, trusted_id):
    """In a moderation transaction, with the annotator row locked."""
    if (await db.execute(select(Anchor.annotator_id).where(Anchor.annotator_id == annotator_id))).first():
        return False
    event_id = await trust_event(db, "anchor.granted", annotator_id=annotator_id, details={"trusted_id": trusted_id})
    db.add(Anchor(annotator_id=annotator_id, trusted_id=trusted_id, granted_event_id=event_id))
    await db.flush()
    return True


async def revoke_anchors(db, trusted_id, reason, actor_id=None, annotator_id=None):
    """Revoke the anchor that holds `trusted_id` (or `annotator_id`'s anchor)."""
    query = select(Anchor)
    query = query.where(Anchor.annotator_id == annotator_id) if annotator_id else query.where(Anchor.trusted_id == trusted_id)
    for anchor in (await db.execute(query)).scalars().all():
        await db.execute(delete(Anchor).where(Anchor.annotator_id == anchor.annotator_id))
        await trust_event(db, "anchor.revoked", actor_id=actor_id, annotator_id=anchor.annotator_id,
                          details={"trusted_id": anchor.trusted_id, "reason": reason})


async def trusted_match(db, principal):
    """The active trusted entry for the caller's verified email, or None."""
    if not principal.email or not principal.email_verified:
        return None
    email = normalized_email(principal.email)
    if email is None:
        return None
    return (await db.execute(select(TrustedEmail.id).where(TrustedEmail.email_sha256 == email_digest(email),
                                                           TrustedEmail.removed_at.is_(None)))).scalar_one_or_none()


async def match_anchor(sessions, annotator_id, principal):
    """Grant the anchor if the caller's verified email is on the list and they are not one yet.
    Like the profile refresh, it acts only on a row that still belongs to this subject and is
    not erased."""
    async with sessions() as db:
        async with db.begin():
            if await trusted_match(db, principal) is None:
                return False
        async with db.begin():
            await moderation_tx(db)
            trusted_id = await trusted_match(db, principal)
            person = (await db.execute(select(Annotator.id).where(
                Annotator.id == annotator_id, Annotator.subject == principal.subject, Annotator.status != "erased")
                .with_for_update())).scalar_one_or_none()
            if trusted_id is None or person is None:
                return False
            return await grant_anchor(db, annotator_id, trusted_id)

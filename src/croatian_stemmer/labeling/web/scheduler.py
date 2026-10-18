"""What an annotator is shown next, and the keyed rules behind it.

Every rule that must not be predictable from anything a person can see (which
items are calibration or review samples, which showings are known-answer checks
or shown without a suggestion, in which order) is a keyed hash of the server-side
audit key, which never leaves the database.
"""

import hashlib
import hmac

from sqlalchemy import select

from .models import Setting


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

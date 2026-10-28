from datetime import datetime
from typing import Any

from google.cloud import firestore

from app.config import (
    CONTACTS_COLLECTION,
    EXTERNAL_CALL_TIMEOUT_SECONDS,
    RATE_LIMITS_COLLECTION,
    RateLimits,
)
from app.models.contact import ContactRequest
from app.services.rate_limit import (
    Counter,
    ExceededCounterCache,
    RateLimitExceeded,
    build_counters,
    check_counters,
)

# Contention is unlikely at this traffic level; keep retries (and their reads) low.
TRANSACTION_MAX_ATTEMPTS = 3


def contact_document(contact: ContactRequest, now: datetime) -> dict[str, Any]:
    # Only what the site owner needs; the client IP is not stored with the inquiry.
    return {
        "name": contact.name,
        "email": contact.email,
        "message": contact.message,
        "created_at": now,
        "status": "unread",
    }


class FirestoreContactStore:
    def __init__(self, client: firestore.Client, limits: RateLimits) -> None:
        self._client = client
        self._limits = limits
        self._exceeded = ExceededCounterCache()

    def save(self, contact: ContactRequest, ip_hash: str, now: datetime) -> str:
        """Check and increment the rate-limit counters and save the inquiry atomically.

        Raises RateLimitExceeded without writing anything when a limit is reached, and
        without reading anything when the limit was already reached in this window.
        """
        counters = build_counters(ip_hash, now, self._limits)
        self._exceeded.check(counters, now)
        counter_refs = [
            self._client.collection(RATE_LIMITS_COLLECTION).document(c.doc_id) for c in counters
        ]
        contact_ref = self._client.collection(CONTACTS_COLLECTION).document()

        transactional = firestore.transactional(write_contact)
        try:
            transactional(
                self._client.transaction(max_attempts=TRANSACTION_MAX_ATTEMPTS),
                counter_refs,
                counters,
                contact_ref,
                contact_document(contact, now),
                now,
            )
        except RateLimitExceeded as exc:
            self._exceeded.add([c for c in counters if c.scope in exc.scopes], now)
            raise
        return contact_ref.id


def write_contact(
    transaction: firestore.Transaction,
    counter_refs: list[firestore.DocumentReference],
    counters: list[Counter],
    contact_ref: firestore.DocumentReference,
    contact_data: dict[str, Any],
    now: datetime,
) -> None:
    """Transaction body: 3 reads, and 4 writes only when no limit is exceeded."""
    snapshots = {
        snapshot.id: snapshot
        for snapshot in transaction.get_all(counter_refs, timeout=EXTERNAL_CALL_TIMEOUT_SECONDS)
    }
    counts = [_count(snapshots[c.doc_id]) if c.doc_id in snapshots else 0 for c in counters]
    check_counters(counters, counts, now)
    for ref, counter, count in zip(counter_refs, counters, counts, strict=True):
        # expire_at is the TTL field of the rate-limit collection.
        transaction.set(ref, {"count": count + 1, "expire_at": counter.expires_at})
    transaction.set(contact_ref, contact_data)


def _count(snapshot: firestore.DocumentSnapshot) -> int:
    if not snapshot.exists:
        return 0
    value = (snapshot.to_dict() or {}).get("count", 0)
    return value if isinstance(value, int) else 0

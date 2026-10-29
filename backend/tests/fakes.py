"""In-memory stand-ins for Firestore and Gmail used by the tests."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.config import CONTACTS_COLLECTION, RATE_LIMITS_COLLECTION, RateLimits
from app.models.contact import ContactRequest
from app.services.contact_store import contact_document, write_contact
from app.services.rate_limit import ExceededCounterCache, RateLimitExceeded, build_counters

Documents = dict[tuple[str, str], dict[str, Any]]


@dataclass(frozen=True)
class FakeRef:
    collection: str
    id: str


@dataclass
class FakeSnapshot:
    id: str
    data: dict[str, Any] | None

    @property
    def exists(self) -> bool:
        return self.data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return self.data


class FakeTransaction:
    """Buffers writes until commit(), like a Firestore transaction."""

    def __init__(self, docs: Documents) -> None:
        self._docs = docs
        self._writes: list[tuple[FakeRef, dict[str, Any]]] = []
        self.read_count = 0

    def get_all(self, refs: list[FakeRef], timeout: float) -> list[FakeSnapshot]:
        self.read_count += len(refs)
        return [FakeSnapshot(r.id, self._docs.get((r.collection, r.id))) for r in refs]

    def set(self, ref: FakeRef, data: dict[str, Any]) -> None:
        self._writes.append((ref, data))

    def commit(self) -> None:
        for ref, data in self._writes:
            self._docs[(ref.collection, ref.id)] = data

    @property
    def write_count(self) -> int:
        return len(self._writes)


class InMemoryContactStore:
    """Same flow as FirestoreContactStore.save, backed by a dict."""

    def __init__(self, limits: RateLimits | None = None) -> None:
        self.docs: Documents = {}
        self.limits = limits or RateLimits()
        self.error: Exception | None = None
        self.exceeded = ExceededCounterCache()
        self.read_count = 0

    def save(self, contact: ContactRequest, ip_hash: str, now: datetime) -> str:
        if self.error is not None:
            raise self.error
        counters = build_counters(ip_hash, now, self.limits)
        self.exceeded.check(counters, now)
        refs = [FakeRef(RATE_LIMITS_COLLECTION, c.doc_id) for c in counters]
        contact_ref = FakeRef(CONTACTS_COLLECTION, f"contact-{len(self.contacts()) + 1}")
        transaction = FakeTransaction(self.docs)
        try:
            write_contact(
                transaction, refs, counters, contact_ref, contact_document(contact, now), now
            )
        except RateLimitExceeded as exc:
            self.exceeded.add([c for c in counters if c.scope in exc.scopes], now)
            raise
        finally:
            self.read_count += transaction.read_count
        transaction.commit()
        return contact_ref.id

    def contacts(self) -> dict[str, dict[str, Any]]:
        return {doc_id: d for (c, doc_id), d in self.docs.items() if c == CONTACTS_COLLECTION}

    def rate_limit_docs(self) -> dict[str, dict[str, Any]]:
        return {doc_id: d for (c, doc_id), d in self.docs.items() if c == RATE_LIMITS_COLLECTION}


@dataclass
class FakeNotifier:
    sent: list[tuple[str, ContactRequest]] = field(default_factory=list)
    error: Exception | None = None

    def notify(self, contact_id: str, contact: ContactRequest) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((contact_id, contact))


@dataclass
class FakeClock:
    now: datetime = field(default_factory=lambda: datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC))

    def __call__(self) -> datetime:
        return self.now

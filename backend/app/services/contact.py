import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from app.config import load_contact_settings
from app.models.contact import ContactRequest
from app.services.rate_limit import hash_client_ip

logger = logging.getLogger(__name__)

# After a failed build (e.g. a wrong secret name), wait this long before trying again so
# that every request does not repeat the Secret Manager calls.
BUILD_RETRY_INTERVAL_SECONDS = 60.0


class ContactServiceUnavailable(Exception):
    """The service could not be built recently; the build is not retried yet."""


class ContactStore(Protocol):
    def save(self, contact: ContactRequest, ip_hash: str, now: datetime) -> str:
        """Save the inquiry and return its ID. Raises RateLimitExceeded."""
        ...


class Notifier(Protocol):
    def notify(self, contact_id: str, contact: ContactRequest) -> None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class ContactService:
    store: ContactStore
    notifier: Notifier
    ip_hash_key: bytes
    trust_x_forwarded_for: bool
    clock: Callable[[], datetime] = field(default=_utc_now)

    def submit(self, contact: ContactRequest, client_ip: str) -> str:
        contact_id = self.store.save(
            contact, hash_client_ip(client_ip, self.ip_hash_key), self.clock()
        )
        try:
            self.notifier.notify(contact_id, contact)
        except Exception:
            # The inquiry is already saved, so the request still succeeds. Retrying would
            # only create a duplicate; the owner can find it in Firestore by this ID.
            logger.exception(json.dumps({"event": "contact_notification_failed", "id": contact_id}))
        return contact_id


def build_contact_service() -> ContactService:
    """Create the production service from environment variables.

    Google Cloud client libraries are imported here, not at startup, so that page views
    (which never use them) do not pay for loading them on a cold start.
    """
    from google.cloud import firestore

    from app.services.contact_store import FirestoreContactStore
    from app.services.gmail import GmailNotifier, create_gmail_session
    from app.services.secrets import resolve_secret

    settings = load_contact_settings()
    session = create_gmail_session(
        client_id=settings.gmail_client_id,
        client_secret=resolve_secret(settings.gmail_client_secret),
        refresh_token=resolve_secret(settings.gmail_refresh_token),
    )
    return ContactService(
        store=FirestoreContactStore(firestore.Client(), settings.rate_limits),
        notifier=GmailNotifier(session, settings.notify_to),
        ip_hash_key=resolve_secret(settings.ip_hash_key).encode(),
        trust_x_forwarded_for=settings.trust_x_forwarded_for,
    )


class ContactServiceProvider:
    """Builds the service on first use and reuses it.

    A failed build is retried at most once per BUILD_RETRY_INTERVAL_SECONDS; in between,
    get() raises ContactServiceUnavailable without calling any external service.
    """

    def __init__(
        self,
        build: Callable[[], ContactService] = build_contact_service,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._build = build
        self._monotonic = monotonic
        self._service: ContactService | None = None
        self._failed_at: float | None = None
        self._lock = threading.Lock()

    def get(self) -> ContactService:
        with self._lock:
            if self._service is None:
                if (
                    self._failed_at is not None
                    and self._monotonic() - self._failed_at < BUILD_RETRY_INTERVAL_SECONDS
                ):
                    raise ContactServiceUnavailable()
                try:
                    self._service = self._build()
                except Exception:
                    self._failed_at = self._monotonic()
                    raise
            return self._service

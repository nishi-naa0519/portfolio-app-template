import json
import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import RateLimits
from app.main import create_app
from app.models.contact import EMAIL_MAX_LENGTH, MESSAGE_MAX_LENGTH, NAME_MAX_LENGTH
from app.services.contact import ContactService, ContactServiceProvider
from tests.fakes import FakeClock, FakeNotifier, InMemoryContactStore

VALID_PAYLOAD = {
    "name": "Example User",
    "email": "user@example.com",
    "message": "Hello",
}
OWNER_EMAIL = "owner@example.com"
RATE_LIMITED = {"detail": "Too many requests. Please try again later."}
UNAVAILABLE = {"detail": "The contact form is temporarily unavailable. Please try again later."}


@dataclass
class Context:
    client: TestClient
    store: InMemoryContactStore
    notifier: FakeNotifier
    clock: FakeClock
    service: ContactService


def make_context(trust_x_forwarded_for: bool = False, limits: RateLimits | None = None) -> Context:
    store = InMemoryContactStore(limits)
    notifier = FakeNotifier()
    clock = FakeClock()
    service = ContactService(
        store=store,
        notifier=notifier,
        ip_hash_key=b"test-key",
        trust_x_forwarded_for=trust_x_forwarded_for,
        clock=clock,
    )
    client = TestClient(
        create_app(contact_service_provider=ContactServiceProvider(lambda: service))
    )
    return Context(client, store, notifier, clock, service)


@pytest.fixture
def ctx() -> Context:
    return make_context()


def contact_logs(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [
        json.loads(r.getMessage())
        for r in caplog.records
        if r.name in ("app.api.contact", "app.services.contact")
    ]


def post(ctx: Context, payload: dict[str, Any] | None = None, **kwargs: Any) -> Any:
    return ctx.client.post("/api/contact", json=payload or VALID_PAYLOAD, **kwargs)


def test_valid_contact_is_saved_and_notified(
    ctx: Context, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)

    response = post(ctx)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert ctx.store.contacts() == {
        "contact-1": {**VALID_PAYLOAD, "created_at": ctx.clock.now, "status": "unread"}
    }
    assert [(cid, c.model_dump()) for cid, c in ctx.notifier.sent] == [
        ("contact-1", {**VALID_PAYLOAD, "website": ""})
    ]
    assert contact_logs(caplog) == [{"event": "contact_saved", "id": "contact-1"}]


def test_inquiry_content_is_not_logged(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    post(ctx)

    for value in VALID_PAYLOAD.values():
        assert value not in caplog.text


def test_fields_are_stripped_and_max_lengths_are_allowed(ctx: Context) -> None:
    payload = {
        "name": "  " + "a" * NAME_MAX_LENGTH + "  ",
        "email": "a" * 64 + "@" + "b" * 63 + ".example.com",
        "message": "m" * MESSAGE_MAX_LENGTH,
    }

    response = post(ctx, payload)

    assert response.status_code == 202
    assert ctx.store.contacts()["contact-1"]["name"] == "a" * NAME_MAX_LENGTH


def test_honeypot_returns_accepted_without_saving_or_notifying(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)

    def build() -> ContactService:
        raise AssertionError("the service must not be used for honeypot submissions")

    client = TestClient(create_app(contact_service_provider=ContactServiceProvider(build)))

    response = client.post("/api/contact", json={**VALID_PAYLOAD, "website": "http://spam"})

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert contact_logs(caplog) == [{"event": "contact_honeypot_triggered"}]


@pytest.mark.parametrize(
    "override",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "a" * (NAME_MAX_LENGTH + 1)},
        {"email": "not-an-email"},
        {"email": "user@"},
        {"email": "a" * EMAIL_MAX_LENGTH + "@example.com"},
        {"message": ""},
        {"message": "m" * (MESSAGE_MAX_LENGTH + 1)},
        {"name": 123},
        {"website": "x" * 201},
        {"unexpected": "field"},
    ],
)
def test_invalid_fields_are_rejected(ctx: Context, override: dict[str, Any]) -> None:
    response = post(ctx, {**VALID_PAYLOAD, **override})

    assert response.status_code == 422
    assert ctx.store.docs == {}
    assert ctx.notifier.sent == []


@pytest.mark.parametrize("missing", ["name", "email", "message"])
def test_missing_required_field_is_rejected(ctx: Context, missing: str) -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing}

    assert post(ctx, payload).status_code == 422


def test_malformed_json_is_rejected(ctx: Context) -> None:
    response = ctx.client.post(
        "/api/contact", content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_get_is_not_allowed(ctx: Context) -> None:
    assert ctx.client.get("/api/contact").status_code == 405


def test_ip_hourly_limit_returns_429(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ctx.clock.now = ctx.clock.now.replace(minute=59, second=30)

    for _ in range(3):
        assert post(ctx).status_code == 202
    response = post(ctx)

    assert response.status_code == 429
    assert response.json() == RATE_LIMITED
    assert response.headers["Retry-After"] == "30"
    assert len(ctx.store.contacts()) == 3
    assert len(ctx.notifier.sent) == 3
    assert contact_logs(caplog)[-1] == {"event": "contact_rate_limited", "scopes": ["ip_hour"]}


def test_ip_hourly_limit_resets_in_the_next_hour(ctx: Context) -> None:
    for _ in range(3):
        post(ctx)
    ctx.clock.now += timedelta(hours=1)

    assert post(ctx).status_code == 202


def test_ip_daily_limit_returns_429(ctx: Context, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ctx.clock.now = ctx.clock.now.replace(hour=22)
    for _ in range(3):
        assert post(ctx).status_code == 202
    ctx.clock.now += timedelta(hours=1)
    for _ in range(2):
        assert post(ctx).status_code == 202

    response = post(ctx)

    assert response.status_code == 429
    assert contact_logs(caplog)[-1] == {"event": "contact_rate_limited", "scopes": ["ip_day"]}
    # The daily window ends at 00:00 UTC.
    midnight = (ctx.clock.now + timedelta(days=1)).replace(hour=0, minute=0, second=0)
    assert response.headers["Retry-After"] == str(int((midnight - ctx.clock.now).total_seconds()))

    ctx.clock.now = midnight
    assert post(ctx).status_code == 202


def test_site_wide_daily_limit_returns_429(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    ctx = make_context(trust_x_forwarded_for=True, limits=RateLimits(site_per_day=4))

    for i in range(4):
        assert post(ctx, headers={"X-Forwarded-For": f"192.0.2.{i}"}).status_code == 202
    response = post(ctx, headers={"X-Forwarded-For": "192.0.2.99"})

    assert response.status_code == 429
    assert response.json() == RATE_LIMITED
    assert contact_logs(caplog)[-1] == {"event": "contact_rate_limited", "scopes": ["site_day"]}
    assert len(ctx.notifier.sent) == 4


def test_rejected_requests_do_not_count_or_write(ctx: Context) -> None:
    for _ in range(3):
        post(ctx)
    before = {k: dict(v) for k, v in ctx.store.docs.items()}

    for _ in range(5):
        assert post(ctx).status_code == 429

    assert ctx.store.docs == before


def test_rate_limit_documents_expire_and_do_not_store_raw_ip() -> None:
    ctx = make_context(trust_x_forwarded_for=True)

    post(ctx, headers={"X-Forwarded-For": "198.51.100.7"})

    docs = ctx.store.rate_limit_docs()
    assert len(docs) == 3
    for doc_id, doc in docs.items():
        assert "198.51.100.7" not in doc_id
        assert set(doc) == {"count", "expire_at"}
        assert doc["expire_at"] > ctx.clock.now
        assert doc["expire_at"] - ctx.clock.now <= timedelta(days=1)


def test_last_x_forwarded_for_entry_is_used_on_trusted_proxy() -> None:
    ctx = make_context(trust_x_forwarded_for=True)

    # The client controls everything before the last entry, so changing it must not help.
    for i in range(3):
        headers = {"X-Forwarded-For": f"10.0.0.{i}, 203.0.113.5"}
        assert post(ctx, headers=headers).status_code == 202
    blocked = post(ctx, headers={"X-Forwarded-For": "10.0.0.9, 203.0.113.5"})
    other_client = post(ctx, headers={"X-Forwarded-For": "203.0.113.6"})

    assert blocked.status_code == 429
    assert other_client.status_code == 202


def test_x_forwarded_for_is_ignored_unless_trusted(ctx: Context) -> None:
    for i in range(3):
        assert post(ctx, headers={"X-Forwarded-For": f"203.0.113.{i}"}).status_code == 202

    assert post(ctx, headers={"X-Forwarded-For": "203.0.113.99"}).status_code == 429


def test_store_failure_returns_503_without_details(
    ctx: Context, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ctx.store.error = RuntimeError("firestore internal error: projects/secret-project")

    response = post(ctx)

    assert response.status_code == 503
    assert response.json() == UNAVAILABLE
    assert "secret-project" not in response.text
    assert ctx.notifier.sent == []
    assert contact_logs(caplog) == [{"event": "contact_failed"}]


def test_configuration_failure_returns_503_and_is_retried() -> None:
    attempts: list[int] = []

    def build() -> ContactService:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("GMAIL_REFRESH_TOKEN is not set")
        return make_context().service

    client = TestClient(create_app(contact_service_provider=ContactServiceProvider(build)))

    first = client.post("/api/contact", json=VALID_PAYLOAD)
    second = client.post("/api/contact", json=VALID_PAYLOAD)

    assert first.status_code == 503
    assert first.json() == UNAVAILABLE
    assert "GMAIL" not in first.text
    assert second.status_code == 202
    assert len(attempts) == 2


def test_notification_failure_still_accepts_saved_inquiry(
    ctx: Context, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO)
    ctx.notifier.error = RuntimeError("Gmail API returned HTTP 500")

    response = post(ctx)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert list(ctx.store.contacts()) == ["contact-1"]
    assert contact_logs(caplog) == [
        {"event": "contact_notification_failed", "id": "contact-1"},
        {"event": "contact_saved", "id": "contact-1"},
    ]


def test_owner_email_is_never_returned(ctx: Context) -> None:
    # The fake notifier does not know the owner address, but responses for every outcome
    # are checked so that a future change cannot start echoing it back.
    responses = [post(ctx) for _ in range(4)]
    ctx.store.error = RuntimeError(OWNER_EMAIL)
    responses.append(post(ctx))

    assert [r.status_code for r in responses] == [202, 202, 202, 429, 503]
    for response in responses:
        assert OWNER_EMAIL not in response.text
        assert set(response.json()) <= {"status", "detail"}

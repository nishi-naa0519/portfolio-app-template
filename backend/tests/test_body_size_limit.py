from collections.abc import Iterator

from fastapi.testclient import TestClient

from app.body_size_limit import MAX_REQUEST_BODY_BYTES
from app.main import create_app
from app.models.contact import (
    EMAIL_MAX_LENGTH,
    HONEYPOT_MAX_LENGTH,
    MESSAGE_MAX_LENGTH,
    NAME_MAX_LENGTH,
)
from app.services.contact import ContactService, ContactServiceProvider

TOO_LARGE = {"detail": "Request body is too large."}


def make_client() -> TestClient:
    def build() -> ContactService:
        raise AssertionError("oversized requests must not reach the contact service")

    return TestClient(create_app(contact_service_provider=ContactServiceProvider(build)))


def test_body_over_the_content_length_limit_returns_413() -> None:
    body = b'{"message": "' + b"m" * MAX_REQUEST_BODY_BYTES + b'"}'

    response = make_client().post(
        "/api/contact", content=body, headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json() == TOO_LARGE


def test_chunked_body_over_the_limit_returns_413() -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"message": "'
        for _ in range(MAX_REQUEST_BODY_BYTES // 1024 + 1):
            yield b"m" * 1024
        yield b'"}'

    # A generator body is sent with Transfer-Encoding: chunked and no Content-Length.
    response = make_client().post(
        "/api/contact", content=chunks(), headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 413
    assert response.json() == TOO_LARGE


def test_largest_valid_contact_fits_within_the_limit() -> None:
    # 4-byte UTF-8 characters are the worst case for an unescaped JSON body.
    emoji = "\U0001f600"
    payload = {
        "name": emoji * NAME_MAX_LENGTH,
        "email": "a" * (EMAIL_MAX_LENGTH - len("@example.com")) + "@example.com",
        "message": emoji * MESSAGE_MAX_LENGTH,
        # The honeypot keeps the request away from the contact service.
        "website": emoji * HONEYPOT_MAX_LENGTH,
    }

    response = make_client().post("/api/contact", json=payload)

    assert response.status_code == 202

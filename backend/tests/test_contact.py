import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models.contact import EMAIL_MAX_LENGTH, MESSAGE_MAX_LENGTH, NAME_MAX_LENGTH

VALID_PAYLOAD = {
    "name": "Example User",
    "email": "user@example.com",
    "message": "Hello",
}


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def contact_logs(caplog: pytest.LogCaptureFixture) -> list[dict[str, Any]]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == "app.api.contact"]


def test_valid_contact_is_accepted_and_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.api.contact")

    response = client.post("/api/contact", json=VALID_PAYLOAD)

    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert contact_logs(caplog) == [{"event": "contact_received", **VALID_PAYLOAD}]


def test_fields_are_stripped_and_max_lengths_are_allowed(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.api.contact")
    payload = {
        "name": "  " + "a" * NAME_MAX_LENGTH + "  ",
        "email": "a" * 64 + "@" + "b" * 63 + ".example.com",
        "message": "m" * MESSAGE_MAX_LENGTH,
    }

    response = client.post("/api/contact", json=payload)

    assert response.status_code == 202
    assert contact_logs(caplog)[0]["name"] == "a" * NAME_MAX_LENGTH


def test_honeypot_returns_accepted_without_logging_content(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.api.contact")

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
def test_invalid_fields_are_rejected(
    client: TestClient, caplog: pytest.LogCaptureFixture, override: dict[str, Any]
) -> None:
    caplog.set_level(logging.INFO, logger="app.api.contact")

    response = client.post("/api/contact", json={**VALID_PAYLOAD, **override})

    assert response.status_code == 422
    assert contact_logs(caplog) == []


@pytest.mark.parametrize("missing", ["name", "email", "message"])
def test_missing_required_field_is_rejected(client: TestClient, missing: str) -> None:
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != missing}

    response = client.post("/api/contact", json=payload)

    assert response.status_code == 422


def test_malformed_json_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/contact", content="{not json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 422


def test_get_is_not_allowed(client: TestClient) -> None:
    assert client.get("/api/contact").status_code == 405

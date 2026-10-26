import base64
import email
from dataclasses import dataclass, field
from email import policy
from typing import Any

import pytest

from app.models.contact import ContactRequest
from app.services.gmail import GMAIL_SEND_URL, GmailNotifier, GmailSendError, build_notification

CONTACT = ContactRequest(name="山田 太郎", email="user@example.com", message="こんにちは\n2行目")


@dataclass
class FakeResponse:
    status_code: int


@dataclass
class FakeSession:
    status_code: int = 200
    calls: list[dict[str, Any]] = field(default_factory=list)

    def post(self, url: str, *, json: Any, timeout: float) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse(self.status_code)


def test_notification_contains_the_inquiry_and_replies_to_the_sender() -> None:
    message = build_notification("abc123", CONTACT, "owner@example.com")

    assert message["To"] == "owner@example.com"
    assert message["Reply-To"] == "user@example.com"
    assert message["From"] is None
    assert message["Subject"] == "[Portfolio] New inquiry (abc123)"
    body = message.get_content()
    assert "ID: abc123" in body
    assert "Name: 山田 太郎" in body
    assert "Email: user@example.com" in body
    assert "こんにちは\n2行目" in body


def test_notify_sends_a_raw_message_to_the_gmail_api() -> None:
    session = FakeSession()

    GmailNotifier(session, "owner@example.com").notify("abc123", CONTACT)

    [call] = session.calls
    assert call["url"] == GMAIL_SEND_URL
    assert 0 < call["timeout"] <= 10
    raw = base64.urlsafe_b64decode(call["json"]["raw"])
    parsed = email.message_from_bytes(raw, policy=policy.default)
    assert parsed["To"] == "owner@example.com"
    assert "Name: 山田 太郎" in parsed.get_content()


@pytest.mark.parametrize("status_code", [400, 401, 403, 429, 500])
def test_notify_raises_on_error_status(status_code: int) -> None:
    session = FakeSession(status_code=status_code)

    with pytest.raises(GmailSendError, match=str(status_code)):
        GmailNotifier(session, "owner@example.com").notify("abc123", CONTACT)

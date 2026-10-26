import base64
from email.message import EmailMessage
from typing import Any, Protocol

from google.auth.transport.requests import AuthorizedSession
from google.oauth2.credentials import Credentials

from app.config import EXTERNAL_CALL_TIMEOUT_SECONDS
from app.models.contact import ContactRequest

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


class GmailSendError(Exception):
    pass


class HttpSession(Protocol):
    def post(self, url: str, *, json: Any, timeout: float) -> Any: ...


def build_notification(contact_id: str, contact: ContactRequest, notify_to: str) -> EmailMessage:
    message = EmailMessage()
    # From is left out: Gmail sets it to the account that authorized the OAuth client.
    message["To"] = notify_to
    message["Reply-To"] = contact.email
    # User input is kept out of the subject to avoid header injection.
    message["Subject"] = f"[Portfolio] New inquiry ({contact_id})"
    message.set_content(
        "A new inquiry was submitted via the contact form.\n"
        "\n"
        f"ID: {contact_id}\n"
        f"Name: {contact.name}\n"
        f"Email: {contact.email}\n"
        "\n"
        "Message:\n"
        f"{contact.message}\n"
    )
    return message


class GmailNotifier:
    def __init__(self, session: HttpSession, notify_to: str) -> None:
        self._session = session
        self._notify_to = notify_to

    def notify(self, contact_id: str, contact: ContactRequest) -> None:
        message = build_notification(contact_id, contact, self._notify_to)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        response = self._session.post(
            GMAIL_SEND_URL, json={"raw": raw}, timeout=EXTERNAL_CALL_TIMEOUT_SECONDS
        )
        if response.status_code != 200:
            # The response body is not included; it is not needed to diagnose most failures.
            raise GmailSendError(f"Gmail API returned HTTP {response.status_code}")


def create_gmail_session(client_id: str, client_secret: str, refresh_token: str) -> HttpSession:
    credentials = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=GOOGLE_TOKEN_URI,
        scopes=[GMAIL_SEND_SCOPE],
    )
    # The access token is refreshed on first use and cached for the life of the instance.
    return AuthorizedSession(credentials, refresh_timeout=EXTERNAL_CALL_TIMEOUT_SECONDS)

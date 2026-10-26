"""Obtain a Gmail OAuth refresh token for sending contact notifications.

Run from the backend directory (google-auth-oauthlib is only needed for this script):

    uv run --with google-auth-oauthlib python scripts/get_gmail_refresh_token.py

A browser opens; sign in with the Gmail account that should send the notifications.
The refresh token is the only thing written to stdout, so it can be piped into
`gcloud secrets ... --data-file=-` without appearing on screen. Everything else goes
to stderr. Never commit the token.
"""

import contextlib
import getpass
import os
import sys

from google_auth_oauthlib.flow import InstalledAppFlow

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


def prompt(label: str) -> str:
    # input() would print its prompt to stdout, which is reserved for the token.
    print(label, end="", file=sys.stderr, flush=True)
    return sys.stdin.readline()


def main() -> int:
    client_id = os.environ.get("GMAIL_OAUTH_CLIENT_ID") or prompt("OAuth client ID: ")
    client_secret = os.environ.get("GMAIL_OAUTH_CLIENT_SECRET") or getpass.getpass(
        "OAuth client secret (input hidden): ", stream=sys.stderr
    )
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id.strip(),
                "client_secret": client_secret.strip(),
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=[GMAIL_SEND_SCOPE],
    )
    # The library prints the authorization URL to stdout; send it to stderr instead.
    with contextlib.redirect_stdout(sys.stderr):
        credentials = flow.run_local_server(
            host="localhost",
            port=0,
            # Without these, Google may not return a refresh token on re-authorization.
            access_type="offline",
            prompt="consent",
            authorization_prompt_message="If the browser does not open, visit:\n{url}\n",
            success_message="Authorization complete. You can close this window.",
        )
    if not credentials.refresh_token:
        print("No refresh token was returned.", file=sys.stderr)
        return 1
    print(credentials.refresh_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())

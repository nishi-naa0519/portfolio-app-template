"""Settings for the contact flow, read from environment variables.

Secret values can be given directly (local development) or as a Secret Manager
version via ``<NAME>_SECRET_VERSION`` (production). See ``.env.example``.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Firestore collections used by the contact flow.
CONTACTS_COLLECTION = "contacts"
RATE_LIMITS_COLLECTION = "contact_rate_limits"

# Upper bound for a single call to Firestore / Secret Manager / Gmail. The Cloud Run
# request timeout (15 s) must leave room for all of them.
EXTERNAL_CALL_TIMEOUT_SECONDS = 5.0

DEFAULT_RATE_LIMIT_IP_PER_HOUR = 3
DEFAULT_RATE_LIMIT_IP_PER_DAY = 5
DEFAULT_RATE_LIMIT_SITE_PER_DAY = 20


class ConfigError(Exception):
    """A required setting is missing or invalid."""


@dataclass(frozen=True)
class RateLimits:
    ip_per_hour: int = DEFAULT_RATE_LIMIT_IP_PER_HOUR
    ip_per_day: int = DEFAULT_RATE_LIMIT_IP_PER_DAY
    site_per_day: int = DEFAULT_RATE_LIMIT_SITE_PER_DAY


@dataclass(frozen=True)
class SecretSetting:
    """Either a literal value or a Secret Manager version resource name."""

    name: str
    value: str | None = None
    secret_version: str | None = None


@dataclass(frozen=True)
class ContactSettings:
    notify_to: str
    gmail_client_id: str
    gmail_client_secret: SecretSetting
    gmail_refresh_token: SecretSetting
    ip_hash_key: SecretSetting
    rate_limits: RateLimits
    trust_x_forwarded_for: bool


def _get(environ: Mapping[str, str], name: str) -> str | None:
    # Empty values (e.g. "NAME=" in .env) are treated as unset.
    value = environ.get(name, "").strip()
    return value or None


def _require(environ: Mapping[str, str], name: str) -> str:
    value = _get(environ, name)
    if value is None:
        raise ConfigError(f"{name} is not set")
    return value


def _secret(environ: Mapping[str, str], name: str) -> SecretSetting:
    value = _get(environ, name)
    secret_version = _get(environ, f"{name}_SECRET_VERSION")
    if value is None and secret_version is None:
        raise ConfigError(f"{name} or {name}_SECRET_VERSION is not set")
    return SecretSetting(name=name, value=value, secret_version=secret_version)


def _positive_int(environ: Mapping[str, str], name: str, default: int) -> int:
    raw = _get(environ, name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer") from None
    if value < 1:
        raise ConfigError(f"{name} must be at least 1")
    return value


def _bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    raw = _get(environ, name)
    if raw is None:
        return default
    if raw.lower() in ("1", "true", "yes"):
        return True
    if raw.lower() in ("0", "false", "no"):
        return False
    raise ConfigError(f"{name} must be true or false")


def load_contact_settings(environ: Mapping[str, str] = os.environ) -> ContactSettings:
    return ContactSettings(
        notify_to=_require(environ, "CONTACT_NOTIFY_TO"),
        gmail_client_id=_require(environ, "GMAIL_OAUTH_CLIENT_ID"),
        gmail_client_secret=_secret(environ, "GMAIL_OAUTH_CLIENT_SECRET"),
        gmail_refresh_token=_secret(environ, "GMAIL_REFRESH_TOKEN"),
        ip_hash_key=_secret(environ, "CONTACT_IP_HASH_KEY"),
        rate_limits=RateLimits(
            ip_per_hour=_positive_int(
                environ, "CONTACT_RATE_LIMIT_IP_PER_HOUR", DEFAULT_RATE_LIMIT_IP_PER_HOUR
            ),
            ip_per_day=_positive_int(
                environ, "CONTACT_RATE_LIMIT_IP_PER_DAY", DEFAULT_RATE_LIMIT_IP_PER_DAY
            ),
            site_per_day=_positive_int(
                environ, "CONTACT_RATE_LIMIT_SITE_PER_DAY", DEFAULT_RATE_LIMIT_SITE_PER_DAY
            ),
        ),
        # Cloud Run (K_SERVICE is set) puts the client address in X-Forwarded-For.
        # Elsewhere the header could be forged, so it is ignored by default.
        trust_x_forwarded_for=_bool(
            environ, "TRUST_X_FORWARDED_FOR", default=_get(environ, "K_SERVICE") is not None
        ),
    )

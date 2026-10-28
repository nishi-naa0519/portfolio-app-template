import pytest

from app.config import ConfigError, RateLimits, SecretSetting, load_contact_settings
from app.services.secrets import resolve_secret

REQUIRED = {
    "CONTACT_NOTIFY_TO": "owner@example.com",
    "GMAIL_OAUTH_CLIENT_ID": "client-id",
    "GMAIL_OAUTH_CLIENT_SECRET": "client-secret",
    "GMAIL_REFRESH_TOKEN": "refresh-token",
    "CONTACT_IP_HASH_KEY": "hash-key",
}


def test_defaults() -> None:
    settings = load_contact_settings(REQUIRED)

    assert settings.notify_to == "owner@example.com"
    assert settings.gmail_client_id == "client-id"
    assert settings.gmail_refresh_token == SecretSetting("GMAIL_REFRESH_TOKEN", "refresh-token")
    assert settings.rate_limits == RateLimits(ip_per_hour=3, ip_per_day=5, site_per_day=20)
    assert settings.trust_x_forwarded_for is False


def test_rate_limits_can_be_configured() -> None:
    settings = load_contact_settings(
        {
            **REQUIRED,
            "CONTACT_RATE_LIMIT_IP_PER_HOUR": "1",
            "CONTACT_RATE_LIMIT_IP_PER_DAY": "2",
            "CONTACT_RATE_LIMIT_SITE_PER_DAY": "10",
        }
    )

    assert settings.rate_limits == RateLimits(ip_per_hour=1, ip_per_day=2, site_per_day=10)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5"])
def test_invalid_rate_limit_is_rejected(value: str) -> None:
    with pytest.raises(ConfigError, match="CONTACT_RATE_LIMIT_IP_PER_HOUR"):
        load_contact_settings({**REQUIRED, "CONTACT_RATE_LIMIT_IP_PER_HOUR": value})


@pytest.mark.parametrize("name", sorted(REQUIRED))
def test_missing_setting_is_rejected(name: str) -> None:
    environ = {**REQUIRED, name: ""}

    with pytest.raises(ConfigError, match=name):
        load_contact_settings(environ)


def test_secret_can_come_from_secret_manager() -> None:
    environ = {k: v for k, v in REQUIRED.items() if k != "GMAIL_REFRESH_TOKEN"}
    version = "projects/p/secrets/gmail-refresh-token/versions/1"
    environ["GMAIL_REFRESH_TOKEN_SECRET_VERSION"] = version

    setting = load_contact_settings(environ).gmail_refresh_token

    assert setting == SecretSetting("GMAIL_REFRESH_TOKEN", secret_version=version)
    assert resolve_secret(setting, read_version={version: "token\r\n"}.__getitem__) == "token"


def test_literal_secret_takes_precedence_over_secret_manager() -> None:
    setting = SecretSetting(
        "X", value=" literal ", secret_version="projects/p/secrets/x/versions/1"
    )

    def read_version(name: str) -> str:
        raise AssertionError("Secret Manager must not be called")

    assert resolve_secret(setting, read_version) == "literal"


def test_empty_secret_is_rejected() -> None:
    setting = SecretSetting("X", secret_version="projects/p/secrets/x/versions/1")

    with pytest.raises(ValueError, match="X is empty"):
        resolve_secret(setting, lambda name: "\n")


@pytest.mark.parametrize(
    ("environ", "expected"),
    [
        ({}, False),
        ({"K_SERVICE": "portfolio"}, True),
        ({"K_SERVICE": "portfolio", "TRUST_X_FORWARDED_FOR": "false"}, False),
        ({"TRUST_X_FORWARDED_FOR": "true"}, True),
    ],
)
def test_x_forwarded_for_is_trusted_on_cloud_run(environ: dict[str, str], expected: bool) -> None:
    assert load_contact_settings({**REQUIRED, **environ}).trust_x_forwarded_for is expected

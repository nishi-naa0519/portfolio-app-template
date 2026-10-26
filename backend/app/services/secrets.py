from collections.abc import Callable

from app.config import EXTERNAL_CALL_TIMEOUT_SECONDS, SecretSetting

SecretVersionReader = Callable[[str], str]


def read_secret_manager_version(name: str) -> str:
    """Read a version such as projects/<PROJECT>/secrets/<SECRET>/versions/<VERSION>."""
    # Imported here so that the client library is loaded only when a secret is read.
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=name, timeout=EXTERNAL_CALL_TIMEOUT_SECONDS)
    return response.payload.data.decode("utf-8")


def resolve_secret(
    setting: SecretSetting, read_version: SecretVersionReader = read_secret_manager_version
) -> str:
    # A literal value takes precedence so that local development needs no GCP access.
    raw = setting.value if setting.value is not None else read_version(str(setting.secret_version))
    # Values piped into `gcloud secrets create --data-file=-` often end with a newline.
    value = raw.strip()
    if not value:
        raise ValueError(f"{setting.name} is empty")
    return value

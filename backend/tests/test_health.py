import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app


def test_health_returns_ok() -> None:
    client = TestClient(create_app())

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_not_served_without_dist_dir() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 404


def test_frontend_is_served_from_dist_dir(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>frontend</h1>", encoding="utf-8")
    client = TestClient(create_app(tmp_path))

    assert client.get("/").text == "<h1>frontend</h1>"
    assert client.get("/api/health").json() == {"status": "ok"}


def test_api_docs_are_available_by_default() -> None:
    client = TestClient(create_app())

    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_api_docs_can_be_disabled(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text("<h1>frontend</h1>", encoding="utf-8")
    client = TestClient(create_app(tmp_path, enable_api_docs=False))

    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
    assert client.get("/api/health").json() == {"status": "ok"}


def test_google_cloud_libraries_are_not_loaded_at_startup() -> None:
    # Page views should not pay for importing them on a Cloud Run cold start.
    code = "import sys, app.main; sys.exit(any(m.startswith('google.cloud') for m in sys.modules))"

    result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parents[1])

    assert result.returncode == 0

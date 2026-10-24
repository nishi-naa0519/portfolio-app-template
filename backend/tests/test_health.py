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

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
pytest.importorskip("sqlalchemy")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api.db'}")
    from fastapi.testclient import TestClient

    from odos.backend.api import create_app

    return TestClient(create_app())


def test_health_and_audit_with_mock_source(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    body = client.post("/api/v1/audit/run", params={"source": "mock"}).json()
    assert body["status"] == "success" and body["source"] == "mock"
    assert len(body["report"]["anomalies"]) == 1
    events = client.get("/api/v1/audit/events").json()
    assert events[0]["severity"] in {"HIGH", "CRITICAL", "MEDIUM"}
    assert client.get("/api/v1/summary").json()["days_observed"] >= 1


def test_unknown_source_is_a_400(client):
    assert client.post("/api/v1/audit/run", params={"source": "oracle"}).status_code == 400


def test_review_unknown_suggestion_is_a_409(client):
    response = client.post("/api/v1/suggestions/999/approve", json={"reviewer": "me"})
    assert response.status_code == 409


def test_api_key_is_enforced(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'api2.db'}")
    monkeypatch.setenv("ODOS_API_KEY", "s3cret")
    from fastapi.testclient import TestClient

    from odos.backend.api import create_app

    c = TestClient(create_app())
    assert c.get("/healthz").status_code == 200
    assert c.get("/api/v1/suggestions").status_code == 401
    assert c.get("/api/v1/suggestions", headers={"X-API-Key": "s3cret"}).status_code == 200

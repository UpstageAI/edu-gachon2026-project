from fastapi.testclient import TestClient

from app.main import create_app


def test_health_endpoint_returns_public_service_status():
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "finbrief",
        "version": "0.1.0",
        "environment": "local",
        "mock_data": True,
    }


def test_health_endpoint_does_not_expose_secret_values(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://example.invalid/secret-token")
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert "secret-token" not in response.text
    assert "DISCORD_WEBHOOK_URL" not in response.text

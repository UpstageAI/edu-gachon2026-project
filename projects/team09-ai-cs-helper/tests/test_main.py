import main
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_health_check_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_delete_inquiry_returns_deleted_status(monkeypatch):
    monkeypatch.setattr(main, "delete_inquiry", lambda inquiry_id: True)

    response = client.delete("/inquiries/inq-123")

    assert response.status_code == 200
    assert response.json() == {"inquiry_id": "inq-123", "status": "deleted"}


def test_delete_inquiry_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr(main, "delete_inquiry", lambda inquiry_id: False)

    response = client.delete("/inquiries/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "inquiry not found"}


def test_get_inquiry_logs_returns_logs(monkeypatch):
    monkeypatch.setattr(main, "get_inquiry", lambda inquiry_id: {"inquiry_id": inquiry_id})
    monkeypatch.setattr(main, "list_inquiry_logs", lambda inquiry_id: [{"sequence": 1}])

    response = client.get("/inquiries/inq-123/logs")

    assert response.status_code == 200
    assert response.json() == [{"sequence": 1}]


def test_log_action_rejects_unsupported_event(monkeypatch):
    response = client.post(
        "/inquiries/inq-123/logs/actions",
        json={"event": "arbitrary_event"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "unsupported log action"}


def test_log_action_records_edit_started(monkeypatch):
    captured = {}
    monkeypatch.setattr(main, "get_inquiry", lambda inquiry_id: {"inquiry_id": inquiry_id})

    def fake_append(inquiry_id, **values):
        captured["inquiry_id"] = inquiry_id
        captured.update(values)
        return True

    monkeypatch.setattr(main, "append_inquiry_log", fake_append)

    response = client.post(
        "/inquiries/inq-123/logs/actions",
        json={"event": "edit_started"},
    )

    assert response.status_code == 200
    assert response.json() == {"event": "edit_started", "saved": True}
    assert captured["stage"] == "human"
    assert captured["event"] == "edit_started"

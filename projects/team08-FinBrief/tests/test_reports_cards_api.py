from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app.api.dependencies import reset_repository_bundle_cache
from app.core.config import Settings, get_settings
from app.main import create_app


def _client(monkeypatch, tmp_path) -> TestClient:
    reset_repository_bundle_cache()
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("FINBRIEF_OUT", str(tmp_path / "cards"))
    monkeypatch.setenv("FINBRIEF_IMG_OUT", str(tmp_path / "images"))
    monkeypatch.setenv("FINBRIEF_REPORT_OUT", str(tmp_path / "reports"))
    get_settings.cache_clear()
    return TestClient(create_app(Settings(app_env="test", enable_mock_data=True)))


def test_run_report_endpoint_generates_cards_for_subscriptions(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    user_id = "report_user_run"
    client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )

    response = client.post(
        "/api/v1/reports/run",
        json={"run_date": "2026-07-10", "dry_run": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["generated_cards"] == 1
    assert payload["reused_cards"] == 0
    # 전체시장 리포트(채널당 1회) + 구독 카드(1) = 2
    assert payload["delivery_results"] == 2
    assert payload["trace_id"].startswith("local_mock_trace_")
    assert "투자 조언이 아닌" in payload["disclaimer"]
    assert payload["report_url"]
    report_path = Path(payload["report_url"])
    assert report_path.exists()
    with Image.open(report_path) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1080)


def test_run_report_endpoint_uses_langfuse_trace_when_enabled(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.test")
    get_settings.cache_clear()
    user_id = "report_user_trace"
    client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )

    response = client.post(
        "/api/v1/reports/run",
        json={"run_date": "2026-07-10", "dry_run": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["trace_id"]
    assert not payload["trace_id"].startswith("local_mock_trace_")


def test_cards_today_returns_user_subscription_cards(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    user_id = "report_user_cards"
    client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_nasdaq", "channel": "discord"},
    )
    client.post("/api/v1/reports/run", json={"run_date": "2026-07-10", "dry_run": True})

    response = client.get(
        "/api/v1/cards/today",
        params={"user_id": user_id, "run_date": "2026-07-10"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == user_id
    assert payload["run_date"] == "2026-07-10"
    assert [item["topic_id"] for item in payload["cards"]] == ["topic_nasdaq"]
    assert "투자 조언이 아닌" in payload["cards"][0]["disclaimer"]


def test_reports_today_returns_latest_mock_report(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/v1/subscriptions/report_user_today/topics",
        json={"topic_id": "topic_semi", "channel": "discord"},
    )
    client.post("/api/v1/reports/run", json={"run_date": "2026-07-10", "dry_run": True})

    response = client.get("/api/v1/reports/today", params={"run_date": "2026-07-10"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_date"] == "2026-07-10"
    assert payload["status"] == "completed"
    assert payload["generated_cards"] == 1
    assert "투자 조언이 아닌" in payload["disclaimer"]
    assert payload["report_url"]


def test_reports_today_reads_repository_after_memory_reset(monkeypatch, tmp_path):
    from app.agents.pipeline import reset_latest_results

    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/v1/subscriptions/report_user_shared/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )
    client.post("/api/v1/reports/run", json={"run_date": "2026-07-10", "dry_run": True})
    reset_latest_results()

    response = client.get("/api/v1/reports/today", params={"run_date": "2026-07-10"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_date"] == "2026-07-10"
    assert payload["status"] == "completed"
    assert payload["report_url"]


def test_reports_today_explanation_returns_focus_items(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/v1/subscriptions/report_user_explain/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )
    client.post("/api/v1/reports/run", json={"run_date": "2026-07-10", "dry_run": True})

    response = client.get(
        "/api/v1/reports/today/explanation",
        params={"run_date": "2026-07-10", "max_focus": 3},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_date"] == "2026-07-10"
    assert payload["focus_items"]
    assert len(payload["focus_items"]) <= 3
    assert "reply" in payload
    assert "투자 조언이 아닌" in payload["disclaimer"]


def test_cards_today_sources_returns_card_source_explanations(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    user_id = "report_user_card_sources"
    client.post(
        f"/api/v1/subscriptions/{user_id}/topics",
        json={"topic_id": "topic_btc", "channel": "discord"},
    )
    client.post("/api/v1/reports/run", json={"run_date": "2026-07-10", "dry_run": True})

    response = client.get(
        "/api/v1/cards/today/sources",
        params={"user_id": user_id, "run_date": "2026-07-10"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["user_id"] == user_id
    assert payload["run_date"] == "2026-07-10"
    assert payload["cards"]
    assert payload["cards"][0]["topic_id"] == "topic_btc"
    assert "source_summary" in payload["cards"][0]

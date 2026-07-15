from datetime import date
from app.services import notifier
from app.agents.graph import graph


def test_deliver_dry_run(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setenv("DELIVERY_DRY_RUN", "true")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")   # 봇 경로 활성(채널ID는 fixture)
    final = graph.invoke({"run_id": "t", "run_date": date.today().isoformat(),
                          "status": "queued", "cards": [], "deliveries": [], "errors": []})
    assert final["deliveries"] and all(d["status"] == "dry_run" for d in final["deliveries"])


def test_deliver_sent_mock(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setattr(notifier, "send_via_bot", lambda **kw: {"status": "sent"})
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    final = graph.invoke({"run_id": "t", "run_date": date.today().isoformat(),
                          "status": "queued", "cards": [], "deliveries": [], "errors": []})
    assert final["deliveries"] and all(d["status"] == "sent" for d in final["deliveries"])

"""deliver 라우팅: discord_channel_id 있으면 봇 전송, 없으면 skip(웹훅 제거됨)."""
from app.agents import nodes
from app.services import notifier


def _card(topic_id):
    return {"topic_id": topic_id, "category": "MARKET", "headline": "h", "lead": "l",
            "body": "b", "source": "s", "disclaimer": "d", "image_path": None}


def test_deliver_routes_to_bot_when_channel_id(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    bot_calls = []
    monkeypatch.setattr(notifier, "send_via_bot",
                        lambda **k: bot_calls.append(k) or {"status": "sent"})

    state = {
        "cards": [_card("nasdaq")],
        "subscriptions": [{"user_id": "u1", "topic_id": "nasdaq", "channel": "discord",
                           "discord_channel_id": "999"}],
    }
    out = nodes.deliver(state)
    assert len(bot_calls) == 1 and bot_calls[0]["channel_id"] == "999"
    assert out["deliveries"][0]["status"] == "sent"


def test_deliver_skips_without_channel_id(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    bot_calls = []
    monkeypatch.setattr(notifier, "send_via_bot",
                        lambda **k: bot_calls.append(k) or {"status": "sent"})

    state = {
        "cards": [_card("nasdaq")],
        "subscriptions": [{"user_id": "u1", "topic_id": "nasdaq", "channel": "discord"}],
    }
    out = nodes.deliver(state)
    # 채널ID 없으면 봇 호출 없이 skip (웹훅 폴백 없음)
    assert bot_calls == []
    assert all(d["status"] == "skipped" for d in out["deliveries"])

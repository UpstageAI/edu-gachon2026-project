from app.services import notifier


def test_send_via_bot_dry_run(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    monkeypatch.delenv("DELIVERY_DRY_RUN", raising=False)  # 기본 true
    assert notifier.send_via_bot(channel_id="123", text="t")["status"] == "dry_run"


def test_send_via_bot_skipped_without_channel(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    assert notifier.send_via_bot(channel_id="", text="t")["status"] == "skipped"


def test_send_via_bot_skipped_without_token(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    assert notifier.send_via_bot(channel_id="123", text="t")["status"] == "skipped"


def test_send_via_bot_sent_mock(monkeypatch):
    calls = []
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    import httpx

    class _R:
        def raise_for_status(self): pass

    monkeypatch.setattr(httpx, "post", lambda *a, **k: (calls.append((a, k)) or _R()))
    assert notifier.send_via_bot(channel_id="123", text="t")["status"] == "sent"
    assert len(calls) == 1
    # 봇 토큰 헤더로 channels/{id}/messages 에 전송
    assert "channels/123/messages" in calls[0][0][0]
    assert calls[0][1]["headers"]["Authorization"] == "Bot x"

from app.services import notifier


def test_dry_run_default(monkeypatch):
    monkeypatch.delenv("DELIVERY_DRY_RUN", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    assert notifier.dry_run() is True
    res = notifier.send_via_bot(channel_id="123", text="t")
    assert res["status"] == "dry_run"


def test_skipped_without_channel(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    assert notifier.send_via_bot(channel_id="", text="t")["status"] == "skipped"


def test_skipped_without_token(monkeypatch):
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    assert notifier.send_via_bot(channel_id="123", text="t")["status"] == "skipped"


def test_sent_mock(monkeypatch):
    import httpx

    class _R:
        def raise_for_status(self):
            pass

    calls = []
    monkeypatch.setattr(httpx, "post", lambda *a, **k: calls.append(k) or _R())
    monkeypatch.setenv("DELIVERY_DRY_RUN", "false")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "x")
    res = notifier.send_via_bot(channel_id="123", text="t")
    assert res["status"] == "sent" and len(calls) == 1


def test_format_card_text():
    txt = notifier.format_card_text({"category": "MARKET", "headline": "나스닥 상승",
                                     "lead": "L", "body": "B", "source": "S", "disclaimer": "D"})
    assert "나스닥 상승" in txt and "MARKET" in txt

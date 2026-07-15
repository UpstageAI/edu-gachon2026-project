from app.core.config import Settings
from app.services import chatbot_observability as chatobs


def test_turn_metadata_hashes_discord_identifiers_and_excludes_raw_values():
    settings = Settings(finbrief_trace_salt="unit-test-salt", langfuse_capture_io=False)

    metadata = chatobs.build_turn_metadata(
        channel="discord",
        ext_user_id="1468505579847946378",
        channel_id="1234567890",
        message="나스닥 구독해줘",
        settings=settings,
    )

    assert metadata["channel"] == "discord"
    assert metadata["user_hash"].startswith("usr_")
    assert metadata["channel_hash"].startswith("ch_")
    assert "1468505579847946378" not in str(metadata)
    assert "1234567890" not in str(metadata)
    assert "나스닥 구독해줘" not in str(metadata)
    assert metadata["captured_message"] is None


def test_capture_text_respects_capture_policy_and_masks_sensitive_text():
    disabled = Settings(langfuse_capture_io=False)
    enabled = Settings(langfuse_capture_io=True)

    assert chatobs.capture_text("hello", disabled) is None

    captured = chatobs.capture_text(
        "key sk_test_12345678901234567890 webhook https://discord.com/api/webhooks/a/b",
        enabled,
    )

    assert captured is not None
    assert "[SECRET_REDACTED]" in captured
    assert "[WEBHOOK_REDACTED]" in captured
    assert "sk_test_" not in captured
    assert "discord.com/api/webhooks" not in captured


def test_chatbot_turn_trace_noops_when_langfuse_disabled():
    settings = Settings(langfuse_enabled=False, finbrief_trace_salt="unit-test-salt")

    with chatobs.chatbot_turn_trace(
        channel="discord",
        ext_user_id="u1",
        message="나스닥 구독",
        channel_id="c1",
        settings=settings,
    ) as (trace_id, turn_id, observation):
        observation.update(output={"ok": True})

    assert turn_id.startswith("chatbot_turn_")
    assert trace_id.startswith("local_mock_trace_chatbot_turn_")


def test_score_chatbot_turn_is_fail_open_when_langfuse_disabled():
    sent = chatobs.score_chatbot_turn(
        "chatbot.tool_success",
        score=1.0,
        passed=True,
        trace_id="local_mock_trace_chatbot_turn_x",
        turn_id="chatbot_turn_x",
        metadata={"intent": "add_topic"},
        settings=Settings(langfuse_enabled=False),
    )

    assert sent is False

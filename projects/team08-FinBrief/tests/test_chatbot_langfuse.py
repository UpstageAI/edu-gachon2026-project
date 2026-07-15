from app.repositories.memory import create_memory_repositories
from app.services import chatbot
from app.services.subscription_service import SubscriptionService


def _svc():
    return SubscriptionService(create_memory_repositories())


def test_parse_intent_passes_langfuse_metadata_to_llm(monkeypatch):
    import app.core.llm as core_llm

    captured = {}
    catalog = _svc().catalog()
    topic = catalog[0]

    def fake_chat_json(system, message, **kwargs):
        captured.update(kwargs)
        return {"intent": "add_topic", "topic": topic.name}

    monkeypatch.setenv("UPSTAGE_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    monkeypatch.setattr(core_llm, "chat_json", fake_chat_json)

    intent, topic_id = chatbot.parse_intent(
        "구독하고 싶어",
        catalog,
        trace_id="trace_chatbot_1",
        turn_id="chatbot_turn_1",
    )

    assert intent == "add_topic"
    assert topic_id == topic.topic_id
    assert captured["metadata"]["trace_id"] == "trace_chatbot_1"
    assert captured["metadata"]["session_id"] == "chatbot_turn_1"
    assert captured["metadata"]["node"] == "chatbot.intent_parse"
    assert "chatbot" in captured["metadata"]["tags"]


def test_handle_records_chatbot_scores_without_changing_response(monkeypatch):
    from app.core.config import get_settings
    from app.services import chatbot_observability as chatobs

    scores = []

    def fake_score(name, **kwargs):
        scores.append((name, kwargs))
        return True

    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(chatobs, "score_chatbot_turn", fake_score)

    service = _svc()
    topic = service.catalog()[0]
    response = chatbot.handle(service, "discord", "raw-user-id", f"{topic.name} 구독", "raw-channel-id")

    assert response["intent"] == "add_topic"
    assert response["status"] == "completed"
    assert "trace_id" not in response
    names = [name for name, _ in scores]
    assert "chatbot.intent_resolved" in names
    assert "chatbot.tool_success" in names
    assert "chatbot.reply_format" in names
    assert all(item[1]["trace_id"].startswith("local_mock_trace_chatbot_turn_") for item in scores)


def test_investment_advice_block_records_safety_score(monkeypatch):
    from app.core.config import get_settings
    from app.services import chatbot_observability as chatobs

    scores = []

    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        chatobs,
        "score_chatbot_turn",
        lambda name, **kwargs: scores.append((name, kwargs)) or True,
    )

    response = chatbot.handle(_svc(), "discord", "raw-user-id", "오늘 비트코인 사야 해?", "raw-channel-id")

    assert response["status"] == "blocked"
    assert "chatbot.safety.blocked_advice" in [name for name, _ in scores]

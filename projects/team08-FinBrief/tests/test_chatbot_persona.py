from app.repositories.memory import create_memory_repositories
from app.services import chatbot
from app.services.chatbot_responses import (
    format_add_success,
    format_help_reply,
    format_investment_advice_reply,
)
from app.services.chatbot_suggestions import suggest_topics
from app.services.subscription_service import SubscriptionService


def _svc():
    return SubscriptionService(create_memory_repositories())


def test_help_reply_introduces_persona_and_examples():
    reply = format_help_reply()

    assert "브리핑 메이트" in reply
    assert "!" in reply
    assert "✨" in reply or "🚀" in reply
    assert "나스닥 구독" in reply
    assert "내 토픽" in reply
    assert "비트코인 취소" in reply


def test_add_success_reply_uses_lively_persona():
    reply = format_add_success("나스닥", 2, 5)

    assert "🎉" in reply
    assert "나스닥" in reply
    assert "2/5" in reply
    assert "!" in reply


def test_investment_advice_reply_refuses_and_redirects_to_subscription():
    reply = format_investment_advice_reply()

    assert "대신해드릴 수 없" in reply
    assert "⚠️" in reply
    assert "비트코인 구독" in reply
    assert "목표가" not in reply


def test_suggest_topics_returns_limited_keyword_candidates():
    catalog = _svc().catalog()

    suggestions = suggest_topics("금리", catalog, limit=3)

    assert 1 <= len(suggestions) <= 3
    assert any("금리" in item.name for item in suggestions)
    assert all(item.topic_id != "topic_gold" for item in suggestions)
    assert all(item.score >= 1 for item in suggestions)


def test_chatbot_help_intent_uses_persona(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")

    result = chatbot.handle(_svc(), "discord", "user_help", "뭐 할 수 있어?")

    assert result["intent"] == "help"
    assert result["status"] == "completed"
    assert "브리핑 메이트" in result["reply"]
    assert "나스닥 구독" in result["reply"]


def test_chatbot_recommend_intent_returns_curated_topics(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")

    result = chatbot.handle(_svc(), "discord", "user_reco", "처음인데 뭐 받아보면 좋아?")

    assert result["intent"] == "recommend_topics"
    assert result["status"] == "completed"
    assert "처음 시작하기 좋은 토픽" in result["reply"]
    assert "나스닥" in result["reply"]


def test_chatbot_blocks_investment_advice_and_redirects(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")

    result = chatbot.handle(_svc(), "discord", "user_advice", "오늘 비트코인 지금 사야 해?")

    assert result["intent"] == "unknown"
    assert result["status"] == "blocked"
    assert "투자 판단" in result["reply"]
    assert "비트코인 구독" in result["reply"]


def test_chatbot_clarifies_ambiguous_topic_keyword(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")

    result = chatbot.handle(_svc(), "discord", "user_rate", "금리 구독")

    assert result["intent"] == "clarify_topic"
    assert result["status"] == "blocked"
    assert "후보" in result["reply"]
    assert "미국" in result["reply"] or "한국" in result["reply"]

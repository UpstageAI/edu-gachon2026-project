from datetime import date

import pytest

from app.core.schemas import CardArtifact, NewsEvidence, TopicAnalysis
from app.repositories.memory import create_memory_repositories
from app.services import chatbot
from app.services.subscription_service import SubscriptionService


def _svc():
    return SubscriptionService(create_memory_repositories())


def test_rule_intent_persists_channel_id(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    s = _svc()
    topic = s.catalog()[0]
    r = chatbot.handle(s, "discord", "u1", f"{topic.name} 구독해줘", "12345")
    assert r["intent"] == "add_topic" and r["status"] == "completed" and r["topic"] == topic.topic_id
    assert "아침 브리핑" in r["reply"]
    assert "현재" in r["reply"]
    # 저장에 channel_id 반영
    subs = s.list("discord", "u1")
    assert any(x.topic_id == topic.topic_id and x.discord_channel_id == "12345" for x in subs)


def test_add_topic_success_reply_lists_current_subscriptions(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    s = _svc()
    catalog = s.catalog()
    first = catalog[0]
    nasdaq = next(t for t in catalog if t.normalized_name == "nasdaq")
    s.add("discord", "u_subs", first.topic_id, "123")

    r = chatbot.handle(s, "discord", "u_subs", "nasdaq 구독", "123")

    assert r["intent"] == "add_topic"
    assert r["status"] == "completed"
    assert "현재 구독 토픽" in r["reply"]
    assert first.name in r["reply"]
    assert nasdaq.name in r["reply"]


def test_rule_intent_unknown_topic_blocked(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    r = chatbot.handle(_svc(), "discord", "u1", "존재하지않는토픽 구독")
    assert r["status"] == "blocked"


def test_llm_intent(monkeypatch):
    import app.core.llm as core_llm
    s = _svc()
    topic = s.catalog()[0]
    monkeypatch.setenv("UPSTAGE_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    monkeypatch.setattr(core_llm, "chat_json", lambda sys, msg: {"intent": "add_topic", "topic": topic.name})
    r = chatbot.handle(s, "discord", "u2", "구독하고 싶어", "777")
    assert r["topic"] == topic.topic_id and r["status"] == "completed"


def test_recommend_topics_filters_out_of_catalog(monkeypatch):
    """LLM이 카탈로그 밖 이름을 섞어 반환해도 검증으로 걸러진다."""
    import app.core.llm as core_llm
    catalog = _svc().catalog()
    real = catalog[0].name
    monkeypatch.setenv("UPSTAGE_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    monkeypatch.setattr(core_llm, "chat_json",
                        lambda sys, msg: {"topics": [real, "존재하지않는가짜토픽XYZ"]})
    out = chatbot.recommend_topics("관심사 아무거나", catalog)
    assert real in out
    assert "존재하지않는가짜토픽XYZ" not in out


def test_recommend_topics_fallback_without_llm(monkeypatch):
    """키 없음(use_llm False)이면 대표 토픽 상위 N으로 폴백."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    catalog = _svc().catalog()
    out = chatbot.recommend_topics("아무거나", catalog)
    assert out == [t.name for t in catalog][:5]


def test_list_topics_extended(monkeypatch):
    """목록 조회 = 현재 구독 표 + 전체 구독 가능 토픽 표."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    s = _svc()
    catalog = s.catalog()
    topic = catalog[0]
    nasdaq = next(t for t in catalog if t.normalized_name == "nasdaq")
    s.add("discord", "u1", topic.topic_id, "123")
    s.add("discord", "u1", nasdaq.topic_id, "123")
    r = chatbot.handle(s, "discord", "u1", "내 토픽 목록")
    assert r["intent"] == "list_topics" and r["status"] == "completed"
    assert topic.name in r["reply"]          # 현재 구독 표시
    assert nasdaq.name in r["reply"]
    assert "총" in r["reply"]                 # 전체 개수(요약)
    assert "구독 가능" in r["reply"]
    assert "| 번호 | 현재 구독 토픽 | 유형 |" in r["reply"]
    assert "| 유형 | 구독 가능 토픽 |" in r["reply"]
    assert "💡" not in r["reply"]
    assert "추천" not in r["reply"]


def test_welcome_text_has_examples():
    """온보딩 문구에 사용 예시가 포함."""
    w = chatbot.welcome_text(_svc())
    assert "브리핑 메이트" in w and "구독" in w and "멘션" in w and "총" in w
    assert "!" in w and ("🚀" in w or "✨" in w)


def test_add_topic_ambiguous_recommends(monkeypatch):
    """add 의도인데 토픽 매칭 실패 시 추천을 제시(blocked)."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    r = chatbot.handle(_svc(), "discord", "u9", "뭔가 구독하고 싶어")
    assert r["intent"] == "add_topic" and r["status"] == "blocked"
    assert "토픽" in r["reply"]


def test_add_topic_accepts_unique_aliases_and_normalized_names(monkeypatch):
    """카탈로그에 있는 영문 alias/normalized_name도 바로 구독된다."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    cases = [
        ("btc 구독", "topic_btc"),
        ("nasdaq 구독", "topic_nasdaq"),
        ("S&P500 구독", "topic_sp500"),
        ("USD/KRW 구독", "topic_usdkrw"),
        ("fed funds 구독", "topic_fed_funds"),
    ]

    for message, expected_topic_id in cases:
        s = _svc()
        r = chatbot.handle(s, "discord", f"alias_{expected_topic_id}", message, "c")
        assert r["intent"] == "add_topic"
        assert r["status"] == "completed"
        assert r["topic"] == expected_topic_id


def test_add_topic_keeps_ambiguous_alias_as_clarification(monkeypatch):
    """여러 후보가 같은 강도로 맞는 표현은 자동 구독하지 않는다."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    r = chatbot.handle(_svc(), "discord", "ambiguous_alias", "달러 환율 구독", "c")

    assert r["intent"] == "clarify_topic"
    assert r["status"] == "blocked"
    assert "후보" in r["reply"]


def test_llm_intent_accepts_normalized_topic_name(monkeypatch):
    """LLM이 표시명 대신 normalized_name을 반환해도 카탈로그 topic_id로 매핑한다."""
    import app.core.llm as core_llm

    monkeypatch.setenv("UPSTAGE_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    monkeypatch.setattr(core_llm, "chat_json", lambda sys, msg: {"intent": "add_topic", "topic": "btc"})

    r = chatbot.handle(_svc(), "discord", "llm_alias", "비트코인 구독하고 싶어", "c")

    assert r["intent"] == "add_topic"
    assert r["status"] == "completed"
    assert r["topic"] == "topic_btc"


def test_delete_ambiguous_resolves_to_subscription(monkeypatch):
    """'환율 제거' 모호어 → 구독 중인 USD/KRW 하나로 해결해 제거."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    s = _svc()
    cat = s.catalog()
    usdkrw = next(t for t in cat if t.normalized_name == "usdkrw")
    s.add("discord", "del_u1", usdkrw.topic_id, "c")
    r = chatbot.handle(s, "discord", "del_u1", "환율 제거해", "c")
    assert r["intent"] == "delete_topic" and r["status"] == "completed"
    assert len(s.list("discord", "del_u1")) == 0


def test_delete_not_subscribed_blocked(monkeypatch):
    """구독하지 않은 토픽 제거 시도 → 현재 구독 안내(blocked)."""
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    s = _svc()
    r = chatbot.handle(s, "discord", "del_u2", "비트코인 제거", "c")
    assert r["intent"] == "delete_topic" and r["status"] == "blocked"
    assert "구독 목록에 없" in r["reply"]


def test_explain_report_without_generated_report_guides_user(monkeypatch):
    """리포트 설명 요청인데 오늘 리포트가 없으면 생성 안내."""
    from app.agents.pipeline import reset_latest_results

    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    reset_latest_results()
    r = chatbot.handle(_svc(), "discord", "explain_u1", "오늘 리포트에서 뭐 봐야 해?")

    assert r["intent"] == "explain_report"
    assert r["status"] == "blocked"
    assert "리포트" in r["reply"]
    assert "생성" in r["reply"]


def test_explain_card_sources_returns_sources_for_today_cards(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    service = SubscriptionService(repos)
    user_id = "card_source_user"
    topic = repos.topics.get_by_normalized_name("btc")
    service.add("discord", user_id, topic.topic_id, "channel")
    run_date = date.today()
    repos.cards.upsert(
        CardArtifact(
            card_id=f"card_{topic.topic_id}_{run_date:%Y%m%d}",
            topic_id=topic.topic_id,
            run_date=run_date,
            title="비트코인 카드뉴스",
            analysis=TopicAnalysis(
                topic_id=topic.topic_id,
                run_date=run_date,
                headline="비트코인 흐름 점검",
                summary="ETF 자금 흐름을 봅니다.",
                key_points=["ETF 자금 흐름"],
                evidence=[
                    NewsEvidence(
                        news_id="news_btc",
                        title="비트코인 ETF 자금 유입",
                        source="연합뉴스",
                        url="https://example.com/btc",
                        similarity=0.9,
                        snippet="ETF 자금 유입이 이어졌습니다.",
                    )
                ],
            ),
        )
    )

    r = chatbot.handle(service, "discord", user_id, "오늘 카드뉴스 출처 알려줘", "channel")

    assert r["intent"] == "explain_card_sources"
    assert r["status"] == "completed"
    assert "연합뉴스" in r["reply"]
    assert "출처" in r["reply"]


@pytest.mark.parametrize(
    ("message", "expected_intent"),
    [
        ("명령어 알려줘", "help"),
        ("처음 쓰는데 어떻게 해?", "help"),
        ("요즘 뭐 보면 좋아?", "recommend_topics"),
        ("추천 토픽 보여줘", "recommend_topics"),
        ("나스닥 알림 켜줘", "add_topic"),
        ("비트코인 챙겨줘", "add_topic"),
        ("환율은 이제 안 볼래", "delete_topic"),
        ("나스닥 알림 꺼줘", "delete_topic"),
        ("내가 뭐 보고 있지?", "list_topics"),
        ("구독 현황 보여줘", "list_topics"),
        ("몇 개 더 구독할 수 있어?", "tier_status"),
        ("내 한도 알려줘", "tier_status"),
        ("오늘 시장 요약해줘", "explain_report"),
        ("오늘 뭐가 제일 중요해?", "explain_report"),
        ("변동 큰 지표 해설해줘", "explain_report"),
        ("출처 설명해줘", "explain_card_sources"),
        ("근거 기사 보여줘", "explain_card_sources"),
        ("어떤 기사 참고했어?", "explain_card_sources"),
        ("나스닥 카드뉴스 왜 이렇게 썼어?", "explain_card_sources"),
    ],
)
def test_rule_intent_recognizes_expanded_natural_triggers(monkeypatch, message, expected_intent):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    intent, _ = chatbot.parse_intent(message, _svc().catalog())

    assert intent == expected_intent


def test_unknown_reply_uses_llm_answer_with_real_feature_context(monkeypatch):
    import app.core.llm as core_llm

    calls = []

    def fake_chat_json(system, message, **kwargs):
        calls.append((system, message, kwargs))
        if "의도 분류기" in system:
            return {"intent": "unknown", "topic": None}
        if "토픽 추천기" in system:
            return {"topics": []}
        if "FinBrief 기능 안내" in system:
            assert "토픽 구독" in system
            assert "리포트 설명" in system
            assert "카드뉴스 출처 설명" in system
            return {
                "reply": "환율 흐름이 궁금하다면 USD/KRW 환율을 구독하거나 오늘 시장 요약을 요청해 보세요!",
                "suggested_intent": "add_topic",
            }
        return {}

    monkeypatch.setenv("UPSTAGE_API_KEY", "test")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    monkeypatch.setattr(core_llm, "chat_json", fake_chat_json)

    response = chatbot.handle(_svc(), "discord", "unknown_llm_user", "환율이 왜 움직였어?")

    assert response["intent"] == "unknown"
    assert response["status"] == "blocked"
    assert "USD/KRW 환율" in response["reply"]
    assert "오늘 시장 요약" in response["reply"]
    assert any("FinBrief 기능 안내" in system for system, _, _ in calls)

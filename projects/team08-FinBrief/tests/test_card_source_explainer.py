from datetime import date, datetime, timezone

from app.core.schemas import CardArtifact, NewsDocument, NewsEvidence, TopicAnalysis
from app.repositories.memory import create_memory_repositories
from app.services.card_source_explanation_service import (
    get_or_build_card_source_explanation,
    get_user_card_source_explanations,
)


RUN_DATE = date(2026, 7, 14)


def _card(topic_id: str, *, evidence: list[NewsEvidence] | None = None) -> CardArtifact:
    return CardArtifact(
        card_id=f"card_{topic_id}_20260714",
        topic_id=topic_id,
        run_date=RUN_DATE,
        title="비트코인 카드뉴스",
        analysis=TopicAnalysis(
            topic_id=topic_id,
            run_date=RUN_DATE,
            headline="비트코인 변동성 확대",
            summary="ETF 자금 흐름과 위험자산 선호를 함께 봅니다.",
            key_points=["ETF 자금 흐름", "위험자산 선호"],
            evidence=evidence or [],
        ),
    )


def test_card_source_explanation_uses_card_evidence_and_caches(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("btc")
    evidence = [
        NewsEvidence(
            news_id="news_btc_1",
            title="비트코인 ETF 자금 유입 확대",
            source="연합뉴스",
            url="https://example.com/btc",
            similarity=0.91,
            snippet="ETF 자금 유입이 비트코인 흐름에 영향을 줬습니다.",
        )
    ]
    card = _card(topic.topic_id, evidence=evidence)

    first = get_or_build_card_source_explanation(repos, card=card, topic_name=topic.name)
    second = get_or_build_card_source_explanation(repos, card=card, topic_name=topic.name)

    assert first["cached"] is False
    assert second["cached"] is True
    assert first["evidence_count"] == 1
    assert first["sources"][0]["source"] == "연합뉴스"
    assert "연합뉴스" in first["reply"]


def test_card_source_explanation_falls_back_to_rag_news_when_card_has_no_evidence(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories(
        news_documents=[
            NewsDocument(
                news_id="news_btc_rag",
                title="비트코인 가격 상승",
                source="SBS 뉴스",
                url="https://example.com/btc-rag",
                published_at=datetime(2026, 7, 14, 1, 0, tzinfo=timezone.utc),
                summary="위험자산 선호가 강화됐다는 분석입니다.",
                tags=["비트코인", "BTC"],
            )
        ]
    )
    topic = repos.topics.get_by_normalized_name("btc")
    card = _card(topic.topic_id)

    payload = get_or_build_card_source_explanation(repos, card=card, topic_name=topic.name)

    assert payload["evidence_count"] == 1
    assert payload["sources"][0]["source"] == "SBS 뉴스"
    assert "RAG" in payload["source"] or payload["source"] == "card_evidence_rag"


def test_user_card_source_explanations_returns_subscribed_cards_only(monkeypatch):
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    repos = create_memory_repositories()
    user = repos.users.get_or_create("discord", "source_user")
    btc = repos.topics.get_by_normalized_name("btc")
    nasdaq = repos.topics.get_by_normalized_name("nasdaq")
    repos.subscriptions.add(user.user_id, btc.topic_id, "discord")
    repos.cards.upsert(_card(btc.topic_id))
    repos.cards.upsert(_card(nasdaq.topic_id))

    payload = get_user_card_source_explanations(repos, user_id="source_user", run_date=RUN_DATE)

    assert payload["user_id"] == "source_user"
    assert [item["topic_id"] for item in payload["cards"]] == [btc.topic_id]

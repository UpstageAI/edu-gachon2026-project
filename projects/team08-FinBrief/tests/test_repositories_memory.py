from datetime import date, datetime, timezone

import pytest

from app.core.schemas import CardArtifact, NewsDocument, NewsEvidence, TopicAnalysis
from app.repositories.memory import create_memory_repositories
from app.repositories.protocols import TopicLimitExceededError


def test_memory_repositories_load_default_topic_catalog():
    repos = create_memory_repositories()

    topics = repos.topics.list_catalog()

    assert len(topics) >= 100
    assert repos.topics.get_by_normalized_name("semi").name == "반도체"
    assert any(
        "반도체" in mapping.news_keywords
        for mapping in repos.topics.get_by_normalized_name("semi").source_mapping
    )


def test_memory_subscriptions_enforce_free_tier_limit():
    repos = create_memory_repositories()
    user = repos.users.get_or_create("discord", "u_001")
    topic_ids = [topic.topic_id for topic in repos.topics.list_catalog()]

    for topic_id in topic_ids[: user.max_topics]:
        repos.subscriptions.add(user.user_id, topic_id, "discord")

    with pytest.raises(TopicLimitExceededError) as exc_info:
        repos.subscriptions.add(user.user_id, topic_ids[user.max_topics], "discord")

    assert exc_info.value.code == "TOPIC_LIMIT_EXCEEDED"
    assert len(repos.subscriptions.list_by_user(user.user_id)) == user.max_topics


def test_memory_subscriptions_remove_hides_subscription_from_active_lists():
    repos = create_memory_repositories()
    user = repos.users.get_or_create("discord", "u_001")
    topic = repos.topics.get_by_normalized_name("usdkrw")
    subscription = repos.subscriptions.add(user.user_id, topic.topic_id, "discord")

    removed = repos.subscriptions.remove(user.user_id, topic.topic_id)

    assert removed is True
    assert subscription.subscription_id not in {
        item.subscription_id for item in repos.subscriptions.list_active()
    }
    assert repos.subscriptions.list_by_user(user.user_id) == []


def test_memory_cards_upsert_and_get_by_topic_date():
    repos = create_memory_repositories()
    topic = repos.topics.get_by_normalized_name("btc")
    run_date = date(2026, 7, 9)
    card = CardArtifact(
        card_id="card_btc_20260709",
        topic_id=topic.topic_id,
        run_date=run_date,
        title="비트코인 브리핑",
        analysis=TopicAnalysis(
            topic_id=topic.topic_id,
            run_date=run_date,
            headline="비트코인 변동성 주의",
            summary="비트코인 관련 뉴스와 가격 흐름을 요약합니다.",
            key_points=["ETF 자금 흐름 확인", "거시 금리 변수 확인"],
            disclaimer="본 브리핑은 투자 조언이 아닌 참고용 정보입니다.",
        ),
    )

    repos.cards.upsert(card)

    cached = repos.cards.get(topic.topic_id, run_date)
    assert cached == card


def test_memory_news_match_returns_topic_tagged_evidence_sorted_by_similarity():
    repos = create_memory_repositories(
        news_documents=[
            NewsDocument(
                news_id="n_001",
                title="반도체 업황 회복 기대",
                source="fixture",
                url="https://example.com/semi",
                published_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
                summary="AI 반도체 수요가 회복되고 있습니다.",
                tags=["반도체", "AI 반도체"],
            ),
            NewsDocument(
                news_id="n_002",
                title="환율 변동성 확대",
                source="fixture",
                url="https://example.com/fx",
                published_at=datetime(2026, 7, 9, tzinfo=timezone.utc),
                summary="원달러 환율이 움직였습니다.",
                tags=["환율"],
            ),
        ]
    )
    topic = repos.topics.get_by_normalized_name("semi")

    evidence = repos.news.match(topic, datetime(2026, 7, 8, tzinfo=timezone.utc), 3)

    # 하드 태그필터 제거: 태그 안 겹치는 n_002 도 후보에 포함되되(0.5) 겹치는 n_001(0.9)보다 하위.
    assert evidence == [
        NewsEvidence(
            news_id="n_001",
            title="반도체 업황 회복 기대",
            source="fixture",
            url="https://example.com/semi",
            similarity=0.9,
            snippet="AI 반도체 수요가 회복되고 있습니다.",
        ),
        NewsEvidence(
            news_id="n_002",
            title="환율 변동성 확대",
            source="fixture",
            url="https://example.com/fx",
            similarity=0.5,
            snippet="원달러 환율이 움직였습니다.",
        ),
    ]

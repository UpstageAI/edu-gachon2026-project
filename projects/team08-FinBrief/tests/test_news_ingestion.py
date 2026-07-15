from datetime import datetime, timedelta, timezone

from app.core.schemas import Topic, TopicSourceMapping
from app.tools.news.rss import RawFeedEntry, deduplicate_news_items, filter_recent_news, normalize_feed_entry
from app.tools.news.tagging import tag_news_for_topics


def test_normalize_feed_entry_extracts_stable_news_fields():
    entry = RawFeedEntry(
        source="한국경제",
        title="반도체 업황 회복 기대",
        link="https://example.com/semi",
        published_at="2026-07-09T08:00:00+00:00",
        summary="AI 반도체 수요가 늘고 있습니다.",
    )

    document = normalize_feed_entry(entry)

    assert document.news_id.startswith("news_")
    assert document.title == "반도체 업황 회복 기대"
    assert document.source == "한국경제"
    assert document.url == "https://example.com/semi"
    assert document.published_at == datetime(2026, 7, 9, 8, tzinfo=timezone.utc)
    assert document.summary == "AI 반도체 수요가 늘고 있습니다."


def test_news_filtering_deduplicates_and_keeps_recent_items_only():
    now = datetime(2026, 7, 9, tzinfo=timezone.utc)
    recent = normalize_feed_entry(
        RawFeedEntry(
            source="feed",
            title="환율 변동성 확대",
            link="https://example.com/fx",
            published_at=now.isoformat(),
            summary="원달러 환율이 움직였습니다.",
        )
    )
    duplicate = recent.model_copy(update={"news_id": "news_duplicate"})
    old = recent.model_copy(
        update={
            "news_id": "news_old",
            "url": "https://example.com/old",
            "published_at": now - timedelta(days=5),
        }
    )

    filtered = filter_recent_news(
        deduplicate_news_items([recent, duplicate, old]),
        since=now - timedelta(days=3),
    )

    assert [item.news_id for item in filtered] == [recent.news_id]


def test_tag_news_for_topics_uses_source_mapping_keywords():
    topic = Topic(
        topic_id="topic_semi",
        name="반도체",
        normalized_name="semi",
        type="sector",
        source_mapping=[
            TopicSourceMapping(
                provider="yfinance",
                ticker="SOXX",
                news_keywords=["반도체", "AI 반도체", "엔비디아"],
            )
        ],
    )
    document = normalize_feed_entry(
        RawFeedEntry(
            source="feed",
            title="엔비디아 실적에 AI 반도체 기대 확대",
            link="https://example.com/nvidia",
            published_at="2026-07-09T08:00:00+00:00",
            summary="반도체 업황 회복 기대가 커졌습니다.",
        )
    )

    tagged = tag_news_for_topics([document], [topic])

    assert tagged[0].tags == ["AI 반도체", "반도체", "엔비디아"]

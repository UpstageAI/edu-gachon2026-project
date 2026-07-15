import json
from pathlib import Path

from app.core.schemas import Topic


DEFAULT_TOPICS_PATH = Path("data/default_topics.json")
SUPABASE_SQL_PATH = Path("schemas/supabase.sql")
SEED_TOPICS_SQL_PATH = Path("schemas/seed_topics.sql")


def test_default_topics_parse_as_topic_models():
    payload = json.loads(DEFAULT_TOPICS_PATH.read_text(encoding="utf-8"))

    topics = [Topic.model_validate(item) for item in payload]

    assert len(topics) >= 100
    normalized = {topic.normalized_name for topic in topics}
    # core MVP topics stay in the catalog for downstream tests/demo
    assert {"usdkrw", "us_rate", "nasdaq", "btc", "semi"}.issubset(normalized)
    assert len(normalized) == len(topics)  # normalized_name is unique
    assert all(topic.source_mapping for topic in topics)
    assert all(
        any(mapping.news_keywords for mapping in topic.source_mapping)
        for topic in topics
    )
    # the previously-unused 'keyword' theme type is now populated
    assert any(topic.type == "keyword" for topic in topics)
    # rich, de-duplicated news keyword vocabulary for tagging/matching
    keywords = {
        keyword.casefold()
        for topic in topics
        for mapping in topic.source_mapping
        for keyword in mapping.news_keywords
    }
    assert len(keywords) >= 100


def test_supabase_schema_uses_solar_4096_exact_scan_contract():
    sql = SUPABASE_SQL_PATH.read_text(encoding="utf-8").lower()

    assert "create extension if not exists pgcrypto" in sql
    assert "embedding vector(4096) not null" in sql
    assert "embedding_kind text not null default 'passage'" in sql
    assert "create or replace function match_news" in sql
    assert "query_embedding vector(4096)" in sql
    assert "using gin(tags)" in sql
    assert "using ivfflat" not in sql


def test_seed_topics_sql_is_repeatable_and_matches_default_topics():
    topics_payload = json.loads(DEFAULT_TOPICS_PATH.read_text(encoding="utf-8"))
    seed_sql = SEED_TOPICS_SQL_PATH.read_text(encoding="utf-8").lower()

    assert "on conflict (normalized_name) do update" in seed_sql
    for topic in topics_payload:
        assert topic["normalized_name"] in seed_sql

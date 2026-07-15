from datetime import datetime, timezone

import pytest

from app.core.schemas import NewsDocument, Topic, TopicSourceMapping
from app.repositories.supabase import (
    SupabaseIngestionRepository,
    build_indicator_row,
    build_news_document_row,
)
from app.tools.embedding.upstage import (
    EMBEDDING_DIMENSIONS,
    build_passage_text,
    build_topic_query_text,
    embedding_model_for_kind,
    validate_embedding,
)


class _FakeQuery:
    def __init__(self, table_name: str, recorder: list[tuple[str, str, object]]) -> None:
        self._table_name = table_name
        self._recorder = recorder

    def upsert(self, payload: object, on_conflict: str | None = None) -> "_FakeQuery":
        self._recorder.append((self._table_name, on_conflict or "", payload))
        return self

    def execute(self) -> list[dict[str, object]]:
        return []


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []

    def table(self, table_name: str) -> _FakeQuery:
        return _FakeQuery(table_name, self.calls)


def _topic() -> Topic:
    return Topic(
        topic_id="topic_btc",
        name="비트코인",
        normalized_name="btc",
        type="asset",
        source_mapping=[
            TopicSourceMapping(
                provider="yfinance",
                ticker="BTC-USD",
                news_keywords=["비트코인", "가상자산", "BTC"],
            )
        ],
    )


def _document() -> NewsDocument:
    return NewsDocument(
        news_id="news_btc_001",
        title="비트코인 ETF 자금 유입",
        source="feed",
        url="https://example.com/btc",
        published_at=datetime(2026, 7, 9, 8, tzinfo=timezone.utc),
        summary="가상자산 시장에 ETF 자금이 들어왔습니다.",
        tags=["비트코인", "가상자산"],
    )


def test_build_embedding_texts_include_topic_and_news_context():
    passage = build_passage_text(_document())
    query = build_topic_query_text(_topic())

    assert "제목: 비트코인 ETF 자금 유입" in passage
    assert "태그: 비트코인, 가상자산" in passage
    assert "토픽: 비트코인" in query
    assert "키워드: BTC, 가상자산, 비트코인" in query


def test_validate_embedding_rejects_wrong_dimension():
    with pytest.raises(ValueError, match="4096"):
        validate_embedding([0.1, 0.2], expected_dimensions=EMBEDDING_DIMENSIONS)


def test_embedding_model_for_kind_uses_supported_upstage_models():
    assert embedding_model_for_kind("passage") == "solar-embedding-1-large-passage"
    assert embedding_model_for_kind("query") == "solar-embedding-1-large-query"


def test_supabase_ingestion_repository_upserts_indicator_news_and_embedding_payloads():
    client = _FakeClient()
    repository = SupabaseIngestionRepository(client)
    document = _document()
    embedding = [0.0] * EMBEDDING_DIMENSIONS

    repository.upsert_news_documents([document])
    repository.upsert_news_embeddings(
        [{"news_id": document.news_id, "embedding": embedding, "embedding_model": "test-model"}]
    )

    assert client.calls[0][0] == "news_documents"
    assert client.calls[0][1] == "url"
    assert client.calls[0][2][0]["url"] == "https://example.com/btc"
    assert client.calls[1][0] == "news_embeddings"
    assert client.calls[1][1] == "news_id,embedding_model,embedding_kind"
    assert len(client.calls[1][2][0]["embedding"]) == EMBEDDING_DIMENSIONS


def test_supabase_payload_builders_match_schema_columns():
    document = _document()
    news_row = build_news_document_row(document)

    assert set(news_row) == {
        "source",
        "title",
        "url",
        "published_at",
        "summary",
        "tags",
        "raw_payload",
    }

    indicator_row = build_indicator_row(
        indicator_id="topic_btc:BTC-USD",
        name="비트코인",
        source="yfinance",
        value_date="2026-07-09",
        current_value=100.0,
        previous_value=80.0,
        unit="USD",
    )

    assert indicator_row["change_value"] == 20.0
    assert indicator_row["change_percent"] == 25.0

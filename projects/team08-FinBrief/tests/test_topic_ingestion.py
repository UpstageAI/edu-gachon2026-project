from datetime import date, datetime, timezone

from app.core.schemas import IndicatorValue, NewsDocument, Topic, TopicSourceMapping
from app.services import topic_ingestion
from app.services.topic_ingestion import TopicIngestionOptions, collect_topic_indicators, ingest_topics
from app.tools.embedding.upstage import EMBEDDING_DIMENSIONS, EMBEDDING_PASSAGE_MODEL


class _FakeIngestionRepository:
    def __init__(self) -> None:
        self.indicator_values: list[IndicatorValue] = []
        self.news_documents: list[NewsDocument] = []
        self.news_embeddings: list[dict[str, object]] = []

    def upsert_indicator_values(self, values):
        self.indicator_values.extend(values)
        return [value.model_dump(mode="json") for value in values]

    def upsert_news_documents(self, documents):
        self.news_documents.extend(documents)
        return [
            {"id": f"db_{document.news_id}", "url": str(document.url)}
            for document in documents
        ]

    def upsert_news_embeddings(self, rows):
        self.news_embeddings.extend(rows)
        return rows


class _FakeEmbeddingProvider:
    def embed_passage(self, document: NewsDocument) -> list[float]:
        return [0.1] * EMBEDDING_DIMENSIONS


def _topic_btc() -> Topic:
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


def _news(news_id: str, title: str, summary: str, url: str) -> NewsDocument:
    return NewsDocument(
        news_id=news_id,
        title=title,
        source="rss",
        url=url,
        published_at=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
        summary=summary,
    )


def test_ingest_topics_collects_selected_indicators_news_and_embeddings(monkeypatch):
    topic = _topic_btc()
    run_date = date(2026, 7, 10)
    indicator = IndicatorValue(
        indicator_id="topic_btc",
        name="비트코인",
        source="yfinance",
        value_date=run_date,
        current_value=100.0,
        previous_value=90.0,
        change_percent=11.1,
        unit="USD",
    )
    ingestion = _FakeIngestionRepository()

    monkeypatch.setattr(
        topic_ingestion.yfinance_source,
        "fetch_yfinance_prices",
        lambda **kwargs: [indicator],
    )
    monkeypatch.setattr(
        topic_ingestion.rss,
        "fetch_rss_news",
        lambda: [
            _news("news_btc", "비트코인 ETF 자금 유입", "가상자산 시장 강세", "https://e.test/btc"),
            _news("news_semi", "반도체 재고 조정", "메모리 가격 보합", "https://e.test/semi"),
        ],
    )

    result = ingest_topics(
        [topic],
        ingestion=ingestion,
        run_date=run_date,
        embedding_provider=_FakeEmbeddingProvider(),
    )

    assert result.topic_ids == ["topic_btc"]
    assert result.indicator_rows == 1
    assert result.news_rows == 1
    assert result.embedding_rows == 1
    assert result.skipped_embeddings == 0
    assert ingestion.indicator_values == [indicator]
    assert [str(document.url) for document in ingestion.news_documents] == ["https://e.test/btc"]
    assert ingestion.news_documents[0].tags == ["가상자산", "비트코인"]
    assert ingestion.news_embeddings[0]["news_id"] == "db_news_btc"
    assert ingestion.news_embeddings[0]["embedding_model"] == EMBEDDING_PASSAGE_MODEL
    assert len(ingestion.news_embeddings[0]["embedding"]) == EMBEDDING_DIMENSIONS


def test_ingest_topics_skips_embeddings_when_provider_is_missing(monkeypatch):
    topic = _topic_btc()
    ingestion = _FakeIngestionRepository()
    monkeypatch.setattr(topic_ingestion.rss, "fetch_rss_news", lambda: [
        _news("news_btc", "비트코인 급등", "BTC 현물 수요 증가", "https://e.test/btc2")
    ])

    result = ingest_topics(
        [topic],
        ingestion=ingestion,
        run_date=date(2026, 7, 10),
        embedding_provider=None,
        options=TopicIngestionOptions(include_indicators=False),
    )

    assert result.news_rows == 1
    assert result.embedding_rows == 0
    assert result.skipped_embeddings == 1
    assert ingestion.news_documents
    assert ingestion.news_embeddings == []


def test_collect_topic_indicators_uses_ecos_mapping(monkeypatch):
    run_date = date(2026, 7, 10)
    topic = Topic(
        topic_id="topic_kr_base_rate",
        name="한국 기준금리",
        normalized_name="kr_base_rate",
        type="indicator",
        source_mapping=[
            TopicSourceMapping(
                provider="ecos",
                statistic_code="722Y001",
                cycle="D",
                item_code="0101000",
                news_keywords=["한국은행"],
            )
        ],
    )
    indicator = IndicatorValue(
        indicator_id="topic_kr_base_rate",
        name="한국 기준금리",
        source="ecos",
        value_date=run_date,
        current_value=3.5,
        unit="%",
    )
    called: dict[str, object] = {}

    def _fake_ecos_fetch(**kwargs):
        called.update(kwargs)
        return [indicator]

    monkeypatch.setattr(topic_ingestion.ecos, "fetch_ecos_statistic_search", _fake_ecos_fetch)

    values = collect_topic_indicators(topic, run_date)

    assert values == [indicator]
    assert called["statistic_code"] == "722Y001"
    assert called["cycle"] == "D"
    assert called["item_code"] == "0101000"
    assert called["indicator_id"] == "topic_kr_base_rate"


def test_ingest_topics_records_missing_indicator_when_source_returns_empty(monkeypatch):
    topic = _topic_btc()
    monkeypatch.setattr(topic_ingestion.yfinance_source, "fetch_yfinance_prices", lambda **kwargs: [])

    result = ingest_topics(
        [topic],
        ingestion=_FakeIngestionRepository(),
        run_date=date(2026, 7, 10),
        options=TopicIngestionOptions(include_news=False, include_embeddings=False),
    )

    assert result.indicator_rows == 0
    assert result.missing_indicators == ["topic_btc"]

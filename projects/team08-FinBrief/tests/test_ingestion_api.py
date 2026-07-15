from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_embedding_provider,
    get_ingestion_repository,
    get_repository_bundle,
    reset_repository_bundle_cache,
)
from app.core.config import Settings
from app.core.schemas import IndicatorValue, NewsDocument
from app.main import create_app
from app.repositories.memory import create_memory_repositories
from app.services import topic_ingestion
from app.tools.embedding.upstage import EMBEDDING_DIMENSIONS


class _FakeIngestionRepository:
    def __init__(self) -> None:
        self.indicator_values = []
        self.news_documents = []
        self.news_embeddings = []

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
        return [0.2] * EMBEDDING_DIMENSIONS


def _news() -> NewsDocument:
    return NewsDocument(
        news_id="news_btc_api",
        title="비트코인 현물 ETF 거래량 증가",
        source="rss",
        url="https://api.test/btc",
        published_at=datetime(2026, 7, 10, 8, tzinfo=timezone.utc),
        summary="BTC와 가상자산 관련 자금 유입이 이어졌습니다.",
    )


def _client(monkeypatch, tmp_path, repos, ingestion) -> TestClient:
    reset_repository_bundle_cache()
    monkeypatch.setenv("FINBRIEF_LLM_STUB", "1")
    monkeypatch.setenv("FINBRIEF_IMAGE_STUB", "1")
    monkeypatch.setenv("FINBRIEF_OUT", str(tmp_path / "cards"))
    monkeypatch.setenv("FINBRIEF_IMG_OUT", str(tmp_path / "images"))
    app = create_app(Settings(app_env="test", enable_mock_data=True))
    app.dependency_overrides[get_repository_bundle] = lambda: repos
    app.dependency_overrides[get_ingestion_repository] = lambda: ingestion
    app.dependency_overrides[get_embedding_provider] = lambda: _FakeEmbeddingProvider()
    return TestClient(app)


def test_ingest_topic_endpoint_stores_selected_topic_data(monkeypatch, tmp_path):
    repos = create_memory_repositories()
    ingestion = _FakeIngestionRepository()
    run_date = date(2026, 7, 10)
    indicator = IndicatorValue(
        indicator_id="topic_btc",
        name="비트코인",
        source="yfinance",
        value_date=run_date,
        current_value=100.0,
        unit="USD",
    )
    monkeypatch.setattr(
        topic_ingestion.yfinance_source,
        "fetch_yfinance_prices",
        lambda **kwargs: [indicator],
    )
    monkeypatch.setattr(topic_ingestion.rss, "fetch_rss_news", lambda: [_news()])
    client = _client(monkeypatch, tmp_path, repos, ingestion)

    response = client.post(
        "/api/v1/topics/topic_btc/ingest",
        json={
            "run_date": "2026-07-10",
            "include_indicators": True,
            "include_news": True,
            "include_embeddings": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["topic_ids"] == ["topic_btc"]
    assert payload["indicator_rows"] == 1
    assert payload["news_rows"] == 1
    assert payload["embedding_rows"] == 1
    assert [str(document.url) for document in ingestion.news_documents] == ["https://api.test/btc"]


def test_ingest_topic_endpoint_returns_404_for_unknown_topic(monkeypatch, tmp_path):
    repos = create_memory_repositories()
    client = _client(monkeypatch, tmp_path, repos, _FakeIngestionRepository())

    response = client.post("/api/v1/topics/topic_missing/ingest", json={"dry_run": True})

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "NOT_FOUND"


def test_run_report_with_refresh_data_preloads_active_subscription_topics(monkeypatch, tmp_path):
    repos = create_memory_repositories()
    repos.users.get_or_create("discord", "refresh_user")
    repos.subscriptions.add("refresh_user", "topic_btc", "discord")
    ingestion = _FakeIngestionRepository()
    run_date = date(2026, 7, 10)
    indicator = IndicatorValue(
        indicator_id="topic_btc",
        name="비트코인",
        source="yfinance",
        value_date=run_date,
        current_value=100.0,
        unit="USD",
    )
    monkeypatch.setattr(
        topic_ingestion.yfinance_source,
        "fetch_yfinance_prices",
        lambda **kwargs: [indicator],
    )
    monkeypatch.setattr(topic_ingestion.rss, "fetch_rss_news", lambda: [_news()])
    client = _client(monkeypatch, tmp_path, repos, ingestion)

    response = client.post(
        "/api/v1/reports/run",
        json={"run_date": "2026-07-10", "dry_run": True, "refresh_data": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ingestion"]["topic_ids"] == ["topic_btc"]
    assert payload["ingestion"]["indicator_rows"] == 1
    assert payload["ingestion"]["news_rows"] == 1
    assert ingestion.indicator_values
    assert ingestion.news_documents

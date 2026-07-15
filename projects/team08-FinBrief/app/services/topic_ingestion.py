"""Topic-scoped external data ingestion service."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.agents import rag
from app.core.schemas import IndicatorValue, NewsDocument, Topic
from app.tools.data_sources import ecos, fred, yfinance_source
from app.tools.embedding.upstage import EMBEDDING_PASSAGE_MODEL, validate_embedding
from app.tools.news import rss, tagging


class TopicIngestionOptions(BaseModel):
    include_indicators: bool = True
    include_news: bool = True
    include_embeddings: bool = True
    dry_run: bool = False
    since_days: int = Field(default=rag.RAG_SINCE_DAYS, ge=0)   # 0=당일만


class TopicIngestionResult(BaseModel):
    topic_ids: list[str]
    run_date: date
    indicator_rows: int = 0
    news_rows: int = 0
    embedding_rows: int = 0
    skipped_embeddings: int = 0
    missing_indicators: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


def _indicator_provider_exists(topic: Topic) -> bool:
    return any(mapping.provider in {"fred", "yfinance", "ecos"} for mapping in topic.source_mapping)


def _unit_for_ticker(ticker: str) -> str | None:
    """yfinance 티커로 표시 단위 추론(source_mapping 에 unit 이 없을 때).
    지수는 pt, 한국 종목은 원, 그 외(미국 종목/ETF)는 달러. 환율(=X)은 이름/카테고리로 처리."""
    t = str(ticker or "").upper()
    if t.startswith("^"):
        return "pt"                       # 지수(^IXIC, ^GSPC, ^KS11 …)
    if t.endswith("=X"):
        return None                       # 환율 → _display_unit 카테고리 처리(원)
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "원"                       # 한국 종목
    if t.endswith("-USD") or t.endswith("=F"):
        return "달러"                     # 크립토/선물
    return "달러"                         # 그 외 = 미국 종목/ETF


def collect_topic_indicators(topic: Topic, run_date: date) -> list[IndicatorValue]:
    """Collect indicator values for one topic using its source mappings."""

    values: list[IndicatorValue] = []
    start_date = run_date - timedelta(days=7)
    for mapping in topic.source_mapping:
        try:
            if mapping.provider == "fred" and mapping.series_id:
                values.extend(
                    fred.fetch_fred_observations(
                        series_id=mapping.series_id,
                        indicator_id=topic.topic_id,
                        name=topic.name,
                        start_date=start_date,
                        end_date=run_date,
                    )
                )
            elif mapping.provider == "yfinance" and mapping.ticker:
                values.extend(
                    yfinance_source.fetch_yfinance_prices(
                        ticker=mapping.ticker,
                        indicator_id=topic.topic_id,
                        name=topic.name,
                        unit=getattr(mapping, "unit", None) or _unit_for_ticker(mapping.ticker),
                    )
                )
            elif (
                mapping.provider == "ecos"
                and mapping.statistic_code
                and mapping.cycle
                and mapping.item_code
            ):
                values.extend(
                    ecos.fetch_ecos_statistic_search(
                        statistic_code=mapping.statistic_code,
                        cycle=mapping.cycle,
                        start_date=start_date,
                        end_date=run_date,
                        item_code=mapping.item_code,
                        indicator_id=topic.topic_id,
                        name=topic.name,
                    )
                )
        except Exception:
            continue
    return values


def collect_relevant_news(topics: Sequence[Topic], *, run_date: date, since_days: int) -> list[NewsDocument]:
    """Fetch RSS news and keep only documents matched to selected topic keywords."""

    since = rag.since_for(run_date, days=since_days)
    documents = rss.fetch_rss_news()
    documents = rss.filter_recent_news(documents, since=since)
    tagged = tagging.tag_news_for_topics(list(documents), list(topics), include_general_market=False)
    selected_keywords = {
        keyword
        for topic in topics
        for keyword in tagging.topic_keywords(topic)
    }
    if not selected_keywords:
        return []
    return [
        document
        for document in tagged
        if set(document.tags).intersection(selected_keywords)
    ]


def news_id_by_url(rows: Any) -> dict[str, str]:
    """Build url -> database news id mapping from Supabase upsert response rows."""

    if not isinstance(rows, list):
        return {}
    mapping: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("url") and row.get("id"):
            mapping[str(row["url"])] = str(row["id"])
    return mapping


def embed_news_documents(
    documents: Sequence[NewsDocument],
    *,
    id_by_url: dict[str, str],
    embedding_provider: Any | None,
) -> tuple[list[dict[str, Any]], int, list[str]]:
    """Create passage embedding rows for already-upserted news documents."""

    if embedding_provider is None:
        return [], len(documents), []

    rows: list[dict[str, Any]] = []
    skipped = 0
    errors: list[str] = []
    for document in documents:
        news_id = id_by_url.get(str(document.url))
        if news_id is None:
            skipped += 1
            errors.append(f"missing news id for url: {document.url}")
            continue
        try:
            rows.append(
                {
                    "news_id": news_id,
                    "embedding": validate_embedding(embedding_provider.embed_passage(document)),
                    "embedding_model": EMBEDDING_PASSAGE_MODEL,
                    "embedding_kind": "passage",
                }
            )
        except Exception as exc:
            skipped += 1
            errors.append(f"embedding skipped for {document.news_id}: {exc}")
    return rows, skipped, errors


def ingest_topics(
    topics: Sequence[Topic],
    *,
    ingestion: Any | None,
    run_date: date,
    embedding_provider: Any | None = None,
    options: TopicIngestionOptions | None = None,
) -> TopicIngestionResult:
    """Collect and store selected topic indicators, news documents, and embeddings."""

    runtime_options = options or TopicIngestionOptions()
    selected_topics = list(topics)
    result = TopicIngestionResult(
        topic_ids=[topic.topic_id for topic in selected_topics],
        run_date=run_date,
    )

    if runtime_options.include_indicators:
        indicator_values: list[IndicatorValue] = []
        for topic in selected_topics:
            values = collect_topic_indicators(topic, run_date)
            if not values and _indicator_provider_exists(topic):
                result.missing_indicators.append(topic.topic_id)
            indicator_values.extend(values)
        result.indicator_rows = len(indicator_values)
        if indicator_values and ingestion is not None and not runtime_options.dry_run:
            ingestion.upsert_indicator_values(indicator_values)

    if not runtime_options.include_news:
        return result

    documents = collect_relevant_news(
        selected_topics,
        run_date=run_date,
        since_days=runtime_options.since_days,
    )
    result.news_rows = len(documents)
    if not documents:
        return result

    upsert_rows: Any = []
    if ingestion is not None and not runtime_options.dry_run:
        upsert_rows = ingestion.upsert_news_documents(documents)
    id_by_url = news_id_by_url(upsert_rows)
    if runtime_options.dry_run:
        id_by_url = {str(document.url): document.news_id for document in documents}

    if runtime_options.include_embeddings:
        embedding_rows, skipped, errors = embed_news_documents(
            documents,
            id_by_url=id_by_url,
            embedding_provider=embedding_provider,
        )
        result.skipped_embeddings += skipped
        result.errors.extend(errors)
        result.embedding_rows = len(embedding_rows)
        if embedding_rows and ingestion is not None and not runtime_options.dry_run:
            ingestion.upsert_news_embeddings(embedding_rows)

    return result

"""Shared schema contracts for the FinBrief MVP.

These models define data boundaries before implementation logic is added.
They are intentionally small and map directly to the final planning documents.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


TopicType = Literal["indicator", "keyword", "sector", "asset"]
UserTier = Literal["free", "paid"]
DeliveryChannel = Literal["discord", "slack"]
DeliveryStatus = Literal["pending", "sent", "failed", "retrying", "skipped", "dry_run"]
RunStatus = Literal["queued", "running", "completed", "partial_success", "failed"]


class StrictModel(BaseModel):
    """Base model that rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ChannelConfig(StrictModel):
    channel: DeliveryChannel
    webhook_url: str = Field(min_length=1)
    enabled: bool = True


class UserProfile(StrictModel):
    user_id: str = Field(min_length=1)
    display_name: str | None = None
    tier: UserTier = "free"
    max_topics: int = Field(default=5, ge=1)
    channels: list[ChannelConfig] = Field(default_factory=list)
    created_at: datetime | None = None


class TopicSourceMapping(StrictModel):
    provider: Literal["fred", "yfinance", "ecos", "news_rss", "rag"]
    series_id: str | None = None
    ticker: str | None = None
    statistic_code: str | None = None
    cycle: str | None = None
    item_code: str | None = None
    query: str | None = None
    news_keywords: list[str] = Field(default_factory=list)
    notes: str | None = None


class Topic(StrictModel):
    topic_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    normalized_name: str = Field(min_length=1)
    type: TopicType
    source_mapping: list[TopicSourceMapping]
    created_at: datetime | None = None


class Subscription(StrictModel):
    subscription_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    channel: DeliveryChannel
    active: bool = True
    discord_channel_id: str | None = None
    created_at: datetime | None = None


class IndicatorValue(StrictModel):
    indicator_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source: Literal["fred", "yfinance", "ecos", "fixture"]
    value_date: date
    current_value: float
    previous_value: float | None = None
    change_value: float | None = None
    change_percent: float | None = None
    unit: str | None = None
    missing: bool = False


class NewsDocument(StrictModel):
    news_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: HttpUrl | str
    published_at: datetime
    summary: str | None = None
    tags: list[str] = Field(default_factory=list)


class NewsEvidence(StrictModel):
    news_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source: str = Field(min_length=1)
    url: HttpUrl | str
    similarity: float | None = Field(default=None, ge=0.0, le=1.0)
    snippet: str


class TopicAnalysis(StrictModel):
    topic_id: str = Field(min_length=1)
    run_date: date
    headline: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    key_points: list[str] = Field(min_length=1)
    evidence: list[NewsEvidence] = Field(default_factory=list)
    disclaimer: str = Field(default="본 브리핑은 투자 조언이 아닌 참고용 정보입니다.")


class CardArtifact(StrictModel):
    card_id: str = Field(min_length=1)
    topic_id: str = Field(min_length=1)
    run_date: date
    title: str = Field(min_length=1)
    image_url: str | None = None
    report_url: str | None = None
    analysis: TopicAnalysis
    cached: bool = False
    created_at: datetime | None = None


class DeliveryLog(StrictModel):
    delivery_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    topic_id: str | None = None
    card_id: str | None = None
    channel: DeliveryChannel
    status: DeliveryStatus
    attempts: int = Field(default=0, ge=0)
    error_code: str | None = None
    sent_at: datetime | None = None


class FullReport(StrictModel):
    report_id: str = Field(min_length=1)
    run_date: date
    indicators: list[IndicatorValue]
    top_news: list[NewsDocument]
    missing_indicators: list[str] = Field(default_factory=list)
    report_url: str | None = None
    disclaimer: str = Field(default="본 브리핑은 투자 조언이 아닌 참고용 정보입니다.")


class EvaluationResult(StrictModel):
    eval_name: str = Field(min_length=1)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    passed: bool
    result: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None
    run_date: date | None = None
    trace_id: str | None = None
    topic_id: str | None = None


class BatchRunResult(StrictModel):
    run_id: str = Field(min_length=1)
    run_date: date
    status: RunStatus
    report: FullReport | None = None
    generated_cards: list[CardArtifact] = Field(default_factory=list)
    delivery_results: list[DeliveryLog] = Field(default_factory=list)
    eval_results: list[EvaluationResult] = Field(default_factory=list)
    trace_id: str | None = None
    errors: list[str] = Field(default_factory=list)


class AdminCommandRequest(StrictModel):
    user_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class AdminCommandResponse(StrictModel):
    intent: Literal[
        "add_topic",
        "list_topics",
        "delete_topic",
        "tier_status",
        "help",
        "recommend_topics",
        "explain_report",
        "explain_card_sources",
        "clarify_topic",
        "unknown",
    ]
    status: Literal["completed", "blocked", "failed"]
    reply: str
    topic: Topic | None = None
    subscription: Subscription | None = None
    error_code: str | None = None

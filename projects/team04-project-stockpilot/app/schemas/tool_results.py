"""ToolExecutor가 반환하는 안정적인 Pydantic 출력 계약."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.tools import MarketDirection, PricePeriod, ToolName

Number = int | float


class ToolResultModel(BaseModel):
    """Mock과 실제 결과 모두에 적용되는 엄격한 출력 규칙."""

    model_config = ConfigDict(extra="forbid")


class OHLCVPoint(ToolResultModel):
    date: str
    open: Number
    high: Number
    low: Number
    close: Number
    volume: Number
    change_pct: Number


class Fundamentals(ToolResultModel):
    date: str
    bps: Number
    per: Number
    pbr: Number
    eps: Number
    div: Number
    dps: Number


class StockPriceData(ToolResultModel):
    ticker: str
    name: str
    as_of: str
    snapshot_at: str | None = None
    current_price: Number
    previous_close: Number | None
    change: Number | None
    change_pct: Number | None
    period: PricePeriod
    ohlcv: list[OHLCVPoint]
    fundamentals: Fundamentals | None
    fundamentals_available: bool


class StockPriceResult(ToolResultModel):
    success: Literal[True] = True
    data: StockPriceData


class NewsItem(ToolResultModel):
    title: str
    description: str
    original_link: str
    link: str
    source_domain: str
    published_at: str | None
    published_timestamp: Number
    query: str
    relevance_score: int
    matched_keywords: list[str]
    direct_company_match: bool
    company_mentioned: bool
    market_context_match: bool
    direction: MarketDirection
    direction_keywords: list[str]
    opposite_direction_keywords: list[str]
    has_direction_evidence: bool
    issue_score: Number
    ranking_tier: int
    filter_fallback: bool | None = None
    source: str
    url: str
    sentiment: Literal["호재", "악재", "중립"]
    reason: str


class NewsData(ToolResultModel):
    company: str
    direction: MarketDirection
    news: list[NewsItem]


class NewsResult(ToolResultModel):
    success: Literal[True] = True
    data: NewsData


class DisclosureItem(ToolResultModel):
    receipt_no: str
    corp_code: str
    corp_name: str
    stock_code: str | None
    report_name: str
    received_date: str
    source_url: str
    title: str
    date: str
    url: str


class DisclosureData(ToolResultModel):
    ticker: str
    disclosures: list[DisclosureItem]


class DisclosureResult(ToolResultModel):
    success: Literal[True] = True
    data: DisclosureData


class PositiveNewsStock(ToolResultModel):
    ticker: str
    positive_score: Number
    evidence_count: int
    change_pct: Number | None = None
    top_news: str
    url: str
    news: list[NewsItem] | None = None


class PositiveNewsStocksData(ToolResultModel):
    stocks: list[PositiveNewsStock]


class PositiveNewsStocksResult(ToolResultModel):
    success: Literal[True] = True
    data: PositiveNewsStocksData


class WatchlistData(ToolResultModel):
    ticker: str
    name: str
    session_id: str
    saved: bool
    id: int | None = None
    created_at: str | None = None


class WatchlistResult(ToolResultModel):
    success: Literal[True] = True
    data: WatchlistData


class GlossaryTerm(ToolResultModel):
    id: int | None = None
    term: str
    definition: str
    category: str | None = None
    aliases: list[str]
    difficulty: str
    example: str | None = None
    source_url: str | None = None
    metadata: dict[str, object]
    match_score: int
    created_at: str | None = None
    updated_at: str | None = None


class GlossaryTermData(ToolResultModel):
    query: str
    terms: list[GlossaryTerm]


class GlossaryTermResult(ToolResultModel):
    success: Literal[True] = True
    data: GlossaryTermData


class ToolErrorResult(ToolResultModel):
    success: Literal[False] = False
    error: str
    error_type: str | None = None


TOOL_RESULT_SCHEMAS: dict[ToolName, type[ToolResultModel]] = {
    "get_stock_price": StockPriceResult,
    "get_news": NewsResult,
    "get_disclosure": DisclosureResult,
    "find_positive_news_stocks": PositiveNewsStocksResult,
    "add_watchlist": WatchlistResult,
    "lookup_glossary_term": GlossaryTermResult,
}

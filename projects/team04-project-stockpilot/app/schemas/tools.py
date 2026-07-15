"""LLM이 호출할 StockPilot 도구의 Pydantic 입력 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ToolName = Literal[
    "get_stock_price",
    "get_news",
    "get_disclosure",
    "find_positive_news_stocks",
    "add_watchlist",
    "lookup_glossary_term",
]
MarketDirection = Literal["down", "up", "neutral"]
PricePeriod = Literal["1w", "1m", "3m", "6m", "1y"]


class ToolArgs(BaseModel):
    """모든 도구 입력에 공통으로 적용할 검증 규칙."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class GetStockPriceArgs(ToolArgs):
    """주가·일봉·재무지표 조회 입력."""

    ticker: str = Field(
        min_length=1,
        max_length=50,
        description="조회할 국내 종목명 또는 6자리 종목코드. 예: 삼성전자, 005930",
        examples=["삼성전자"],
    )
    period: PricePeriod = Field(
        default="3m",
        description="일봉 조회 기간",
    )


class GetNewsArgs(ToolArgs):
    """기업 관련 최신 뉴스 조회 입력."""

    company: str = Field(
        min_length=1,
        max_length=50,
        description="뉴스를 조회할 정확한 회사명. 예: 삼성전자",
        examples=["삼성전자"],
    )
    days: int = Field(
        default=7,
        ge=1,
        le=30,
        description="현재부터 과거 며칠까지 뉴스를 조회할지 지정",
    )
    direction: MarketDirection = Field(
        default="neutral",
        description=(
            "질문의 주가 방향. 하락 원인은 down, 상승 원인은 up, 방향이 없으면 neutral"
        ),
    )
    limit: int = Field(
        default=15,
        ge=1,
        le=50,
        description="반환할 최대 뉴스 개수",
    )


class GetDisclosureArgs(ToolArgs):
    """OpenDART 최근 공시 조회 입력."""

    ticker: str = Field(
        min_length=1,
        max_length=50,
        description="조회할 회사명 또는 6자리 종목코드",
        examples=["005930"],
    )
    limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="반환할 최대 공시 개수",
    )


class FindPositiveNewsStocksArgs(ToolArgs):
    """상승 근거 뉴스 종목 선별 입력."""

    universe: list[str] | None = Field(
        default=None,
        min_length=1,
        max_length=30,
        description="검색할 회사명 목록. 생략하면 기본 10개 종목을 사용",
    )
    days: int = Field(
        default=3,
        ge=1,
        le=14,
        description="최근 뉴스 조회 기간",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=10,
        description="반환할 최대 종목 개수",
    )


class AddWatchlistArgs(ToolArgs):
    """관심 종목 저장 입력."""

    ticker: str = Field(
        min_length=1,
        max_length=50,
        description="관심 종목에 저장할 회사명 또는 6자리 종목코드",
        examples=["삼성전자"],
    )


class LookupGlossaryTermArgs(ToolArgs):
    """Investment glossary exact/alias lookup input."""

    query: str = Field(
        min_length=1,
        max_length=100,
        description="Investment term or question. Examples: PER, PBR, CB",
        examples=["PER"],
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of glossary matches to return",
    )


TOOL_ARG_SCHEMAS: dict[ToolName, type[ToolArgs]] = {
    "get_stock_price": GetStockPriceArgs,
    "get_news": GetNewsArgs,
    "get_disclosure": GetDisclosureArgs,
    "find_positive_news_stocks": FindPositiveNewsStocksArgs,
    "add_watchlist": AddWatchlistArgs,
    "lookup_glossary_term": LookupGlossaryTermArgs,
}

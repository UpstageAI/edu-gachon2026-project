"""Solar에 전달할 LangChain StructuredTool 레지스트리."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool, StructuredTool

from app.schemas.tools import (
    AddWatchlistArgs,
    FindPositiveNewsStocksArgs,
    GetDisclosureArgs,
    GetNewsArgs,
    GetStockPriceArgs,
    LookupGlossaryTermArgs,
    MarketDirection,
    PricePeriod,
)
from app.tools.executor import ToolExecutor


def build_stockpilot_tools(
    executor: ToolExecutor | None = None,
    *,
    session_id: str = "default",
) -> list[BaseTool]:
    """Pydantic JSON Schema가 포함된 LLM 호출 가능 도구를 생성합니다."""
    tool_executor = executor or ToolExecutor()

    async def get_stock_price(
        ticker: str,
        period: PricePeriod = "3m",
    ) -> dict:
        return await tool_executor.execute(
            "get_stock_price",
            {"ticker": ticker, "period": period},
            session_id=session_id,
        )

    async def get_news(
        company: str,
        days: int = 7,
        direction: MarketDirection = "neutral",
        limit: int = 15,
    ) -> dict:
        return await tool_executor.execute(
            "get_news",
            {
                "company": company,
                "days": days,
                "direction": direction,
                "limit": limit,
            },
            session_id=session_id,
        )

    async def get_disclosure(ticker: str, limit: int = 10) -> dict:
        return await tool_executor.execute(
            "get_disclosure",
            {"ticker": ticker, "limit": limit},
            session_id=session_id,
        )

    async def find_positive_news_stocks(
        universe: list[str] | None = None,
        days: int = 3,
        limit: int = 5,
    ) -> dict:
        return await tool_executor.execute(
            "find_positive_news_stocks",
            {"universe": universe, "days": days, "limit": limit},
            session_id=session_id,
        )

    async def add_watchlist(ticker: str) -> dict:
        return await tool_executor.execute(
            "add_watchlist",
            {"ticker": ticker},
            session_id=session_id,
        )

    async def lookup_glossary_term(query: str, limit: int = 5) -> dict:
        return await tool_executor.execute(
            "lookup_glossary_term",
            {"query": query, "limit": limit},
            session_id=session_id,
        )

    definitions: list[tuple[str, str, type, object]] = [
        (
            "get_stock_price",
            "국내 종목의 현재가, 등락률, 일봉과 재무지표를 조회합니다.",
            GetStockPriceArgs,
            get_stock_price,
        ),
        (
            "get_news",
            "기업의 최신 뉴스를 조회하고 상승·하락 원인 후보를 우선 정렬합니다.",
            GetNewsArgs,
            get_news,
        ),
        (
            "get_disclosure",
            "회사명 또는 종목코드로 최근 OpenDART 공시를 조회합니다.",
            GetDisclosureArgs,
            get_disclosure,
        ),
        (
            "find_positive_news_stocks",
            "기본 또는 지정된 종목 목록에서 상승 근거 뉴스가 있는 종목을 찾습니다.",
            FindPositiveNewsStocksArgs,
            find_positive_news_stocks,
        ),
        (
            "add_watchlist",
            "현재 세션의 관심 종목을 Supabase에 저장합니다.",
            AddWatchlistArgs,
            add_watchlist,
        ),
        (
            "lookup_glossary_term",
            "Look up investment terms in glossary_terms before using fuzzy RAG.",
            LookupGlossaryTermArgs,
            lookup_glossary_term,
        ),
    ]

    return [
        StructuredTool.from_function(
            coroutine=coroutine,
            name=name,
            description=description,
            args_schema=args_schema,
        )
        for name, description, args_schema, coroutine in definitions
    ]


def bind_stockpilot_tools(
    llm: Any,
    executor: ToolExecutor | None = None,
    *,
    session_id: str = "default",
) -> Any:
    """Solar 등 tool-calling LLM에 StockPilot JSON Schema를 전달합니다."""
    tools = build_stockpilot_tools(executor, session_id=session_id)
    return llm.bind_tools(tools)

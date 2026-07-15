from app.repositories import disclosure, glossary, news, price, watchlist
from app.schemas.tool_results import (
    DisclosureResult,
    GlossaryTermResult,
    NewsResult,
    StockPriceResult,
    WatchlistResult,
)
from app.tools import executor as executor_module
from app.tools.executor import ToolExecutor
from tests.fixtures.tool_responses import (
    directional_news_item,
    disclosure_item,
    glossary_term_item,
    stock_snapshot,
    watchlist_item,
)


async def test_executor_connects_stock_price_repository(monkeypatch):
    async def fake_snapshot(ticker: str, *, period: str):
        result = stock_snapshot()
        result["name"] = ticker
        result["period"] = period
        return result

    monkeypatch.setattr(price, "get_stock_snapshot", fake_snapshot)

    result = await ToolExecutor().execute(
        "get_stock_price",
        {"ticker": "삼성전자", "period": "1m"},
    )

    assert result["success"] is True
    assert result["data"]["ticker"] == "005930"
    assert result["data"]["period"] == "1m"
    StockPriceResult.model_validate(result)


async def test_executor_connects_directional_news_repository(monkeypatch):
    async def fake_issue_news(company: str, **kwargs):
        assert company == "삼성전자"
        assert kwargs["direction"] == "down"
        return [directional_news_item()]

    monkeypatch.setattr(news, "get_stock_issue_news", fake_issue_news)

    result = await ToolExecutor().execute(
        "get_news",
        {"company": "삼성전자", "direction": "down"},
    )

    item = result["data"]["news"][0]
    assert item["sentiment"] == "악재"
    assert item["url"] == "https://example.com/down"
    assert item["reason"] == "급락, 우려"
    NewsResult.model_validate(result)


async def test_positive_news_screener_reuses_short_cache(monkeypatch):
    with executor_module._SCREENER_CACHE_LOCK:
        executor_module._SCREENER_CACHE.clear()

    calls = 0

    async def fake_change_pct(company: str):
        return {"삼성전자": 1.2, "SK하이닉스": 0.8}[company]

    async def fake_issue_news(company: str, **kwargs):
        nonlocal calls
        calls += 1
        item = directional_news_item()
        item.update(
            {
                "title": f"{company} 호재 상승",
                "description": "신규 수주와 실적 개선 기대가 있다.",
                "direction": "up",
                "direction_keywords": ["상승", "수주"],
                "opposite_direction_keywords": [],
                "has_direction_evidence": True,
                "issue_score": 20,
                "ranking_tier": 3,
            }
        )
        return [item]

    monkeypatch.setattr(price, "get_change_pct", fake_change_pct)
    monkeypatch.setattr(news, "get_stock_issue_news", fake_issue_news)

    executor = ToolExecutor()
    first = await executor.find_positive_news_stocks(
        universe=["삼성전자", "SK하이닉스"],
        days=3,
        limit=2,
    )
    second = await executor.find_positive_news_stocks(
        universe=["삼성전자", "SK하이닉스"],
        days=3,
        limit=2,
    )

    assert calls == 2
    assert second == first
    assert first["data"]["stocks"][0]["news"]

    second["data"]["stocks"][0]["ticker"] = "mutated"
    third = await executor.find_positive_news_stocks(
        universe=["삼성전자", "SK하이닉스"],
        days=3,
        limit=2,
    )
    assert third["data"]["stocks"][0]["ticker"] != "mutated"

    with executor_module._SCREENER_CACHE_LOCK:
        executor_module._SCREENER_CACHE.clear()


async def test_executor_connects_disclosure_repository(monkeypatch):
    async def fake_disclosures(corp: str, limit: int):
        assert corp == "005930"
        assert limit == 3
        return [disclosure_item()]

    monkeypatch.setattr(disclosure, "get_recent_disclosures", fake_disclosures)

    result = await ToolExecutor().execute(
        "get_disclosure",
        {"ticker": "005930", "limit": 3},
    )

    item = result["data"]["disclosures"][0]
    assert item["title"] == "사업보고서 (2025.12)"
    assert item["date"] == "20260317"
    DisclosureResult.model_validate(result)


def test_disclosure_tool_has_budget_for_unknown_corporation_lookup():
    assert executor_module.TOOL_TIMEOUT_SECONDS["get_disclosure"] >= 45


async def test_executor_connects_watchlist_repository(monkeypatch):
    async def fake_resolve_ticker(ticker: str):
        return "005930"

    async def fake_add_watchlist(**kwargs):
        item = watchlist_item()
        assert item["ticker"] == kwargs["ticker"]
        assert item["session_id"] == kwargs["session_id"]
        return item

    monkeypatch.setattr(price, "resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(watchlist, "add_watchlist", fake_add_watchlist)

    result = await ToolExecutor().execute(
        "add_watchlist",
        {"ticker": "삼성전자"},
        session_id="session-1",
    )

    assert result["success"] is True
    assert result["data"]["ticker"] == "005930"
    assert result["data"]["session_id"] == "session-1"
    WatchlistResult.model_validate(result)


async def test_executor_connects_glossary_repository(monkeypatch):
    async def fake_search_terms(query: str, *, limit: int):
        assert query == "PER이 뭐야?"
        assert limit == 3
        return [glossary_term_item()]

    monkeypatch.setattr(glossary, "search_or_research_terms", fake_search_terms)

    result = await ToolExecutor().execute(
        "lookup_glossary_term",
        {"query": "PER이 뭐야?", "limit": 3},
    )

    assert result["success"] is True
    assert result["data"]["terms"][0]["term"] == "PER"
    GlossaryTermResult.model_validate(result)


async def test_executor_returns_structured_error(monkeypatch):
    async def fail(*args, **kwargs):
        raise RuntimeError("시세 서비스 오류")

    monkeypatch.setattr(price, "get_stock_snapshot", fail)

    result = await ToolExecutor().execute(
        "get_stock_price",
        {"ticker": "삼성전자"},
    )

    assert result == {
        "success": False,
        "error": "시세 서비스 오류",
        "error_type": "RuntimeError",
    }

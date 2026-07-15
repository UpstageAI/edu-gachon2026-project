from app.schemas.tool_results import (
    DisclosureItem,
    GlossaryTerm,
    NewsItem,
    StockPriceData,
    WatchlistData,
)
from app.tools.executor import _normalize_news_item
from tests.fixtures.tool_responses import (
    directional_news_item,
    disclosure_item,
    glossary_term_item,
    stock_snapshot,
    watchlist_item,
)


def test_price_mock_matches_actual_normalized_contract():
    validated = StockPriceData.model_validate(stock_snapshot())

    assert set(validated.model_dump()) == {
        "ticker",
        "name",
        "as_of",
        "snapshot_at",
        "current_price",
        "previous_close",
        "change",
        "change_pct",
        "period",
        "ohlcv",
        "fundamentals",
        "fundamentals_available",
    }
    assert set(validated.ohlcv[0].model_dump()) == {
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "change_pct",
    }


def test_news_mock_matches_actual_normalized_contract():
    normalized = _normalize_news_item(directional_news_item(), "down")
    validated = NewsItem.model_validate(normalized)

    assert validated.direction == "down"
    assert validated.sentiment == "악재"
    assert validated.published_at == "2026-07-09T01:30:00+00:00"


def test_disclosure_mock_matches_actual_normalized_contract():
    item = disclosure_item()
    normalized = {
        **item,
        "title": item["report_name"],
        "date": item["received_date"],
        "url": item["source_url"],
    }

    validated = DisclosureItem.model_validate(normalized)

    assert validated.receipt_no == "20260317001234"
    assert validated.stock_code == "005930"


def test_watchlist_mock_matches_actual_normalized_contract():
    validated = WatchlistData.model_validate(watchlist_item())

    assert validated.saved is True
    assert validated.session_id == "session-1"


def test_glossary_mock_matches_actual_normalized_contract():
    validated = GlossaryTerm.model_validate(glossary_term_item())

    assert validated.term == "PER"
    assert validated.aliases == ["Price Earnings Ratio"]
    assert validated.match_score == 100

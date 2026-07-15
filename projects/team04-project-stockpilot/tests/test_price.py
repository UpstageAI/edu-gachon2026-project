from datetime import date
from types import SimpleNamespace

import pandas as pd

from app.repositories import price
from app.schemas.tool_results import StockPriceData
from tests.fixtures.tool_responses import stock_snapshot


async def test_resolve_known_company_without_krx_credentials(monkeypatch):
    monkeypatch.setattr(price.settings, "krx_id", None)
    monkeypatch.setattr(price.settings, "krx_pw", None)

    assert await price.resolve_ticker("삼성전자") == "005930"
    assert await price.resolve_ticker("005930") == "005930"
    assert await price.resolve_ticker("심텍") == "222800"
    assert await price.resolve_ticker("삼성전자우") == "005935"


async def test_get_ohlcv_normalizes_pykrx_frame(monkeypatch):
    frame = pd.DataFrame(
        [
            {
                "시가": 70000,
                "고가": 71000,
                "저가": 69000,
                "종가": 70500,
                "거래량": 100,
                "등락률": -0.7,
            },
            {
                "시가": 70500,
                "고가": 72000,
                "저가": 70000,
                "종가": 71500,
                "거래량": 200,
                "등락률": 1.42,
            },
        ],
        index=pd.to_datetime(["2026-07-08", "2026-07-09"]),
    )
    fake_stock = SimpleNamespace(get_market_ohlcv_by_date=lambda *args: frame)
    monkeypatch.setattr(price, "_get_stock_api", lambda: fake_stock)

    rows = await price.get_ohlcv("005930", "2026-07-08", "2026-07-09")

    assert rows == [
        {
            "date": "2026-07-08",
            "open": 70000,
            "high": 71000,
            "low": 69000,
            "close": 70500,
            "volume": 100,
            "change_pct": -0.7,
        },
        {
            "date": "2026-07-09",
            "open": 70500,
            "high": 72000,
            "low": 70000,
            "close": 71500,
            "volume": 200,
            "change_pct": 1.42,
        },
    ]


async def test_get_stock_snapshot_prefers_pykrx_change_pct(monkeypatch):
    mock = stock_snapshot()
    mock["ohlcv"] = [dict(row) for row in mock["ohlcv"]]
    mock["ohlcv"][-1]["change_pct"] = 1.95

    async def fake_get_ohlcv(*args, **kwargs):
        return mock["ohlcv"]

    async def fake_get_fundamentals(*args, **kwargs):
        return mock["fundamentals"]

    monkeypatch.setattr(price, "get_ohlcv", fake_get_ohlcv)
    monkeypatch.setattr(price, "get_fundamentals", fake_get_fundamentals)

    snapshot = await price.get_stock_snapshot(
        "삼성전자",
        period="1m",
        end=date(2026, 7, 9).isoformat(),
        include_fundamentals=True,
    )

    assert snapshot["ticker"] == "005930"
    assert snapshot["current_price"] == 71400
    assert snapshot["change"] == 1400
    assert snapshot["change_pct"] == 1.95
    assert snapshot["fundamentals_available"] is True
    StockPriceData.model_validate(snapshot)


async def test_get_stock_snapshot_reuses_short_live_cache(monkeypatch):
    with price._SNAPSHOT_CACHE_LOCK:
        price._SNAPSHOT_CACHE.clear()

    calls = 0

    async def fake_get_ohlcv(*args, **kwargs):
        nonlocal calls
        calls += 1
        mock = stock_snapshot()
        rows = [dict(row) for row in mock["ohlcv"]]
        rows[-1]["close"] = 71400 + calls * 100
        rows[-1]["change_pct"] = 2.0 + calls
        return rows

    async def fake_get_fundamentals(*args, **kwargs):
        return None

    monkeypatch.setattr(price, "get_ohlcv", fake_get_ohlcv)
    monkeypatch.setattr(price, "get_fundamentals", fake_get_fundamentals)

    first = await price.get_stock_snapshot("삼성전자", period="1m")
    second = await price.get_stock_snapshot("삼성전자", period="1m")

    assert calls == 1
    assert second == first

    with price._SNAPSHOT_CACHE_LOCK:
        price._SNAPSHOT_CACHE.clear()

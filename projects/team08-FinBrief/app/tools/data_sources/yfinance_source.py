"""yfinance market data source adapter."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

from app.core.schemas import IndicatorValue
from app.tools.data_sources.base import RawIndicatorPoint, build_indicator_values, parse_date, to_float


def parse_yfinance_price_rows(
    rows: Iterable[dict[str, Any]],
    *,
    indicator_id: str,
    name: str,
    unit: str | None = None,
) -> list[IndicatorValue]:
    """Parse simple yfinance row dictionaries into indicator values."""

    points: list[RawIndicatorPoint] = []
    for row in rows:
        raw_value = row.get("Close", row.get("Adj Close"))
        numeric_value = to_float(raw_value)
        if numeric_value is None:
            continue
        points.append(
            RawIndicatorPoint(
                indicator_id=indicator_id,
                name=name,
                source="yfinance",
                value_date=parse_date(row["date"]),
                value=numeric_value,
                unit=unit,
            )
        )
    return build_indicator_values(points)


def _dataframe_to_price_rows(dataframe: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if dataframe is None or getattr(dataframe, "empty", True):
        return rows

    for index, row in dataframe.reset_index().iterrows():
        date_value = row.get("Date") or row.get("Datetime")
        rows.append(
            {
                "date": date_value.date().isoformat()
                if hasattr(date_value, "date")
                else str(date_value)[:10],
                "Close": row.get("Close"),
                "Adj Close": row.get("Adj Close"),
            }
        )
    return rows


def fetch_yfinance_prices(
    *,
    ticker: str,
    indicator_id: str,
    name: str,
    period: str = "5d",
    interval: str = "1d",
    unit: str | None = None,
) -> list[IndicatorValue]:
    """Fetch market prices through yfinance if the optional package exists."""

    try:
        import yfinance as yf
    except ImportError:
        return []

    dataframe = yf.download(
        ticker,
        period=period,
        interval=interval,
        auto_adjust=True,
        progress=False,
        threads=False,
        timeout=10,
        multi_level_index=False,
    )
    return parse_yfinance_price_rows(
        _dataframe_to_price_rows(dataframe),
        indicator_id=indicator_id,
        name=name,
        unit=unit,
    )

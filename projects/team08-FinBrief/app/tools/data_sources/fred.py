"""FRED indicator source adapter."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import Settings, get_settings
from app.core.schemas import IndicatorValue
from app.tools.data_sources.base import RawIndicatorPoint, build_indicator_values, parse_date, to_float


FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"


def parse_fred_observations(
    payload: dict[str, Any],
    *,
    indicator_id: str,
    name: str,
    unit: str | None = None,
) -> list[IndicatorValue]:
    """Parse FRED observations JSON into FinBrief indicator values."""

    points: list[RawIndicatorPoint] = []
    for row in payload.get("observations", []):
        numeric_value = to_float(row.get("value"))
        if numeric_value is None:
            continue
        points.append(
            RawIndicatorPoint(
                indicator_id=indicator_id,
                name=name,
                source="fred",
                value_date=parse_date(row["date"]),
                value=numeric_value,
                unit=unit,
            )
        )
    return build_indicator_values(points)


def fetch_fred_observations(
    *,
    series_id: str,
    indicator_id: str,
    name: str,
    start_date: date,
    end_date: date,
    unit: str | None = None,
    settings: Settings | None = None,
) -> list[IndicatorValue]:
    """Fetch observations from FRED. Requires FRED_API_KEY."""

    runtime_settings = settings or get_settings()
    if runtime_settings.fred_api_key is None:
        return []

    import httpx

    response = httpx.get(
        FRED_OBSERVATIONS_URL,
        params={
            "series_id": series_id,
            "api_key": runtime_settings.fred_api_key.get_secret_value(),
            "file_type": "json",
            "observation_start": start_date.isoformat(),
            "observation_end": end_date.isoformat(),
        },
        timeout=10,
    )
    response.raise_for_status()
    return parse_fred_observations(
        response.json(),
        indicator_id=indicator_id,
        name=name,
        unit=unit,
    )

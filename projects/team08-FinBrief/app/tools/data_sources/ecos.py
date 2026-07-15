"""Bank of Korea ECOS source adapter."""

from __future__ import annotations

from datetime import date
from typing import Any

from app.core.config import Settings, get_settings
from app.core.schemas import IndicatorValue
from app.tools.data_sources.base import RawIndicatorPoint, build_indicator_values, parse_date, to_float


ECOS_BASE_URL = "https://ecos.bok.or.kr/api"


def parse_ecos_key_statistics(
    payload: dict[str, Any],
    *,
    indicator_id_prefix: str = "ecos",
) -> list[IndicatorValue]:
    """Parse ECOS KeyStatisticList JSON into indicator values."""

    rows = payload.get("KeyStatisticList", {}).get("row", [])
    points: list[RawIndicatorPoint] = []
    for row in rows:
        numeric_value = to_float(row.get("DATA_VALUE"))
        if numeric_value is None:
            continue
        name = str(row["KEYSTAT_NAME"])
        points.append(
            RawIndicatorPoint(
                indicator_id=f"{indicator_id_prefix}:{name}",
                name=name,
                source="ecos",
                value_date=parse_date(str(row["CYCLE"])),
                value=numeric_value,
                unit=row.get("UNIT_NAME"),
            )
        )
    return build_indicator_values(points)


def fetch_ecos_key_statistics(
    *,
    start: int = 1,
    end: int = 20,
    settings: Settings | None = None,
) -> list[IndicatorValue]:
    """Fetch ECOS key statistics. Requires ECOS_API_KEY."""

    runtime_settings = settings or get_settings()
    if runtime_settings.ecos_api_key is None:
        return []

    import httpx

    api_key = runtime_settings.ecos_api_key.get_secret_value()
    url = f"{ECOS_BASE_URL}/KeyStatisticList/{api_key}/json/kr/{start}/{end}/"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return parse_ecos_key_statistics(response.json())


def fetch_ecos_statistic_search(
    *,
    statistic_code: str,
    cycle: str,
    start_date: date,
    end_date: date,
    item_code: str,
    indicator_id: str,
    name: str,
    unit: str | None = None,
    settings: Settings | None = None,
) -> list[IndicatorValue]:
    """Fetch one ECOS StatisticSearch series and map it to IndicatorValue."""

    runtime_settings = settings or get_settings()
    if runtime_settings.ecos_api_key is None:
        return []

    import httpx

    api_key = runtime_settings.ecos_api_key.get_secret_value()
    url = (
        f"{ECOS_BASE_URL}/StatisticSearch/{api_key}/json/kr/1/100/"
        f"{statistic_code}/{cycle}/{start_date:%Y%m%d}/{end_date:%Y%m%d}/{item_code}/"
    )
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    rows = response.json().get("StatisticSearch", {}).get("row", [])

    points: list[RawIndicatorPoint] = []
    for row in rows:
        numeric_value = to_float(row.get("DATA_VALUE"))
        if numeric_value is None:
            continue
        points.append(
            RawIndicatorPoint(
                indicator_id=indicator_id,
                name=name,
                source="ecos",
                value_date=parse_date(str(row["TIME"])),
                value=numeric_value,
                unit=unit or row.get("UNIT_NAME"),
            )
        )
    return build_indicator_values(points)

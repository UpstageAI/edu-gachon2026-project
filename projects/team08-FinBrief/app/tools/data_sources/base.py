"""Shared helpers for external indicator data sources."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

from app.core.schemas import IndicatorValue


IndicatorSource = Literal["fred", "yfinance", "ecos", "fixture"]


@dataclass(frozen=True, slots=True)
class RawIndicatorPoint:
    indicator_id: str
    name: str
    source: IndicatorSource
    value_date: date
    value: float
    unit: str | None = None


def parse_date(value: str | date | datetime) -> date:
    """Parse common external API date strings into a date."""

    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    normalized = value.strip()
    if len(normalized) == 8 and normalized.isdigit():
        return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:8]))
    if len(normalized) == 6 and normalized.isdigit():
        return date(int(normalized[:4]), int(normalized[4:6]), 1)
    if "q" in normalized.casefold():
        year = int(normalized[:4])
        quarter = int(normalized[-1])
        month = {1: 1, 2: 4, 3: 7, 4: 10}[quarter]
        return date(year, month, 1)
    return date.fromisoformat(normalized[:10])


def to_float(value: object) -> float | None:
    """Return a float for valid numeric API values, otherwise None."""

    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if not text or text == ".":
        return None
    try:
        numeric = float(text)
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def build_indicator_values(points: list[RawIndicatorPoint]) -> list[IndicatorValue]:
    """Build IndicatorValue models with previous value and change fields."""

    values: list[IndicatorValue] = []
    previous_by_indicator: dict[str, float] = {}

    for point in sorted(points, key=lambda item: (item.indicator_id, item.value_date)):
        previous = previous_by_indicator.get(point.indicator_id)
        change_value = None if previous is None else point.value - previous
        change_percent = None
        if previous not in (None, 0):
            change_percent = (point.value - previous) / previous * 100

        values.append(
            IndicatorValue(
                indicator_id=point.indicator_id,
                name=point.name,
                source=point.source,
                value_date=point.value_date,
                current_value=point.value,
                previous_value=previous,
                change_value=change_value,
                change_percent=change_percent,
                unit=point.unit,
            )
        )
        previous_by_indicator[point.indicator_id] = point.value

    return values

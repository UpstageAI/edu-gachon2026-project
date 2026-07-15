from __future__ import annotations

from datetime import date


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def deadline_status(end_date: str | None, *, today: date | None = None) -> str:
    """Return a display-only deadline label without eligibility scoring."""

    today = today or date.today()
    end = _parse_iso_date(end_date)
    if end is None:
        return "일정 확인 필요"
    if end < today:
        return "마감"
    if (end - today).days <= 14:
        return "마감임박"
    return "모집중"

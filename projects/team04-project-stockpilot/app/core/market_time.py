"""뉴스 발행 시각을 한국 정규장(KRX) 기준 구간으로 분류하는 유틸.

정규장: 09:00~15:30 (KST). 발행 시각을 아래 4구간으로 나눈다.
- 장 시작 전 : ~09:00   (밤사이·아침 뉴스 → 당일 시초가에 반영)
- 장 시작 후 : 09:00~12:00
- 장 마감 전 : 12:00~15:30
- 장 마감 후 : 15:30~    (실적·공시 다수 → 다음 거래일에 반영)
주말(토·일)은 '휴장', 파싱 불가 시 '시각 미상'.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

KST = timezone(timedelta(hours=9))
_OPEN = time(9, 0)
_MID = time(12, 0)
_CLOSE = time(15, 30)


def _to_kst(value: datetime | str | None) -> datetime | None:
    """datetime 또는 ISO 문자열을 KST 기준 datetime으로 변환."""
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(KST)


def classify_session(published_at: datetime | str | None) -> str:
    """발행 시각을 정규장 기준 구간으로 분류한다."""
    dt = _to_kst(published_at)
    if dt is None:
        return "시각 미상"
    if dt.weekday() >= 5:  # 토(5)·일(6)
        return "휴장"
    now = dt.time()
    if now < _OPEN:
        return "장 시작 전"
    if now < _MID:
        return "장 시작 후"
    if now < _CLOSE:
        return "장 마감 전"
    return "장 마감 후"


def tag_session(item: dict[str, Any]) -> dict[str, Any]:
    """뉴스 아이템에 market_session 태그를 붙여 새 dict로 반환한다."""
    tagged = dict(item)
    tagged["market_session"] = classify_session(item.get("published_at"))
    return tagged

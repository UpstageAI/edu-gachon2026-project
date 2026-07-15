"""전체시장 리포트 전용 지표 수집기 (구독과 무관, 카탈로그 21슬롯 전체).

build_report_image 가 이 수집기로 리포트를 채운다. 아침 리포트는 모든 사용자에게
동일하게 발송되므로 구독 토픽이 아니라 카탈로그 전체를 실수집한다.
각 소스(yfinance/fred/ecos) 호출은 개별 try/except 로 격리 — 하나 실패해도 나머지는 채운다."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .report_catalog import MARKET_REPORT_SLOTS
from app.tools.data_sources.yfinance_source import fetch_yfinance_prices
from app.tools.data_sources.fred import fetch_fred_observations
from app.tools.data_sources.ecos import fetch_ecos_statistic_search

# 비-yfinance 슬롯의 소스 파라미터 매핑.
_FRED_SERIES: dict[str, str] = {
    "us10y": "DGS10",              # 미국 10년물 국채금리
    "us_policy_rate": "FEDFUNDS",  # 미국 기준금리(연방기금금리)
    "eu_policy_rate": "ECBDFR",    # ECB 예금금리
    "jp10y": "IRLTLT01JPM156N",    # 일본 10년물(월간, 넓은 범위 필요)
}
# indicator_id: (statistic_code, item_code, cycle, lookback_days)
_ECOS_SERIES: dict[str, tuple[str, str, str, int]] = {
    "kr10y": ("817Y002", "010200001", "D", 30),          # 국고채 10년(일)
    "kr_policy_rate": ("722Y001", "0101000", "D", 120),  # 한국은행 기준금리
}


def _yf_tickers(slot) -> list[str]:
    """슬롯 alias 중 yfinance 티커 후보(특수문자 포함 티커 우선, topic_* 제외)."""
    cands = [a for a in slot.aliases if not a.startswith("topic_")]
    cands.sort(key=lambda a: 0 if any(c in a for c in "^=.-") else 1)
    return cands


def _row(value, slot) -> dict[str, Any]:
    return {
        "indicator_id": slot.indicator_id,
        "name": slot.display_name,
        "value": value.current_value,
        "prev": value.previous_value,
        "change_value": value.change_value,
        "change_pct": value.change_percent,
        "unit": slot.unit,
    }


def collect_report_indicators(run_date: date) -> tuple[list[dict[str, Any]], list[str]]:
    """카탈로그 21슬롯을 실수집. (indicators, missing_indicator_ids) 반환."""
    end = run_date
    indicators: list[dict[str, Any]] = []
    missing: list[str] = []

    for slot in MARKET_REPORT_SLOTS:
        values = []
        try:
            if slot.source == "yfinance":
                for ticker in _yf_tickers(slot):
                    values = fetch_yfinance_prices(
                        ticker=ticker, indicator_id=slot.indicator_id,
                        name=slot.display_name, unit=slot.unit)
                    if values:
                        break
            elif slot.indicator_id in _FRED_SERIES:
                values = fetch_fred_observations(
                    series_id=_FRED_SERIES[slot.indicator_id], indicator_id=slot.indicator_id,
                    name=slot.display_name, start_date=end - timedelta(days=200),
                    end_date=end, unit=slot.unit)
            elif slot.indicator_id in _ECOS_SERIES:
                stat, item, cycle, days = _ECOS_SERIES[slot.indicator_id]
                values = fetch_ecos_statistic_search(
                    statistic_code=stat, cycle=cycle, start_date=end - timedelta(days=days),
                    end_date=end, item_code=item, indicator_id=slot.indicator_id,
                    name=slot.display_name, unit=slot.unit)
        except Exception:
            values = []

        if values:
            indicators.append(_row(values[-1], slot))
        else:
            missing.append(slot.indicator_id)

    return indicators, missing

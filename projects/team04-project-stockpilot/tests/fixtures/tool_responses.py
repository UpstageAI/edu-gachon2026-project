"""실제 repository 응답과 동일한 전체 필드를 갖는 Mock factory."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def stock_snapshot() -> dict[str, Any]:
    return {
        "ticker": "005930",
        "name": "삼성전자",
        "as_of": "2026-07-09",
        "snapshot_at": "2026-07-09T01:30:00+00:00",
        "current_price": 71400,
        "previous_close": 70000,
        "change": 1400,
        "change_pct": 2.0,
        "period": "1m",
        "ohlcv": [
            {
                "date": "2026-07-08",
                "open": 69500,
                "high": 70500,
                "low": 69000,
                "close": 70000,
                "volume": 12345678,
                "change_pct": -0.7,
            },
            {
                "date": "2026-07-09",
                "open": 70500,
                "high": 72000,
                "low": 70000,
                "close": 71400,
                "volume": 15000000,
                "change_pct": 2.0,
            },
        ],
        "fundamentals": {
            "date": "2026-07-09",
            "bps": 60000,
            "per": 12.3,
            "pbr": 1.4,
            "eps": 5800,
            "div": 2.1,
            "dps": 1444,
        },
        "fundamentals_available": True,
    }


def directional_news_item() -> dict[str, Any]:
    """get_stock_issue_news가 Executor에 넘기는 실제 repository 형태."""
    published_at = datetime(2026, 7, 9, 1, 30, tzinfo=timezone.utc)
    return {
        "title": "삼성전자 실적 우려에 주가 급락",
        "description": "영업이익 감소 우려로 주가가 약세를 보였다.",
        "original_link": "https://example.com/down",
        "link": "https://n.news.naver.com/down",
        "source_domain": "example.com",
        "published_at": published_at,
        "published_timestamp": published_at.timestamp(),
        "query": "삼성전자 하락",
        "relevance_score": 9,
        "matched_keywords": ["실적", "영업이익", "주가"],
        "direct_company_match": True,
        "company_mentioned": True,
        "market_context_match": True,
        "direction": "down",
        "direction_keywords": ["급락", "우려"],
        "opposite_direction_keywords": [],
        "has_direction_evidence": True,
        "issue_score": 18,
        "ranking_tier": 3,
    }


def disclosure_item() -> dict[str, Any]:
    """get_recent_disclosures가 Executor에 넘기는 실제 repository 형태."""
    return {
        "receipt_no": "20260317001234",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "stock_code": "005930",
        "report_name": "사업보고서 (2025.12)",
        "received_date": "20260317",
        "source_url": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260317001234",
    }


def watchlist_item() -> dict[str, Any]:
    """Supabase upsert 이후 repository가 반환하는 실제 형태."""
    return {
        "id": 1,
        "session_id": "session-1",
        "ticker": "005930",
        "name": "삼성전자",
        "created_at": "2026-07-09T01:30:00+00:00",
        "saved": True,
    }


def glossary_term_item() -> dict[str, Any]:
    """glossary_terms row returned by the structured glossary repository."""
    return {
        "id": 1,
        "term": "PER",
        "definition": "Price Earnings Ratio. Current price divided by EPS.",
        "category": "valuation",
        "aliases": ["Price Earnings Ratio"],
        "difficulty": "beginner",
        "example": "PER 10 means price is 10x EPS.",
        "source_url": "https://example.com/per",
        "metadata": {},
        "match_score": 100,
        "created_at": "2026-07-09T01:30:00+00:00",
        "updated_at": "2026-07-09T01:30:00+00:00",
    }

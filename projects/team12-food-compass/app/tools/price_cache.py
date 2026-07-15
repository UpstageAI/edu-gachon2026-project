"""Supabase(PostgreSQL) price_cache 테이블 저장/조회 — API 장애 시 Fallback 용."""
from __future__ import annotations

import json
from typing import Any

from app.core.db import get_conn as _get_conn
from app.schemas import RawPriceOutput


def ping() -> bool:
    """DB 연결 가능 여부만 확인 (헬스체크용)."""
    try:
        conn = _get_conn()
        conn.close()
        return True
    except Exception:
        return False


def save_price_cache(item_name: str, price_data: RawPriceOutput, source: str = "KAMIS") -> None:
    """가격 조회 성공 시 price_cache에 UPSERT."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO price_cache (item_name, source, price_data, cached_at)
            VALUES (%s, %s, %s::jsonb, NOW())
            ON CONFLICT (item_name) DO UPDATE
                SET price_data = EXCLUDED.price_data,
                    source     = EXCLUDED.source,
                    cached_at  = EXCLUDED.cached_at;
            """,
            (item_name, source, json.dumps(price_data.model_dump())),
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()


def get_price_cache(item_name: str) -> dict[str, Any] | None:
    """API 장애 시 캐시에서 조회. 없으면 None 반환.

    반환값에 is_fallback=True 포함 — 호출측에서 사용자에게 캐시 데이터임을 고지.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT price_data, source, cached_at FROM price_cache WHERE item_name = %s;",
            (item_name,),
        )
        row = cur.fetchone()
        cur.close()
    finally:
        conn.close()

    if row is None:
        return None

    price_data, source, cached_at = row
    return {
        **price_data,
        "item_name": item_name,
        "source": source,
        "cached_at": cached_at.isoformat(),
        "is_fallback": True,
    }

"""value_repository — 컬럼 값 조회(셀 매칭용 distinct 값·리터럴 검색), 읽기 전용, dialect 인지.

식별자(table/column)는 카탈로그에서 온 값만 넘어오므로 쿼트 주입 안전.
sqlite: 스키마 접두어 없음·LIKE,  postgres: schema.table·ILIKE.
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.db import get_engine, is_sqlite
from app.core.settings import settings


def _qualified(table: str, sqlite: bool) -> str:
    return f'"{table}"' if sqlite else f'"{settings.db_schema}"."{table}"'


def sample_values(table: str, column: str, k: int = 3) -> list:
    eng = get_engine()
    q = (f'SELECT DISTINCT "{column}" FROM {_qualified(table, is_sqlite(eng))} '
         f'WHERE "{column}" IS NOT NULL LIMIT {int(k)}')
    with eng.connect() as c:
        return [r[0] for r in c.execute(text(q)).fetchall()]


def find_columns_with_value(literal: str, candidates: list[tuple[str, str]]) -> list[tuple[str, str]]:
    eng = get_engine()
    sqlite = is_sqlite(eng)
    op = "LIKE" if sqlite else "ILIKE"
    hits: list[tuple[str, str]] = []
    with eng.connect() as c:
        for t, col in candidates:
            q = f'SELECT 1 FROM {_qualified(t, sqlite)} WHERE "{col}" {op} :v LIMIT 1'
            if c.execute(text(q), {"v": f"%{literal}%"}).first():
                hits.append((t, col))
    return hits

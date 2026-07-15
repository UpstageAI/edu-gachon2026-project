"""schema_repository — DB 스키마 카탈로그(테이블·컬럼·DDL) 접근 (읽기 전용, dialect 인지).

sqlite: sqlite_master / PRAGMA table_info,  postgres: information_schema.
소스: core.db 엔진(현재 스레드 타깃).
"""
from __future__ import annotations

from sqlalchemy import text

from app.core.db import get_engine, is_sqlite
from app.core.settings import settings


def list_tables() -> list[str]:
    eng = get_engine()
    with eng.connect() as c:
        if is_sqlite(eng):
            rows = c.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"))
        else:
            rows = c.execute(text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :s AND table_type = 'BASE TABLE' ORDER BY table_name"),
                {"s": settings.db_schema})
        return [r[0] for r in rows]


def get_columns(table: str) -> list[tuple[str, str]]:
    eng = get_engine()
    with eng.connect() as c:
        if is_sqlite(eng):
            rows = c.execute(text(f'PRAGMA table_info("{table}")'))
            return [(r[1], (r[2] or "TEXT")) for r in rows]  # (name, type)
        rows = c.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = :s AND table_name = :t ORDER BY ordinal_position"),
            {"s": settings.db_schema, "t": table})
        return [(r[0], r[1]) for r in rows]


def get_ddl(tables: list[str]) -> str:
    """여러 테이블의 CREATE TABLE DDL (dialect 무관 — get_columns 기반)."""
    parts = []
    for t in tables:
        body = ",\n  ".join(f'"{n}" {d}' for n, d in get_columns(t))
        parts.append(f'CREATE TABLE "{t}" (\n  {body}\n)')
    return "\n\n".join(parts)


def catalog() -> list[dict]:
    """전체 테이블·컬럼 카탈로그 (스키마 브라우저용, 읽기 전용 메타데이터).

    행 데이터는 안 나감 — 테이블·컬럼명·타입뿐. list_tables + get_columns 재사용.
    """
    return [
        {"name": t, "columns": [{"name": n, "type": d} for n, d in get_columns(t)]}
        for t in list_tables()
    ]

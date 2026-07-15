"""대상 데이터베이스 접근 — 기본은 Supabase(PostgreSQL) 읽기전용,
평가용으로 thread-local 타깃 스위칭(AI Hub sqlite)도 지원.

- 기본(타깃 미지정): Supabase read-only (default_transaction_read_only + statement_timeout)
- set_target(sqlite_path): 그 스레드의 쿼리를 해당 sqlite 로 라우팅 (route_eval 실 linker용)

repositories/tools 는 is_sqlite() 로 dialect 분기한다.
"""
from __future__ import annotations

import threading

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from app.core.settings import settings

_ctx = threading.local()
_engines: dict[str, Engine] = {}
_lock = threading.Lock()


def set_target(sqlite_path: str | None) -> None:
    """이 스레드의 대상 DB 를 지정(None=Supabase 기본)."""
    _ctx.path = sqlite_path


def current_db_key() -> str:
    """캐시 키용 현재 DB 식별자."""
    return getattr(_ctx, "path", None) or "supabase"


def is_sqlite(engine: Engine) -> bool:
    return engine.dialect.name == "sqlite"


def _make(url: str, sqlite: bool) -> Engine:
    if sqlite:
        return create_engine(url)
    timeout_ms = int(settings.sql_exec_timeout_s * 1000)
    return create_engine(
        url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
        },
    )


def get_engine() -> Engine:
    """현재 타깃(스레드별)에 맞는 엔진을 반환(경로별 싱글턴)."""
    path = getattr(_ctx, "path", None)
    # sqlite 평가 DB 는 읽기전용(mode=ro)으로 — 생성 SQL 이 SELECT 여도 엔진 레벨에서 쓰기 차단
    url = f"sqlite:///file:{path}?mode=ro&uri=true" if path else settings.sqlalchemy_url
    with _lock:
        if url not in _engines:
            _engines[url] = _make(url, bool(path))
    return _engines[url]

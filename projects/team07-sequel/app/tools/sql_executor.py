"""sql_executor 도구 — 검증된 SQL 을 읽기전용으로 실행한다.

입력: sql(str)
출력: ExecutionResult(columns, rows, format, truncated)
제약: LIMIT(settings.sql_max_rows) 강제 주입, read-only·statement_timeout 은 core.db 커넥션 레벨.
엔진: core.db.get_engine() (Supabase read-only)
"""
from __future__ import annotations

import sqlglot
from sqlalchemy import text
from sqlglot import exp

from app.core.db import get_engine
from app.core.settings import settings
from app.tools.schemas import ExecutionResult


def _with_limit(sql: str) -> str:
    """최상위 SELECT 에 LIMIT 이 없으면 강제로 붙인다."""
    try:
        expr = sqlglot.parse_one(sql, dialect="postgres")
        if isinstance(expr, exp.Select) and not expr.args.get("limit"):
            expr = expr.limit(settings.sql_max_rows)
        return expr.sql(dialect="postgres")
    except Exception:  # noqa: BLE001 — 파싱 실패는 validator 가 이미 걸렀음
        return sql.strip().rstrip(";")


def execute_sql(sql: str) -> ExecutionResult:
    stmt = _with_limit(sql)
    with get_engine().connect() as c:
        result = c.execute(text(stmt))
        columns = list(result.keys())
        fetched = [list(r) for r in result.fetchmany(settings.sql_max_rows + 1)]

    truncated = len(fetched) > settings.sql_max_rows
    rows = fetched[: settings.sql_max_rows]
    fmt = "scalar" if (len(rows) == 1 and len(columns) == 1) else "table"
    return ExecutionResult(columns=columns, rows=rows, format=fmt, truncated=truncated)

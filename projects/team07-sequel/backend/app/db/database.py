"""Supabase(Postgres) 연결. text2sql_reader(읽기 전용) 계정의 Session Pooler
연결 문자열을 SUPABASE_DB_URL 환경변수로 주입받아 사용한다.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import settings

# 커넥션 풀을 요청마다 새로 만들지 않도록 모듈 전역에 한 번만 생성해서 재사용한다.
_engine: Engine | None = None


def get_engine() -> Engine:
    """SQLAlchemy Engine을 최초 1회만 생성하고(lazy init) 이후에는 재사용한다.

    pool_pre_ping=True: 커넥션을 실제로 쓰기 전에 살아있는지 확인해서,
    Supabase 쪽에서 유휴 커넥션을 끊어버려도 자동으로 재연결하게 한다.
    """
    global _engine
    if _engine is None:
        if not settings.SUPABASE_DB_URL:
            raise RuntimeError("SUPABASE_DB_URL 환경변수가 설정되지 않았습니다.")
        _engine = create_engine(settings.SUPABASE_DB_URL, pool_pre_ping=True)
    return _engine


def run_readonly_query(sql: str) -> list[dict]:
    """SQL을 실행하고 결과를 [{컬럼명: 값}, ...] 형태의 리스트로 돌려준다.

    주의: 이 함수는 guardrail.validate_sql()을 통과한 SELECT 쿼리만
    받는다고 가정한다. 이 함수 자체는 쿼리 내용을 다시 검증하지 않는다.
    """

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        return [dict(zip(columns, row)) for row in result.fetchall()]


def run_readonly_query_table(sql: str) -> tuple[list[str], list[list]]:
    """SQL을 실행하고 (컬럼명 리스트, 행(리스트) 리스트) 형태로 돌려준다.

    run_readonly_query()와 실행 로직은 같지만, 반환 형태가 다르다
    (agent/frontend가 쓰는 {columns:[...], rows:[[...]]} 표 형식에 맞춤).
    proxy.py의 defense-in-depth 재검증(agent 결과를 백엔드가 재실행)에서 사용한다.
    행이 0건이어도 columns는 쿼리 자체에서 그대로 얻어진다.
    """

    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        columns = list(result.keys())
        rows = [list(row) for row in result.fetchall()]
        return columns, rows

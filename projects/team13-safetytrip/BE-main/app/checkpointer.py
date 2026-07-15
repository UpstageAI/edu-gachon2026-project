"""
LangGraph 체크포인터(Postgres) 연결 관리.
FastAPI 앱 생명주기 동안 커넥션 풀 하나를 계속 재사용함
(요청마다 새 커넥션 안 만듦).

주의: SQLAlchemy(psycopg2)를 쓰는 tools/stats_tool.py 등과는 별도로,
LangGraph 체크포인터는 psycopg(v3)를 직접 씀 - 서로 다른 드라이버라
충돌 없이 같이 쓸 수 있음.
"""
import os

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# PostgresSaver 공식 문서 권장 설정: autocommit=True 필수
# (테이블 생성/체크포인트 저장이 트랜잭션 밖에서 즉시 커밋되어야 함)
_CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,  # PgBouncer/Supabase pooler 환경에서 prepared statement 이슈 방지
}

_pool = None


def get_checkpointer_pool() -> ConnectionPool:
    """
    체크포인터 전용 커넥션 풀. 앱 시작 시 한 번만 생성해서 재사용.
    """
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL이 .env에 설정되지 않았습니다.")
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=1,
            max_size=5,
            kwargs=_CONNECTION_KWARGS,
            open=True,
        )
    return _pool


def get_checkpointer() -> PostgresSaver:
    """FastAPI 앱에서 그래프 compile 시 사용할 체크포인터 인스턴스."""
    pool = get_checkpointer_pool()
    return PostgresSaver(pool)
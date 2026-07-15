"""
LangGraph 체크포인터 테이블을 Supabase에 생성.
공식 문서 권장사항: 앱 런타임 안에서 매번 .setup()을 부르지 말고,
배포/마이그레이션 단계에서 1회만 실행할 것.

실행: python loaders/setup_checkpointer.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from psycopg_pool import ConnectionPool
from langgraph.checkpoint.postgres import PostgresSaver

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")


def run():
    if not DATABASE_URL:
        print("[ERROR] DATABASE_URL이 .env에 설정되지 않았습니다.")
        sys.exit(1)

    print("체크포인터 테이블 생성 중...")
    with ConnectionPool(
        conninfo=DATABASE_URL,
        min_size=1,
        max_size=1,
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=True,
    ) as pool:
        checkpointer = PostgresSaver(pool)
        checkpointer.setup()

    print("완료. checkpoints / checkpoint_blobs / checkpoint_writes 테이블이 생성/확인되었습니다.")


if __name__ == "__main__":
    run()
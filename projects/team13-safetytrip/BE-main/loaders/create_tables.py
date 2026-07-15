"""
Step 1. Supabase에 테이블 생성 (DDL 실행)
preprocessors/ 안의 *_schema.sql 파일들을 순서대로 실행함.

실행 전: .env에 DATABASE_URL 채워져 있어야 함
실행: python loaders/create_tables.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

SCHEMA_FILES = [
    "preprocessors/disaster_messages_schema.sql",
    "preprocessors/response_agencies_schema.sql",
    "preprocessors/disaster_guidelines_schema.sql",
]


def run():
    if not DATABASE_URL or "[YOUR-PASSWORD]" in DATABASE_URL:
        print("[ERROR] .env의 DATABASE_URL이 설정되지 않았습니다.")
        print("Supabase 프로젝트 > Settings > Database > Connection string(URI)에서 복사하세요.")
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    cur = conn.cursor()

    for path in SCHEMA_FILES:
        if not os.path.exists(path):
            print(f"[SKIP] {path} 없음")
            continue
        print(f"실행 중: {path}")
        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
        try:
            cur.execute(sql)
            print("  -> 성공")
        except Exception as e:
            print(f"  -> [ERROR] {e}")

    cur.close()
    conn.close()
    print("\n테이블 생성 완료.")


if __name__ == "__main__":
    run()
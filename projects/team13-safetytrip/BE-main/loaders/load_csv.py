"""
Step 2. processed_data/*.csv를 Supabase 테이블로 적재.
기존 데이터는 TRUNCATE 후 새로 적재 (초기 적재이므로 upsert 대신 간단하게 처리).

실행: python loaders/load_csv.py <table_name> <csv_path>
예:   python loaders/load_csv.py disaster_messages processed_data/disaster_messages.csv
      python loaders/load_csv.py response_agencies processed_data/response_agencies.csv
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

# 각 테이블별 날짜 컬럼 (pandas가 문자열로 읽지 않고 datetime으로 파싱하도록)
DATE_COLUMNS = {
    "disaster_messages": ["created_at", "reg_date", "modified_date"],
    "response_agencies": [],
}


def load(table_name: str, csv_path: str, chunksize: int = 1000):
    if not DATABASE_URL or "[YOUR-PASSWORD]" in DATABASE_URL:
        print("[ERROR] .env의 DATABASE_URL이 설정되지 않았습니다.")
        sys.exit(1)

    if not os.path.exists(csv_path):
        print(f"[ERROR] {csv_path} 없음")
        sys.exit(1)

    date_cols = DATE_COLUMNS.get(table_name, [])
    df = pd.read_csv(csv_path, parse_dates=date_cols)
    print(f"{csv_path} 로드: {len(df)}행, 컬럼: {list(df.columns)}")

    engine = create_engine(DATABASE_URL)

    with engine.begin() as conn:
        print(f"{table_name} 테이블 TRUNCATE...")
        conn.execute(text(f"TRUNCATE TABLE {table_name}"))

    print(f"{table_name}에 적재 중 (청크 {chunksize}건씩)...")
    df.to_sql(
        table_name,
        engine,
        if_exists="append",
        index=False,
        chunksize=chunksize,
        method="multi",
    )

    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
        count = result.scalar()
    print(f"적재 완료. {table_name} 현재 행 수: {count}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python loaders/load_csv.py <table_name> <csv_path>")
        sys.exit(1)

    load(sys.argv[1], sys.argv[2])
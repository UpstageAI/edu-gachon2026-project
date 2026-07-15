"""
disaster_guidelines 테이블의 safety_cate_nm2(재난유형) 분포 확인.
자연재난 데이터가 특정 유형(태풍 등)에 쏠려있는지, 다양하게 분포돼있는지 검증용.

실행: python tools/check_guidelines_distribution.py
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def check():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT source_dataset, safety_cate_nm2, COUNT(*) as cnt
        FROM disaster_guidelines
        GROUP BY source_dataset, safety_cate_nm2
        ORDER BY source_dataset, cnt DESC
    """)
    rows = cur.fetchall()

    print(f"{'source':<10} {'재난유형':<15} {'건수':<5}")
    print("-" * 35)
    for r in rows:
        print(f"{r[0]:<10} {r[1] or '(없음)':<15} {r[2]:<5}")

    cur.execute("SELECT COUNT(*) FROM disaster_guidelines")
    total = cur.fetchone()[0]
    print(f"\n총 {total}건")

    cur.close()
    conn.close()


if __name__ == "__main__":
    check()
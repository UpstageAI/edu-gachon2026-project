"""Supabase (PostgreSQL) 연결 및 price_cache 테이블 동작 검증."""
from __future__ import annotations

import json
import os
import urllib.parse

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    # psycopg2가 URL 내 %40(@) 등 특수문자를 오파싱하는 문제를 방지하기 위해
    # URL을 직접 파싱해 각 파라미터로 분리하여 전달
    url = urllib.parse.urlparse(DATABASE_URL)
    return psycopg2.connect(
        host=url.hostname,
        port=url.port or 5432,
        dbname=url.path.lstrip("/"),
        user=urllib.parse.unquote(url.username or ""),
        password=urllib.parse.unquote(url.password or ""),
        sslmode="require",
    )


# ── 연결 ──────────────────────────────────────────────────────────────

def test_connection():
    """DATABASE_URL로 Supabase에 정상 연결되는지 확인."""
    conn = get_conn()
    assert conn.status == psycopg2.extensions.STATUS_READY
    conn.close()


def test_price_cache_table_exists():
    """price_cache 테이블이 존재하는지 확인."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_name = 'price_cache'
        );
    """)
    exists = cur.fetchone()[0]
    cur.close()
    conn.close()
    assert exists, "price_cache 테이블이 없습니다. data/sql/init.sql을 먼저 실행하세요."


# ── UPSERT / SELECT / DELETE ──────────────────────────────────────────

TEST_ITEM = "__test_item__"
TEST_DATA = {"dpr1": "1000", "dpr5": "900", "dpr7": "950", "unit": "1개"}


def test_upsert_price_cache():
    """price_cache에 테스트 레코드를 UPSERT할 수 있는지 확인."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO price_cache (item_name, source, price_data, cached_at)
        VALUES (%s, %s, %s::jsonb, NOW())
        ON CONFLICT (item_name) DO UPDATE
            SET price_data = EXCLUDED.price_data,
                cached_at  = EXCLUDED.cached_at;
    """, (TEST_ITEM, "TEST", json.dumps(TEST_DATA)))
    conn.commit()
    cur.close()
    conn.close()


def test_select_price_cache():
    """UPSERT한 레코드를 SELECT로 정상 조회할 수 있는지 확인."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT price_data FROM price_cache WHERE item_name = %s;",
        (TEST_ITEM,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()

    assert row is not None, "레코드가 없습니다."
    price_data = row[0]
    assert price_data["dpr1"] == TEST_DATA["dpr1"]
    assert price_data["unit"] == TEST_DATA["unit"]


def test_cleanup_test_record():
    """테스트용 레코드를 삭제해 DB를 원상복구."""
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM price_cache WHERE item_name = %s;", (TEST_ITEM,))
    conn.commit()
    cur.close()
    conn.close()

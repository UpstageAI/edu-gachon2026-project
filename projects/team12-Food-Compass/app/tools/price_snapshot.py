"""Supabase(PostgreSQL) price_snapshot 테이블 저장/조회.

KAMIS 응답을 가공 없이 그대로 적재 — 등급/품종별 row 전부 유지.
"""
from __future__ import annotations

from typing import Any

import psycopg2.extras

from app.core.db import get_conn as _get_conn

_DPR_FIELDS = ("dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7")


def save_price_snapshot(items: list[dict[str, Any]], regday: str, source: str = "KAMIS") -> int:
    """KAMIS 응답 row 리스트를 price_snapshot에 UPSERT. 저장된 row 수 반환."""
    if not items:
        return 0

    rows = [
        (
            item["item_category_code"],
            item["item_name"],
            item["item_code"],
            item["kind_name"],
            item["kind_code"],
            item["rank"],
            item["rank_code"],
            item["unit"],
            *(item.get(field, "-") for field in _DPR_FIELDS),
            regday,
            source,
        )
        for item in items
    ]

    conn = _get_conn()
    try:
        cur = conn.cursor()
        psycopg2.extras.execute_values(
            cur,
            """
            INSERT INTO price_snapshot (
                item_category_code, item_name, item_code, kind_name, kind_code,
                rank_name, rank_code, unit,
                dpr1, dpr2, dpr3, dpr4, dpr5, dpr6, dpr7,
                regday, source
            )
            VALUES %s
            ON CONFLICT (item_code, kind_code, rank_code, regday) DO UPDATE
                SET dpr1 = EXCLUDED.dpr1,
                    dpr2 = EXCLUDED.dpr2,
                    dpr3 = EXCLUDED.dpr3,
                    dpr4 = EXCLUDED.dpr4,
                    dpr5 = EXCLUDED.dpr5,
                    dpr6 = EXCLUDED.dpr6,
                    dpr7 = EXCLUDED.dpr7,
                    fetched_at = NOW();
            """,
            rows,
        )
        conn.commit()
        saved = cur.rowcount
        cur.close()
    finally:
        conn.close()
    return saved


def get_latest_prices(item_name: str) -> list[dict[str, Any]]:
    """품목명으로 가장 최근 regday의 전체 row(등급/품종별)를 조회."""
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT item_name, item_code, kind_name, kind_code, rank_name, rank_code,
                   unit, dpr1, dpr2, dpr3, dpr4, dpr5, dpr6, dpr7, regday, source, fetched_at
            FROM price_snapshot
            WHERE item_name = %s
              AND regday = (
                  SELECT MAX(regday) FROM price_snapshot WHERE item_name = %s
              );
            """,
            (item_name, item_name),
        )
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    return [dict(zip(columns, row, strict=True)) for row in rows]


_SIMILAR_ITEM_NAME_LIMIT = 20


def _escape_like_pattern(keyword: str) -> str:
    """ILIKE 패턴에 쓰기 전에 keyword 안의 LIKE 메타문자(%, _)를 리터럴로 이스케이프.

    [2026-07-15 코드 리뷰 반영] keyword는 Router가 사용자 입력에서 추출한 품목명이라
    "%"나 "_"가 그대로 들어있으면 리터럴 문자가 아니라 LIKE 와일드카드로 해석돼 의도치
    않게 넓게 매칭될 수 있음 — PostgreSQL은 별도 ESCAPE 절 없이도 기본 이스케이프
    문자가 백슬래시라 이렇게 이스케이프해두면 그대로 리터럴 취급됨(직접 검증함).
    """
    return keyword.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_similar_item_names(keyword: str) -> list[str]:
    """정확히 일치하는 품목명이 없을 때 쓰는 ILIKE 부분일치 폴백 검색.

    [2026-07-15 추가] "고추"로 물어봤을 때 KAMIS DB엔 "붉은고추"/"풋고추"/"건고추"만 있고
    정확히 "고추"라는 품목명은 없어서 매번 KAMIS를 못 찾은 것으로 처리되고 참가격
    (data.go.kr)으로 새고 있었음(KAMIS에 실제로 데이터가 있는데도 우선순위가 밀리던 문제).
    get_latest_prices()의 정확 일치가 실패했을 때만 이 함수로 관련 품목명 후보를 찾는다.

    [2026-07-15 코드 리뷰 반영] 매칭 후보 수를 LIMIT으로 제한 — 호출부(get_raw_price_node)가
    후보 하나마다 추가로 get_latest_prices() 쿼리를 날리므로, 과도하게 넓은 키워드가
    들어와도 DB 부하가 무한정 커지지 않도록 방어.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT DISTINCT item_name FROM price_snapshot WHERE item_name ILIKE %s ORDER BY item_name LIMIT %s;",
            (f"%{_escape_like_pattern(keyword)}%", _SIMILAR_ITEM_NAME_LIMIT),
        )
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [row[0] for row in rows]


def get_latest_prices_by_kind_name(kind_name: str, limit: int = _SIMILAR_ITEM_NAME_LIMIT) -> list[dict[str, Any]]:
    """부위명(kind_name)만으로 검색했을 때, 그 부위를 가진 모든 품목(item_name)의
    최신 regday row를 한 번의 쿼리·커넥션으로 조회.

    [2026-07-15 추가] "삼겹살"은 KAMIS의 item_name이 아니라 "돼지"의 kind_name(부위)일
    뿐이라, item_name 기준 정확/ILIKE 매칭이 둘 다 실패해 참가격(data.go.kr)으로 새고
    있었음(실제 재현 확인). "수입 ~"류는 국내산 기준 응답이 되도록 제외(사용자 확인) —
    "삼겹살"→돼지만, "소고기"류 alias와 동일한 국내산 우선 원칙.

    [2026-07-15 코드리뷰 반영] 기존엔 이 함수(당시 이름 find_kind_name_parents)가
    item_name 목록만 반환하고, 호출부(kamis.py)가 그 목록을 순회하며 매 item_name마다
    get_latest_prices()를 별도 호출 — parent 수만큼(최대 2~3개) 커넥션을 새로 열고
    쿼리도 그만큼 반복 실행했음. item_name별 "최신 regday"는 윈도우 함수로 각 item_name
    자신의 데이터만 기준으로 구해서, 커넥션 1개·쿼리 1번으로 모든 parent의 최신 row를
    한 번에 가져오도록 변경. search_similar_item_names와 동일하게 결과 행 수를 LIMIT으로
    제한(부위 하나가 지나치게 많은 item_name에 걸리는 경우에 대한 방어).
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT item_name, item_code, kind_name, kind_code, rank_name, rank_code,
                   unit, dpr1, dpr2, dpr3, dpr4, dpr5, dpr6, dpr7, regday, source, fetched_at
            FROM (
                SELECT *,
                       RANK() OVER (PARTITION BY item_name ORDER BY regday DESC) AS _rank
                FROM price_snapshot
                WHERE kind_name = %s AND item_name NOT ILIKE '수입 %%'
            ) ranked
            WHERE _rank = 1
            ORDER BY item_name
            LIMIT %s;
            """,
            (kind_name, limit),
        )
        columns = [desc[0] for desc in cur.description]
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()
    return [dict(zip(columns, row, strict=True)) for row in rows]


def delete_old_snapshots(retention_days: int = 7) -> int:
    """[2026-07-14 추가] regday가 (오늘 - retention_days)보다 오래되고, 테이블에 남아있는
    가장 최신 regday보다도 오래된 row만 삭제. 삭제 건수 반환.

    `get_latest_prices()`는 항상 MAX(regday)만 조회하므로 오래된 row가 남아있어도 판정
    결과 자체엔 영향 없지만(§ 확인 완료), 매일 쌓이는 걸 무한정 방치하지 않도록 최근
    N일치만 유지 — 동시에 최근 며칠 치는 남겨서 "특정 날짜 수집분이 이상했다" 같은
    디버깅은 계속 가능하게 함(예: 축산물 제외 dpr1/dpr2 결측 이슈도 스냅샷이 남아있어서
    바로 진단할 수 있었음).

    [2026-07-14 (14) 추가 보강] price_gokr_snapshot에서 실제로 겪은 사고(수집이 예상보다
    지연되면서 retention_days 기준에 걸려 유일한 최신 데이터까지 삭제됨)를 계기로,
    KAMIS cron이 하루 이틀 실패하는 경우에도 같은 일이 벌어지지 않도록 "테이블에 남은
    가장 최신 regday는 아무리 오래돼도 절대 지우지 않는다"는 안전장치를 동일하게 추가.
    """
    conn = _get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM price_snapshot
            WHERE regday < CURRENT_DATE - (%s * INTERVAL '1 day')
              AND regday < (SELECT MAX(regday) FROM price_snapshot);
            """,
            (retention_days,),
        )
        conn.commit()
        deleted = cur.rowcount
        cur.close()
    finally:
        conn.close()
    return deleted

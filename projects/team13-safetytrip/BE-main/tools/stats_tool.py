"""
SQL 통계 Tool: 지역 x 월별 재난 유형 발생 빈도 집계.
LangGraph의 stats 노드에서 호출할 함수.

핵심 로직 (기획서 4번 섹션 "데이터 공백 폴백" 반영):
1. 시/군/구 단위로 집계 시도
2. 표본이 부족하면(기본 임계값 5건) -> 시/도 단위로 확대, 확대했다는 사실을 결과에 명시
3. 시/도 단위로도 부족하면 -> 표본 부족을 솔직히 표시 (LLM이 임의로 답을 만들지 않도록)

실행 예시: python tools/stats_tool.py 부산광역시 해운대구 8
"""
import os
import sys
from dataclasses import dataclass

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from tools.resilience import call_with_retry, ToolUnavailableError

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")
MIN_SAMPLE_THRESHOLD = 5  # 이 건수 미만이면 표본 부족으로 판단


@dataclass
class DisasterStatsResult:
    sido: str
    sigungu: str | None
    month: int
    total_count: int
    breakdown: list  # [{"disaster_type": str, "count": int, "pct": float}, ...]
    scope_used: str  # "sigungu" | "sido" | "insufficient"
    fallback_notice: str | None = None  # 사용자에게 보여줄 안내 문구 (확대/부족 시)


def _execute_query(engine, sql, params):
    """DB 접속/쿼리 실행 1회. 재시도는 호출부에서 call_with_retry로 감쌈."""
    with engine.connect() as conn:
        return conn.execute(sql, params).fetchall()


def _query_breakdown(engine, sido: str, sigungu: str | None, month: int):
    """
    disaster_type별 건수를 집계해서 반환.
    sigungu가 주어지면 해당 시/군/구 + 시/도 전체("전체") 문자를 함께 포함.

    DB 호출이 재시도까지 다 실패하면 ToolUnavailableError가 발생함 -
    호출부(get_disaster_stats)가 이를 잡아서 "표본 부족"과 동일하게
    안전하게 강등 처리함 (억지로 통계를 만들어내지 않음).
    """
    if sigungu:
        sql = text("""
            SELECT disaster_type, COUNT(*) as cnt
            FROM disaster_messages
            WHERE is_missing_person = FALSE
              AND region_sido ILIKE :sido
              AND (region_sigungu ILIKE :sigungu OR region_sigungu = '전체')
              AND EXTRACT(MONTH FROM created_at) = :month
            GROUP BY disaster_type
            ORDER BY cnt DESC
        """)
        params = {"sido": f"%{sido}%", "sigungu": f"%{sigungu}%", "month": month}
    else:
        sql = text("""
            SELECT disaster_type, COUNT(*) as cnt
            FROM disaster_messages
            WHERE is_missing_person = FALSE
              AND region_sido ILIKE :sido
              AND EXTRACT(MONTH FROM created_at) = :month
            GROUP BY disaster_type
            ORDER BY cnt DESC
        """)
        params = {"sido": f"%{sido}%", "month": month}

    rows = call_with_retry(
        _execute_query, engine, sql, params,
        retryable_exceptions=(DBAPIError,),
        tool_name="stats_tool(DB)",
    )

    return [{"disaster_type": r[0], "count": r[1]} for r in rows]


_engine = None


def _get_engine():
    """
    엔진을 매 호출마다 새로 만들지 않고 재사용.
    Supabase Session Pooler가 전체 프로젝트 기준 최대 15개 연결로 제한되어 있어서,
    엔진을 계속 새로 만들면 풀이 금방 고갈됨 (실제로 겪은 장애 원인).
    pool_size를 작게 잡아서 이 도구 하나가 예산을 너무 많이 쓰지 않게 함.
    """
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_size=2, max_overflow=1, pool_timeout=10)
    return _engine


def get_disaster_stats(sido: str, sigungu: str = None, month: int = None) -> DisasterStatsResult:
    """
    지역(sido, sigungu) x 월(month) 조합의 재난 유형별 발생 빈도를 집계.
    표본 부족 시 자동으로 시/도 단위로 확대하고, 그 사실을 fallback_notice에 명시.

    DB 호출이 재시도까지 다 실패하면(ToolUnavailableError) 억지로 에러를 띄우지 않고
    "표본 부족"과 동일한 방식으로 안전하게 강등 처리함 (하위 로직이 변경 없이 재사용됨).
    """
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL이 .env에 설정되지 않았습니다.")
    if month is None or not (1 <= month <= 12):
        raise ValueError("month는 1~12 사이의 정수여야 합니다.")

    engine = _get_engine()

    try:
        # 1) 시/군/구 단위 시도
        breakdown = _query_breakdown(engine, sido, sigungu, month) if sigungu else []
        total = sum(item["count"] for item in breakdown)

        if sigungu and total >= MIN_SAMPLE_THRESHOLD:
            return _build_result(sido, sigungu, month, breakdown, total, scope_used="sigungu")

        # 2) 시/도 단위로 확대
        breakdown_sido = _query_breakdown(engine, sido, None, month)
        total_sido = sum(item["count"] for item in breakdown_sido)

        if total_sido >= MIN_SAMPLE_THRESHOLD:
            notice = None
            if sigungu:
                notice = (f"{sido} {sigungu}의 표본이 부족하여({total}건) "
                          f"{sido} 전체 기준으로 집계를 확대했습니다.")
            return _build_result(sido, sigungu, month, breakdown_sido, total_sido,
                                 scope_used="sido", fallback_notice=notice)

        # 3) 시/도 단위로도 부족 -> 표본 부족 솔직히 고지
        return DisasterStatsResult(
            sido=sido, sigungu=sigungu, month=month,
            total_count=total_sido, breakdown=[], scope_used="insufficient",
            fallback_notice=(f"{sido} 지역의 {month}월 표본이 매우 부족합니다({total_sido}건). "
                             f"통계적으로 유의미한 결과를 제공하기 어려우니, 해당 시기 일반 행동요령만 참고해주세요.")
        )

    except ToolUnavailableError as e:
        # DB 자체가 재시도까지 다 실패한 경우 - 통계 없이도 뒷단(RAG/에스컬레이션)이
        # 정상 동작할 수 있게 "표본 부족"과 동일한 형태로 안전하게 강등
        return DisasterStatsResult(
            sido=sido, sigungu=sigungu, month=month,
            total_count=0, breakdown=[], scope_used="insufficient",
            fallback_notice=f"통계 조회 서비스에 일시적인 문제가 있어 통계를 제공할 수 없습니다 ({e})."
        )


def _build_result(sido, sigungu, month, breakdown, total, scope_used, fallback_notice=None):
    ranked = sorted(breakdown, key=lambda x: x["count"], reverse=True)
    with_pct = [
        {**item, "pct": round(item["count"] / total * 100, 1)}
        for item in ranked
    ]
    return DisasterStatsResult(
        sido=sido, sigungu=sigungu, month=month,
        total_count=total, breakdown=with_pct,
        scope_used=scope_used, fallback_notice=fallback_notice
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("사용법: python tools/stats_tool.py <시도> [시군구] <월>")
        print("예: python tools/stats_tool.py 부산광역시 해운대구 8")
        sys.exit(1)

    if len(sys.argv) == 3:
        sido_arg, month_arg = sys.argv[1], sys.argv[2]
        sigungu_arg = None
    else:
        sido_arg, sigungu_arg, month_arg = sys.argv[1], sys.argv[2], sys.argv[3]

    result = get_disaster_stats(sido_arg, sigungu_arg, int(month_arg))

    print(f"\n=== {result.sido} {result.sigungu or ''} {result.month}월 재난 통계 ===")
    print(f"집계 범위: {result.scope_used} / 총 표본: {result.total_count}건")
    if result.fallback_notice:
        print(f"[안내] {result.fallback_notice}")
    print()
    for item in result.breakdown[:10]:
        print(f"  {item['disaster_type']}: {item['count']}건 ({item['pct']}%)")
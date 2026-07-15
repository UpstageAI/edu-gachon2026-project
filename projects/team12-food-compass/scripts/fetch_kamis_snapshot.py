"""KAMIS 전체 부류 가격 조회 → Supabase price_snapshot 적재.

1회성 테스트 및 향후 GitHub Actions cron의 기반이 되는 스크립트.

실행:
    $env:PYTHONUTF8=1
    .venv/Scripts/python.exe scripts/fetch_kamis_snapshot.py
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.kamis_client import CATEGORY_CODES, fetch_category_prices
from app.tools.price_snapshot import delete_old_snapshots, save_price_snapshot

# [2026-07-14 추가] price_snapshot이 매일 무한정 쌓이는 걸 막기 위한 보관 기간(일)
_RETENTION_DAYS = 7

# [2026-07-15 (2) 추가] 부류 6개를 간격 없이 연속 요청하는 게 WAF 오탐 요인 중 하나일
# 가능성을 낮추기 위한 최소한의 여유(price_gokr 쪽 _REQUEST_INTERVAL_SEC와 동일한 취지)
_REQUEST_INTERVAL_SEC = 0.5


def main() -> None:
    regday = date.today().isoformat()
    print(f"조회 기준일: {regday}")
    print("=" * 50)

    total_saved = 0
    failed_categories: list[str] = []
    for category_code, label in CATEGORY_CODES.items():
        try:
            items = fetch_category_prices(category_code, regday=regday)
        except Exception as e:
            # [2026-07-15 추가] fetch_category_prices에 재시도(최대 3회)가 있지만, 그래도
            # 실패하면(예: "406 Not Acceptable" 일시 차단) 이 부류 하나 때문에 나머지
            # 부류까지 전부 미처리되던 걸 막기 위해 건너뛰고 계속 진행(price_gokr 쪽과
            # 동일한 방어 패턴).
            print(f"[{category_code}] {label}: 조회 실패, 건너뜀: {e!r}")
            failed_categories.append(label)
            continue
        saved = save_price_snapshot(items, regday=regday)
        total_saved += saved
        print(f"[{category_code}] {label}: {len(items)}건 조회 -> {saved}건 저장")
        time.sleep(_REQUEST_INTERVAL_SEC)

    print("=" * 50)
    print(f"전체 저장 완료: {total_saved}건")
    if failed_categories:
        print(f"조회 실패로 건너뛴 부류 {len(failed_categories)}개: {failed_categories}")

    # 오늘자 저장이 다 끝난 뒤에 지우기 — 저장 도중 실패해도 기존 데이터가 먼저 날아가지 않도록
    # (일부 부류가 실패했어도 성공한 부류의 정리는 그대로 진행)
    deleted = delete_old_snapshots(retention_days=_RETENTION_DAYS)
    print(f"{_RETENTION_DAYS}일 이전 스냅샷 정리: {deleted}건 삭제")

    if failed_categories:
        # [2026-07-15 추가] 성공한 부류는 이미 저장·정리까지 끝났으니 여기서 죽지
        # 않지만, 실패가 있었다는 사실 자체는 GitHub Actions에서 "실패"로 보여야
        # 방치되지 않음(조용히 continue만 하면 매번 절반만 수집해도 초록불로 보여
        # 알아채기 어려움).
        sys.exit(1)


if __name__ == "__main__":
    main()

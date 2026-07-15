"""참가격(data.go.kr) 식품 품목·매장·가격 전체 조회 -> Supabase price_gokr_* 적재.

1회성 테스트 및 향후 GitHub Actions cron의 기반이 되는 스크립트.
scripts/fetch_kamis_snapshot.py와 동일한 구조 — 품목/매장 마스터는 매번 UPSERT만
하고, 가격 스냅샷만 보관 기간(retention) 정리 대상.

가격 조사 주기가 격주(2주 간격)라 정확한 조사일을 미리 알 수 없음 —
find_latest_inspect_day()로 아무 품목 하나(_PROBE_GOOD_ID) 기준 최신 조사일을
먼저 찾고, 그 날짜를 전체 식품 품목(약 457개)에 재사용함.

실행:
    $env:PYTHONUTF8=1
    .venv/Scripts/python.exe scripts/fetch_price_gokr_snapshot.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.tools.price_gokr_client import (
    fetch_all_stores,
    fetch_food_items,
    fetch_prices_for_item,
    find_latest_inspect_day,
)
from app.tools.price_gokr_snapshot import (
    delete_old_snapshots,
    save_items,
    save_price_snapshot,
    save_store_regions,
    save_stores,
)

# [2026-07-14 추가, 실제 사고 후 30일로 상향] 조사 주기가 격주보다도 더 불규칙하게
# 밀릴 수 있음이 실측으로 확인됨(2026-06-26 이후 다음 조사가 2주 뒤에도 안 올라옴) —
# delete_old_snapshots()의 "최신 good_inspect_day는 항상 보존" 안전장치와 함께 사용
_RETENTION_DAYS = 30

# 최신 조사일 탐색용 기준 품목 — 참이슬 오리지널(360ml), 조사 이력이 꾸준히 있어 선택
_PROBE_GOOD_ID = "265"

# 품목 하나당 API 호출 1회 — 457개 연속 호출 시 서버 부담을 줄이기 위한 간격(초)
_REQUEST_INTERVAL_SEC = 0.2


def main() -> None:
    print("[1/5] 식품 품목 마스터 조회 중...")
    items = fetch_food_items()
    saved_items = save_items(items)
    print(f"      {len(items)}개 품목 조회 -> {saved_items}건 저장(UPSERT)")

    print("[2/5] 판매처(매장) 마스터 조회 중...")
    stores = fetch_all_stores()
    saved_stores = save_stores(stores)
    print(f"      {len(stores)}개 매장 조회 -> {saved_stores}건 저장(UPSERT)")

    print("[3/5] 매장 지역(8개 권역) 분류 중...")
    region_result = save_store_regions()
    print(
        f"      분류 완료: {region_result['classified']}건, "
        f"분류 실패: {region_result['unclassified']}건"
    )

    print("[4/5] 최신 조사일 탐색 중...")
    inspect_day = find_latest_inspect_day(_PROBE_GOOD_ID)
    total_saved = 0
    failed_items: list[str] = []

    if inspect_day is None:
        # [2026-07-15 (4) 수정] 기존엔 여기서 바로 sys.exit(1)해서 [1~3/5]에서 이미
        # 저장한 품목/매장/지역 데이터는 남지만 보관정책 정리(delete_old_snapshots)를
        # 못 타고 죽었음 — "정리는 항상 실행, 실패 표시는 맨 마지막에" 원칙과 어긋나서
        # 나머지 흐름과 동일하게 맞춤(품목 조회 자체를 건너뛰고 실패 목록에 표시만).
        print("      최근 조사일을 찾지 못했습니다 — 조회 범위(21일)를 늘려야 할 수 있습니다.")
        failed_items.append("(전체: 최신 조사일 탐색 실패)")
    else:
        print(f"      최신 조사일: {inspect_day}")
        print(f"[5/5] {len(items)}개 품목의 {inspect_day}자 가격 조회 중...")
        for i, item in enumerate(items, start=1):
            good_id = item["good_id"]
            try:
                rows = fetch_prices_for_item(good_id, inspect_day)
            except Exception as e:
                # [2026-07-15 추가] fetch_prices_for_item 자체에 재시도(최대 3회)가 있지만,
                # 그래도 실패하는 경우(예: 그 품목만 지속적으로 타임아웃)에 스크립트 전체가
                # 죽어서 이미 성공한 품목 이후의 나머지가 전부 미처리되는 걸 실제로 겪음
                # (457개 중 50번째에서 실패 -> 407개 유실). 이 품목만 건너뛰고 계속 진행.
                print(f"      [{i}/{len(items)}] {item['good_name']} 조회 실패, 건너뜀: {e!r}")
                failed_items.append(item["good_name"])
                continue
            saved = save_price_snapshot(rows)
            total_saved += saved
            if i % 50 == 0 or i == len(items):
                print(f"      진행: {i}/{len(items)} ({item['good_name']}: {len(rows)}건)")
            time.sleep(_REQUEST_INTERVAL_SEC)

    print("=" * 50)
    print(f"가격 스냅샷 전체 저장 완료: {total_saved}건")
    if failed_items:
        print(f"조회 실패로 건너뛴 품목 {len(failed_items)}개: {failed_items}")

    # 전체 저장이 다 끝난 뒤에 지우기 — 저장 도중 실패해도 기존 데이터가 먼저 날아가지 않도록
    # (일부 품목이 실패했어도, 심지어 조사일 탐색 자체가 실패했어도 정리는 그대로 진행)
    deleted = delete_old_snapshots(retention_days=_RETENTION_DAYS)
    print(f"{_RETENTION_DAYS}일 이전 스냅샷 정리: {deleted}건 삭제")

    if failed_items:
        # [2026-07-15 추가] 성공한 품목은 이미 저장·정리까지 끝났으니 여기서 죽지
        # 않지만, 실패가 있었다는 사실 자체는 GitHub Actions에서 "실패"로 보여야
        # 방치되지 않음(조용히 continue만 하면 매번 일부만 수집해도 초록불로 보임).
        sys.exit(1)


if __name__ == "__main__":
    main()

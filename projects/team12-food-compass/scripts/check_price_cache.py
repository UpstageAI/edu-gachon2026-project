"""price_cache 저장/조회 동작을 터미널에서 직접 확인하는 스크립트.

실행:
    $env:PYTHONUTF8=1
    .venv/Scripts/python.exe scripts/check_price_cache.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas import RawPriceOutput
from app.tools.price_cache import get_price_cache, save_price_cache

SAMPLE = RawPriceOutput(
    item_name="상추",
    dpr1="4,500",
    dpr5="3,800",
    dpr7="2,800",
    unit="100g",
)


def main() -> None:
    print("=" * 50)
    print("[1] 상추 가격 캐시 저장 (UPSERT)")
    save_price_cache("상추", SAMPLE)
    print("  -> 저장 완료")

    print("\n[2] 상추 캐시 조회")
    result = get_price_cache("상추")
    if result:
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        print("  -> 캐시 없음")

    print("\n[3] 등록되지 않은 품목 조회 (None 반환 확인)")
    missing = get_price_cache("__없는품목__")
    print(f"  -> {missing}")

    print("\n모든 확인 완료")
    print("=" * 50)


if __name__ == "__main__":
    main()

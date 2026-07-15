"""
scripts/fix_broken_nutrition.py
원본 식약처 데이터에 섞인 '깨진 영양값'을 교정한다(1회성).

원본 cookrcp01_all.csv 자체에 클럽샌드위치 1kcal, 파르페 0kcal 같은 입력 오류가 있다.
원본을 못 고치므로 우리 런타임 CSV(foods_samsam.csv)에서 교정한다.

교정 규칙(안전하게 '완전 결측'만 손댄다):
  - kcal ≤ 1 이고 탄단지도 전부 ≤ 1 → 완전 결측(입력 오류). 대표값으로 채움.
    (샌드위치·덮밥류 한 끼 기준): kcal 250 / 탄 30 / 단 20 / 지 10 / 나트륨 250

  ※ 탄단지 역산 교정은 하지 않는다. 삼삼 데이터의 g은 1인분이 아닌 경우가 있어
    역산하면 장어조림 4685kcal처럼 폭발한다. 표기 kcal을 신뢰한다.

실행: uv run python scripts/fix_broken_nutrition.py   (--dry 로 미리보기)
"""

import shutil
import sys
from pathlib import Path

import pandas as pd

CSV = Path(__file__).resolve().parent.parent / "app" / "data" / "foods_samsam.csv"

# 완전 결측 시 채울 대표값(한 끼 메인 기준)
DEFAULT = {"kcal": 250.0, "carbohydrate": 30.0, "protein": 20.0, "fat": 10.0, "sodium": 250.0}


def main(dry: bool = False) -> None:
    df = pd.read_csv(CSV)
    fixed_full = 0

    for i, row in df.iterrows():
        macros_broken = (row.carbohydrate <= 1) and (row.protein <= 1) and (row.fat <= 1)
        # 완전 결측(kcal·탄단지 모두 ≤1) → 대표값으로 채움
        if row.kcal <= 1 and macros_broken:
            for col, val in DEFAULT.items():
                df.at[i, col] = val
            fixed_full += 1
            print(f"[결측→대표값] {row.food_name}: {row.kcal}kcal → 250kcal")

    print(f"\n교정: 결측 대표값 {fixed_full}건")
    if dry:
        print("(--dry: 저장 안 함)")
        return

    backup = CSV.with_suffix(".csv.bak")
    if not backup.exists():
        shutil.copy(CSV, backup)
        print(f"백업 생성: {backup.name}")
    df.to_csv(CSV, index=False)
    print(f"저장 완료: {CSV.name}")


if __name__ == "__main__":
    main(dry="--dry" in sys.argv)

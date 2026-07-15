"""
scripts/curate_salads.py

샐러드·샌드위치 큐레이션 (2차 정제).

배경:
  1차 정제(reclassify_foods.py) 후에도 샐러드·샌드위치가 61개 남아
  조합에 양식/퓨전(시저·클럽·펜네파스타·코울슬로 등)이 섞여 나왔다.
  → 사용자 결정: 샐러드·샌드위치는 전부 '한그릇'으로 통일 + 한식·건강식 15개만 남기고 삭제.

동작(현재 app/data/foods_samsam.csv 기준):
  1. 이름에 '샐러드' 또는 '샌드위치'가 든 항목 중 KEEP_SALAD_SANDWICH에 없는 것은 삭제.
  2. 남는 샐러드·샌드위치는 meal_role='한그릇'으로 통일(반찬에 있던 것도 옮김).

입력/출력: app/data/foods_samsam.csv (덮어쓰기, .bak2 백업)

사용: uv run python scripts/curate_salads.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CSV = ROOT / "app" / "data" / "foods_samsam.csv"
BACKUP = ROOT / "app" / "data" / "foods_samsam.csv.bak2"

# 남길 샐러드·샌드위치 (한식·건강식 15개, docs/샐러드샌드위치_큐레이션.md)
KEEP_SALAD_SANDWICH = {
    "아보카도 연어샐러드",
    "아보카도 두부 샐러드",
    "새콤한연어샐러드",
    "연어샐러드",
    "훈제오리가슴살 샐러드",
    "구운 닭고기 샐러드와 저나트륨 과일 드레싱",
    "퀴노아닭가슴살샐러드",
    "주꾸미샐러드",
    "깻잎향을 입힌 관자 샐러드",
    "두부채소샐러드",
    "토마토제철나물 샐러드",
    "돌나물 샐러드",
    "두릅 샐러드",
    "두부 샌드위치",
    "단호박 양파잼 샌드위치",
}

# 샐러드·샌드위치는 아니지만 명백한 양식/퓨전(브리또·라이스페이퍼롤·딤섬 등) — 삭제.
# 실측에서 조합에 섞여 나온 것들(수퍼 브리또, 라이스페이퍼 새우롤 등).
EXTRA_WESTERN_DELETE = {
    "닭고기또띠아",
    "닭고기월남쌈",
    "삼색딤섬",
    "리코타치즈돈가스",
    "라이스페이퍼 야채롤",
    "리코타치즈 카프레제",
    "라이스페이퍼 수제소시지",
    "라이스페이퍼 새우롤",
    "수퍼 브리또",
    "오븐에 구운 또띠아 칩과 아보카도 딥",
    "참외지 리코타버무리",
}


def main() -> None:
    dry = "--dry-run" in sys.argv
    df = pd.read_csv(CSV)
    before = len(df)

    is_salad = df["food_name"].str.contains("샐러드|샌드위치", na=False)
    keep_mask = df["food_name"].isin(KEEP_SALAD_SANDWICH)

    # 삭제: (샐러드/샌드위치인데 KEEP에 없는 것) + (명시 양식/퓨전)
    to_drop = (is_salad & ~keep_mask) | df["food_name"].isin(EXTRA_WESTERN_DELETE)
    dropped = sorted(df[to_drop]["food_name"].tolist())

    # KEEP에 있는데 데이터에 실제로 없는 이름(오타 방지) 경고
    present = set(df.loc[is_salad, "food_name"])
    missing_keep = sorted(KEEP_SALAD_SANDWICH - present)

    df = df[~to_drop].copy()

    # 남은 샐러드·샌드위치는 전부 한그릇으로 통일
    still = df["food_name"].str.contains("샐러드|샌드위치", na=False)
    role_before = df.loc[still, "meal_role"].value_counts().to_dict()
    df.loc[still, "meal_role"] = "한그릇"

    after = len(df)
    kept = sorted(df.loc[still, "food_name"].tolist())

    print(f"샐러드·샌드위치 삭제 {len(dropped)}개 / 유지 {len(kept)}개")
    print(f"전체: {before} → {after}개")
    print(f"유지 항목 역할(삭제 전): {role_before} → 전부 '한그릇' 통일")
    if missing_keep:
        print(f"⚠️ KEEP인데 데이터에 없음(오타 의심): {missing_keep}")
    print("\n[유지된 샐러드·샌드위치]")
    for n in kept:
        print(f"  - {n}")

    if dry:
        print("\n[dry-run] 저장 안 함.")
        return

    pd.read_csv(CSV).to_csv(BACKUP, index=False)
    df.to_csv(CSV, index=False)
    print(f"\n완료. 백업: {BACKUP.name}")
    print("최종 meal_role 분포:")
    print(df["meal_role"].value_counts().to_string())


if __name__ == "__main__":
    main()

"""
scripts/apply_llm_classification.py

classify_korean_llm.py가 만든 foods_classified.csv의 라벨을 적용.
사용자 결정: drop + borderline 전부 삭제, keep만 남긴다.

입력:  app/data/foods_classified.csv (llm_label 컬럼 포함)
출력:  app/data/foods_samsam.csv (덮어쓰기, .bak3 백업, 분류/이유 컬럼 제거)

사용: uv run python scripts/apply_llm_classification.py [--dry-run]
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIED = ROOT / "app" / "data" / "foods_classified.csv"
CSV = ROOT / "app" / "data" / "foods_samsam.csv"
BACKUP = ROOT / "app" / "data" / "foods_samsam.csv.bak3"


# LLM이 keep으로 놓친 명백한 양식/디저트 — 키워드 안전망(정확한 이름).
# (LLM 전수분류는 80%만 잡음. 이름에 아래가 들어가면 정체성이 양식이라 확실히 삭제.)
KEYWORD_SAFETY_NET = [
    "웰링턴",
    "베이컨",
    "까스",
    "비프",
    "타르타르",
    "밀푀유",
    "라떼",
    "라비올리",
    "커틀",
    "모히또",
    "판나코타",
    "파나코타",
    "스콘",
    "스무디",
    "쉐이크",
    "샤벳",
    "소르베",
    "크림스튜",
    "로제스튜",
    "크림닭",
    "크림볶음밥",
    "라자냐",
    "라타냐",
    "아란치니",
    "뇨키",
    "뇨끼",
    "카프레",
    "카프리",
    "파피요트",
    "니고랭",
    "사모사",
    "뮤즐리",
    "에피타이저",
    "프리타타",
    "케이준",
    "헝가리",
    "밀라노",
    "다쿠아즈",
    "마들렌",
    "티라미수",
    "파르페",
    "크레이프",
    "퐁듀",
    "샹그리아",
    "그라탕",
    "그라탱",
]


def main() -> None:
    dry = "--dry-run" in sys.argv
    df = pd.read_csv(CLASSIFIED)
    before = len(df)

    llm_mask = df["llm_label"].isin(["drop", "borderline"])
    kw_mask = df["food_name"].str.contains("|".join(KEYWORD_SAFETY_NET), na=False)
    # 안전망으로 추가 삭제되는 것(LLM은 keep이었던)
    added = df[kw_mask & ~llm_mask][["food_name", "meal_role"]]
    drop_mask = llm_mask | kw_mask
    dropped = df[drop_mask][["food_name", "meal_role", "llm_label", "llm_reason"]]
    keep = df[~drop_mask].drop(columns=["llm_label", "llm_reason"])

    print(
        f"전체 {before} → keep {len(keep)} (삭제 {len(dropped)}: "
        f"LLM drop {(df['llm_label'] == 'drop').sum()} + borderline "
        f"{(df['llm_label'] == 'borderline').sum()} + 키워드안전망 {len(added)})"
    )
    print(f"\n[키워드 안전망으로 추가 삭제 — LLM이 놓친 양식 {len(added)}개]")
    for _, r in added.iterrows():
        print(f"  [{r['meal_role']}] {r['food_name']}")

    print("\n[삭제 후 meal_role 분포]")
    print(keep["meal_role"].value_counts().to_string())

    if dry:
        print("\n[dry-run] 저장 안 함.")
        return

    pd.read_csv(CSV).to_csv(BACKUP, index=False)
    keep.to_csv(CSV, index=False)
    print(f"\n완료. 백업: {BACKUP.name} / foods_samsam.csv = {len(keep)}개")


if __name__ == "__main__":
    main()

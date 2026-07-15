"""삼삼한 밥상(COOKRCP01) 원본 → FoodItem 스키마 어댑터.

입력:  app/data/cookrcp01_all.csv  (식약처 조리식품 레시피 DB, 1146행)
       app/data/foods_clean.csv    (흰밥 병합용)
출력:  app/data/foods_samsam.csv   (파이프라인이 쓸 정본)

처리 (docs/12 계획):
  1. BOM 제거 (﻿RCP_PARTS_DTLS → RCP_PARTS_DTLS)
  2. 컬럼명 매핑 (RCP_*/INFO_* → FoodItem 필드)
  3. meal_role 매핑 (RCP_PAT2 → 밥/국물/반찬/한그릇/간식/기타)
  4. 당류=빈값, serving_size 결측 처리
  5. 이상치 제거 (탄단지>1000 or kcal>1200)
  6. 레시피 단계/사진/저감팁/재료를 필드로 정리
  7. 흰밥류를 foods_clean에서 병합

건강식 기준 v4 반영: serving_size는 완성요리 1인분으로 확정 사용(실측 검증됨).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "app" / "data"
SRC_SAMSAM = DATA_DIR / "cookrcp01_all.csv"
SRC_CLEAN = DATA_DIR / "foods_clean.csv"
DST = DATA_DIR / "foods_samsam.csv"

# RCP_PAT2(요리종류) → 우리 meal_role
ROLE_MAP = {
    "밥": "밥",
    "국&찌개": "국물",
    "반찬": "반찬",
    "일품": "한그릇",
    "후식": "간식",
    "기타": "기타",
}

# 출력 컬럼 (FoodItem 확장 스키마)
FIELDS = [
    "food_id",
    "food_name",
    "meal_role",
    "serving_size",
    "kcal",
    "carbohydrate",
    "protein",
    "fat",
    "sugar",
    "sodium",
    "recipe_steps",  # JSON 배열 문자열
    "recipe_images",  # JSON 배열 문자열
    "ingredients",  # 재료 원문
    "na_tip",  # 나트륨 저감팁
    "source",  # samsam / foods_clean
]

# 병합할 흰밥 이름 (foods_clean에서, 순수 밥류만)
WANTED_RICE = {
    "쌀밥",
    "현미밥",
    "잡곡밥",
    "귀리밥",
    "보리밥",
    "흑미밥",
    "완두콩밥",
    "강낭콩밥",
}


def to_float(value: str) -> float | None:
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def strip_bom_keys(row: dict) -> dict:
    """CSV 첫 컬럼명에 붙은 BOM(\\ufeff) 제거."""
    return {k.lstrip("﻿"): v for k, v in row.items()}


def collect_recipe(row: dict) -> tuple[list[str], list[str]]:
    """MANUAL01~20 조리단계, MANUAL_IMG01~20 사진을 순서대로 리스트로."""
    steps, images = [], []
    for i in range(1, 21):
        step = (row.get(f"MANUAL{i:02d}") or "").strip()
        img = (row.get(f"MANUAL_IMG{i:02d}") or "").strip()
        if step:
            steps.append(step)
        if img:
            images.append(img)
    return steps, images


def is_outlier(kcal, carb, protein, fat) -> bool:
    if kcal is not None and kcal > 1200:
        return True
    return any(v is not None and v > 1000 for v in (carb, protein, fat))


def load_samsam() -> list[dict]:
    out = []
    dropped_outlier = 0
    dropped_role = 0
    with SRC_SAMSAM.open(encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            row = strip_bom_keys(raw)
            role = ROLE_MAP.get((row.get("RCP_PAT2") or "").strip())
            if role is None:
                dropped_role += 1
                continue

            kcal = to_float(row.get("INFO_ENG"))
            carb = to_float(row.get("INFO_CAR"))
            protein = to_float(row.get("INFO_PRO"))
            fat = to_float(row.get("INFO_FAT"))
            sodium = to_float(row.get("INFO_NA"))

            if is_outlier(kcal, carb, protein, fat):
                dropped_outlier += 1
                continue

            steps, images = collect_recipe(row)
            out.append(
                {
                    "food_id": int(row.get("RCP_SEQ", "0").strip()),  # RCP_SEQ → 정수 id
                    "food_name": (row.get("RCP_NM") or "").strip(),
                    "meal_role": role,
                    "serving_size": to_float(row.get("INFO_WGT")) or "",  # 결측이면 빈값
                    "kcal": kcal if kcal is not None else 0,
                    "carbohydrate": carb if carb is not None else 0,
                    "protein": protein if protein is not None else 0,
                    "fat": fat if fat is not None else 0,
                    "sugar": "",  # 당류 데이터 없음 (v4: 검증 범위 밖)
                    "sodium": sodium if sodium is not None else 0,
                    "recipe_steps": json.dumps(steps, ensure_ascii=False),
                    "recipe_images": json.dumps(images, ensure_ascii=False),
                    "ingredients": (row.get("RCP_PARTS_DTLS") or "").strip(),
                    "na_tip": (row.get("RCP_NA_TIP") or "").strip(),
                    "source": "samsam",
                }
            )
    print(
        f"삼삼한밥상: {len(out)}행 유지 (이상치 {dropped_outlier} · 역할없음 {dropped_role} 제외)"
    )
    return out


RICE_ID_BASE = 90000  # 흰밥 id는 삼삼한밥상 RCP_SEQ와 겹치지 않게 90001~ 부여(정수 통일)


def load_rice() -> list[dict]:
    """foods_clean에서 순수 흰밥류만 병합."""
    out = []
    with SRC_CLEAN.open(encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            row = strip_bom_keys(raw)
            name = (row.get("food_name") or "").strip()
            if row.get("meal_role") != "밥":
                continue
            # 순수 밥류만 (볶음밥·비빔밥·김밥 등 제외), '_' 파편도 제외
            if name not in WANTED_RICE:
                continue
            out.append(
                {
                    "food_id": RICE_ID_BASE + len(out) + 1,  # 90001, 90002, ... (정수)
                    "food_name": name,
                    "meal_role": "밥",
                    "serving_size": to_float(row.get("serving_size")) or "",
                    "kcal": to_float(row.get("kcal")) or 0,
                    "carbohydrate": to_float(row.get("carbohydrate")) or 0,
                    "protein": to_float(row.get("protein")) or 0,
                    "fat": to_float(row.get("fat")) or 0,
                    "sugar": to_float(row.get("sugar")) or "",
                    "sodium": to_float(row.get("sodium")) or 0,
                    "recipe_steps": "[]",
                    "recipe_images": "[]",
                    "ingredients": "",
                    "na_tip": "",
                    "source": "foods_clean",
                }
            )
    print(f"흰밥 병합: {len(out)}행 ({sorted(r['food_name'] for r in out)})")
    return out


def main() -> None:
    rows = load_samsam() + load_rice()
    with DST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    from collections import Counter

    by_role = Counter(r["meal_role"] for r in rows)
    print(f"\n총 {len(rows)}행 → {DST}")
    print("meal_role별:", dict(by_role))


if __name__ == "__main__":
    main()

"""
scripts/import_foods_to_supabase.py
foods_samsam.csv → Supabase foods 테이블 적재.

- 데이터 소스: 식약처 "삼삼한 밥상" 가공본(cookrcp01_all.csv → foods_samsam.csv).
  개별 식품이 아니라 완성 요리 단위 → 레시피 단계·사진·재료·나트륨 저감팁 포함.
- 사용자가 원할 때만 수동 실행하는 1회성 배치 (배포 런타임에는 안 돎).
- food_id 기준 upsert → 재실행 안전. 같은 id는 갱신, 새 id는 추가.
- 이 스크립트는 영양/레시피/이름/역할만 넣는다. search_text/embedding은 embed_foods.py가 채운다.
- serving_size/sugar는 삼삼한밥상에 결측이 있어 NULL 허용(테이블도 NULL 허용).

⚠️ 사전 준비: database/001_foods.sql을 Supabase SQL Editor에서 먼저 실행해
   테이블을 재생성해 둘 것(옛 데이터 제거 + 레시피 컬럼 추가).

실행:
    uv run python scripts/import_foods_to_supabase.py
"""

import json
from pathlib import Path

import pandas as pd

from app.services.supabase_client import get_client

CSV_PATH = Path(__file__).resolve().parent.parent / "app" / "data" / "foods_samsam.csv"

# NOT NULL 숫자 컬럼 (결측이면 적재 불가 → 사전 검증)
REQUIRED_NUM = ["kcal", "carbohydrate", "protein", "fat", "sodium"]
# NULL 허용 숫자 컬럼 (삼삼한밥상 결측 있음)
OPTIONAL_NUM = ["serving_size", "sugar"]
# 레시피 텍스트 컬럼
TEXT_COLS = ["ingredients", "na_tip", "source"]


def _opt_float(v):
    """빈값·NaN → None, 그 외 → float."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _json_list(v):
    """CSV의 JSON 배열 문자열 → list. jsonb 컬럼에 그대로 들어감. 실패 시 []."""
    s = str(v).strip() if v is not None else ""
    if not s or s.lower() == "nan":
        return []
    try:
        parsed = json.loads(s)
        return parsed if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _text(v):
    s = str(v).strip() if v is not None else ""
    return "" if s.lower() == "nan" else s


def main() -> None:
    df = pd.read_csv(CSV_PATH)

    base_cols = ["food_id", "food_name", "meal_role"] + REQUIRED_NUM
    missing = [c for c in base_cols if c not in df.columns]
    if missing:
        raise SystemExit(f"CSV에 누락된 필수 컬럼: {missing}")

    records = []
    for _, row in df.iterrows():
        rec = {
            "food_id": int(row["food_id"]),
            "food_name": str(row["food_name"]),
            "meal_role": str(row["meal_role"]),
        }
        for c in REQUIRED_NUM:
            rec[c] = float(row[c])
        for c in OPTIONAL_NUM:
            rec[c] = _opt_float(row.get(c)) if c in df.columns else None
        rec["recipe_steps"] = _json_list(row.get("recipe_steps"))
        rec["recipe_images"] = _json_list(row.get("recipe_images"))
        for c in TEXT_COLS:
            rec[c] = _text(row.get(c)) if c in df.columns else ""
        records.append(rec)

    client = get_client()
    # food_id 유니크 제약 기준 upsert. 큰 배치는 나눠서.
    batch = 500
    total = 0
    for i in range(0, len(records), batch):
        chunk = records[i : i + batch]
        client.table("foods").upsert(chunk, on_conflict="food_id").execute()
        total += len(chunk)
        print(f"  upsert {total}/{len(records)}")

    count = client.table("foods").select("food_id", count="exact").limit(1).execute().count
    print(f"완료. foods 테이블 총 {count}개.")


if __name__ == "__main__":
    main()

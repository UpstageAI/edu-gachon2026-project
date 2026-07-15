"""검토를 마친 카테고리 CSV(generate_ingredient_categories.py 결과)를 Supabase에 적재한다.

db/migrations/0008_ingredients_category.sql이 이미 Supabase에 적용되어 ingredients_category
테이블과 ingredients_master.category_id 컬럼이 존재해야 실행할 수 있다.
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.supabase_client import get_supabase

DEFAULT_INPUT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "ingredient_categories_review.csv"
)


def read_review_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="리뷰 완료된 재료 카테고리 CSV를 ingredients_category/ingredients_master에 적재"
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH)
    parser.add_argument(
        "--apply", action="store_true", help="실제로 Supabase에 반영 (기본값은 dry-run)"
    )
    args = parser.parse_args()

    rows = read_review_csv(args.input)
    category_names = sorted({row["category"] for row in rows})
    print(f"재료 {len(rows)}건, 카테고리 {len(category_names)}종을 적재할 준비가 됐다:")
    print(category_names)

    if not args.apply:
        print("(dry-run) --apply 없이 실행했으므로 아무것도 반영하지 않았다.")
        return

    supabase = get_supabase()

    category_id_by_name = {}
    for name in category_names:
        response = (
            supabase.table("ingredients_category")
            .upsert({"name": name}, on_conflict="name")
            .execute()
        )
        category_id_by_name[name] = response.data[0]["id"]

    for i, row in enumerate(rows):
        category_id = category_id_by_name[row["category"]]
        supabase.table("ingredients_master").update({"category_id": category_id}).eq(
            "id", row["ingredient_id"]
        ).execute()
        if (i + 1) % 200 == 0:
            print(f"{i + 1}/{len(rows)}건 반영")

    print(f"{len(rows)}건 반영 완료.")


if __name__ == "__main__":
    main()

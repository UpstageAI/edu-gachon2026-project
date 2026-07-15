import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.data.supabase_client import get_supabase
from app.ingestion.allergens import resolve_allergen_id


def fetch_all(table: str, columns: str) -> list[dict]:
    supabase = get_supabase()
    rows: list[dict] = []
    page = 0
    page_size = 1000
    while True:
        response = (
            supabase.table(table)
            .select(columns)
            .range(page * page_size, page * page_size + page_size - 1)
            .execute()
        )
        if not response.data:
            break
        rows.extend(response.data)
        page += 1
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "기존 ingredients_master 행의 allergen_id만 재계산해 갱신 (id/name은 건드리지 않음)"
        )
    )
    parser.add_argument(
        "--apply", action="store_true", help="실제로 Supabase에 반영 (기본값은 dry-run)"
    )
    args = parser.parse_args()

    allergens = fetch_all("allergen_master", "id, allergen_name")
    allergen_id_by_name = {a["allergen_name"]: a["id"] for a in allergens}

    ingredients = fetch_all("ingredients_master", "id, name, allergen_id")

    changes = []
    for ingredient in ingredients:
        new_allergen_id = resolve_allergen_id(ingredient["name"], allergen_id_by_name)
        if new_allergen_id != ingredient["allergen_id"]:
            changes.append((ingredient["id"], ingredient["name"], new_allergen_id))

    print(f"재료 {len(ingredients)}개 중 {len(changes)}건의 allergen_id가 변경 대상입니다.")

    if not args.apply:
        print("(dry-run) --apply 없이 실행했으므로 아무것도 반영하지 않았습니다.")
        return

    supabase = get_supabase()
    for ingredient_id, _name, new_allergen_id in changes:
        supabase.table("ingredients_master").update({"allergen_id": new_allergen_id}).eq(
            "id", ingredient_id
        ).execute()

    print(f"{len(changes)}건 반영 완료.")


if __name__ == "__main__":
    main()

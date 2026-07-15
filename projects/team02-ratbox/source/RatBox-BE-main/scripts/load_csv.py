import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.pipeline import process_csv
from app.ingestion.schemas import (
    TABLE_ALLERGEN_MASTER,
    TABLE_INGREDIENTS_CATEGORY,
    TABLE_INGREDIENTS_MASTER,
    TABLE_RECIPE_INGREDIENTS,
    TABLE_RECIPES,
)
from app.ingestion.supabase_loader import get_supabase_client, load_dataframe


def main() -> None:
    parser = argparse.ArgumentParser(description="레시피 검색 CSV를 Supabase에 적재")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()

    result = process_csv(args.csv_path)
    client = get_supabase_client()

    # 마스터 데이터를 먼저 적재해야 하위 테이블의 FK 참조가 유효함
    # (allergen_master/ingredients_category -> ingredients_master -> recipes ->
    # recipe_ingredients 순).
    # unique 컬럼 기준 upsert로 재실행 시 중복 생성을 막지만,
    # recipe_ingredients는 unique 제약이 없어 재실행 시 중복될 수 있음 (재적재 전 비우고 실행 권장).
    load_dataframe(
        client, TABLE_ALLERGEN_MASTER, result.allergen_master, on_conflict="allergen_name"
    )
    load_dataframe(
        client, TABLE_INGREDIENTS_CATEGORY, result.ingredients_category, on_conflict="name"
    )
    load_dataframe(client, TABLE_INGREDIENTS_MASTER, result.ingredients_master, on_conflict="name")
    load_dataframe(client, TABLE_RECIPES, result.recipes, on_conflict="source_recipe_no")
    load_dataframe(client, TABLE_RECIPE_INGREDIENTS, result.recipe_ingredients)

    print(
        f"알레르기 {len(result.allergen_master)}개, 레시피 {len(result.recipes)}개, "
        f"표준 재료 {len(result.ingredients_master)}개, "
        f"레시피-재료 매핑 {len(result.recipe_ingredients)}개 적재 완료"
    )


if __name__ == "__main__":
    main()

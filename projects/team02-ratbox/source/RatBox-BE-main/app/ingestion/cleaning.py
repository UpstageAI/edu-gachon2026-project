import re
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.ingestion.allergens import build_allergen_master, resolve_allergen_id
from app.ingestion.constants import (
    EXCLUDED_INGREDIENT_NAMES,
    SYNONYM_TO_STANDARD,
    build_ingredient_category_master,
    get_ingredient_category,
)
from app.ingestion.ingredient_parser import parse_ingredient_text
from app.ingestion.schemas import REQUIRED_SOURCE_COLUMNS, SOURCE_CSV_ENCODING
from app.ingestion.validators import require_columns

_SERVINGS_PATTERN = re.compile(r"(\d+)")
_HOURS_PATTERN = re.compile(r"(\d+)\s*시간")
_MINUTES_PATTERN = re.compile(r"(\d+)\s*분")

RECIPE_REQUIRED_FIELDS = [
    "name",
    "cooking_time",
    "difficulty",
    "servings",
    "category",
    "cooking_method",
]


def load_recipe_search_csv(filepath: Path) -> pd.DataFrame:
    df = pd.read_csv(filepath, encoding=SOURCE_CSV_ENCODING)
    require_columns(df, REQUIRED_SOURCE_COLUMNS, "레시피 CSV")
    return df


def parse_servings(text) -> int | None:
    if not isinstance(text, str):
        return None
    match = _SERVINGS_PATTERN.search(text)
    return int(match.group(1)) if match else None


def parse_cooking_time_minutes(text) -> int | None:
    if not isinstance(text, str):
        return None
    hours_match = _HOURS_PATTERN.search(text)
    minutes_match = _MINUTES_PATTERN.search(text)
    if not hours_match and not minutes_match:
        return None
    hours = int(hours_match.group(1)) if hours_match else 0
    minutes = int(minutes_match.group(1)) if minutes_match else 0
    return hours * 60 + minutes


def parse_registered_at(value) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if len(text) != 14 or not text.isdigit():
        return None
    return datetime.strptime(text, "%Y%m%d%H%M%S").isoformat()


def build_recipes(df: pd.DataFrame) -> pd.DataFrame:
    # cooking_time/servings는 pandas Series.apply()를 거치면 int+None 혼합이
    # float64(NaN)로 업캐스트되어 Postgres INTEGER 컬럼에 "15.0" 형태로 들어가 실패한다.
    # 리스트 컴프리헨션 + dtype="object"로 만들어 원본 int/None 타입을 그대로 유지한다.
    cooking_time = pd.Series(
        [parse_cooking_time_minutes(v) for v in df["CKG_TIME_NM"]], dtype="object", index=df.index
    )
    servings = pd.Series(
        [parse_servings(v) for v in df["CKG_INBUN_NM"]], dtype="object", index=df.index
    )

    recipes = pd.DataFrame(
        {
            "id": [str(uuid.uuid4()) for _ in range(len(df))],
            "source_recipe_no": df["RCP_SNO"],
            "name": df["CKG_NM"],
            "cooking_time": cooking_time,
            "difficulty": df["CKG_DODF_NM"],
            "servings": servings,
            "category": df["CKG_KND_ACTO_NM"],
            "cooking_method": df["CKG_MTH_ACTO_NM"],
            "created_at": df["FIRST_REG_DT"].apply(parse_registered_at),
        },
        index=df.index,
    )

    # 필수 컬럼(NOT NULL) 중 원본에 값이 없던 행은 기본값을 채우지 않고 통째로 제외한다.
    is_complete = recipes[RECIPE_REQUIRED_FIELDS].notna().all(axis=1)
    # 재료 중 하나라도 이름/수량/단위가 불완전하면, 그 재료만 빼는 게 아니라 레시피 자체를 제외한다.
    has_complete_ingredients = df["CKG_MTRL_CN"].apply(_all_ingredients_complete)
    return recipes[is_complete & has_complete_ingredients]


def _all_ingredients_complete(raw) -> bool:
    items = parse_ingredient_text(raw)
    if not items:
        return False
    return all(
        item["name"]
        and item["name"] not in EXCLUDED_INGREDIENT_NAMES
        and item["amount"] is not None
        and item["unit"] is not None
        for item in items
    )


def build_ingredient_tables(
    df: pd.DataFrame, recipes_df: pd.DataFrame
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    included = df.loc[recipes_df.index]

    rows = []
    for recipe_id, raw_ingredients in zip(recipes_df["id"], included["CKG_MTRL_CN"]):
        for item in parse_ingredient_text(raw_ingredients):
            standard_name = SYNONYM_TO_STANDARD.get(item["name"], item["name"])
            rows.append(
                {
                    "recipe_id": recipe_id,
                    "ingredient_name": standard_name,
                    "amount": item["amount"],
                    "unit": item["unit"],
                }
            )
    recipe_ingredients = pd.DataFrame(
        rows, columns=["recipe_id", "ingredient_name", "amount", "unit"]
    )

    allergen_master = build_allergen_master()
    allergen_id_by_name = dict(zip(allergen_master["allergen_name"], allergen_master["id"]))

    ingredients_category = build_ingredient_category_master()
    category_id_by_name = dict(zip(ingredients_category["name"], ingredients_category["id"]))

    unique_names = recipe_ingredients["ingredient_name"].unique()
    ingredients_master = pd.DataFrame(
        {
            "id": [str(uuid.uuid4()) for _ in range(len(unique_names))],
            "name": unique_names,
            "category_id": [
                category_id_by_name[get_ingredient_category(name)] for name in unique_names
            ],
            "allergen_id": [
                resolve_allergen_id(name, allergen_id_by_name) for name in unique_names
            ],
        }
    )

    ingredient_id_by_name = dict(zip(ingredients_master["name"], ingredients_master["id"]))
    recipe_ingredients = recipe_ingredients.assign(
        id=[str(uuid.uuid4()) for _ in range(len(recipe_ingredients))],
        ingredient_id=recipe_ingredients["ingredient_name"].map(ingredient_id_by_name),
        is_required=True,
    )[["id", "recipe_id", "ingredient_id", "amount", "unit", "is_required"]]

    return recipe_ingredients, ingredients_master, allergen_master, ingredients_category

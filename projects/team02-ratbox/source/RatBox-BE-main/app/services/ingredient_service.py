from uuid import UUID

from app.data.repositories.ingredient_repository import (
    find_all_categories,
    find_ingredients_by_category_id,
)
from app.data.repositories.user_allergen_repository import find_user_allergens
from app.data.repositories.user_repository import find_user_by_id
from app.domain.models import Allergen, Ingredient, IngredientCategory


class UserNotFoundError(Exception):
    pass


class CategoryNotFoundError(Exception):
    pass


def list_categories() -> list[IngredientCategory]:
    rows = find_all_categories()
    return [IngredientCategory(id=row["id"], name=row["name"]) for row in rows]


def confirm_ingredient_selection(
    user_id: UUID, category_id: UUID
) -> tuple[list[Ingredient], list[Allergen]]:
    if not find_user_by_id(str(user_id)):
        raise UserNotFoundError(f"존재하지 않는 사용자입니다: {user_id}")

    ingredient_rows = find_ingredients_by_category_id(str(category_id))
    if not ingredient_rows:
        raise CategoryNotFoundError(f"존재하지 않거나 재료가 없는 카테고리입니다: {category_id}")

    allergen_rows = find_user_allergens(str(user_id))

    ingredients = [_to_ingredient(row) for row in ingredient_rows]
    allergens = [
        Allergen(id=a["id"], allergen_name=a["allergen_name"], category=a["category"])
        for a in allergen_rows
    ]
    return ingredients, allergens


def _to_ingredient(row: dict) -> Ingredient:
    return Ingredient(
        id=row["id"],
        name=row["name"],
        description=row.get("description"),
        allergen=_to_allergen(row.get("allergen_master")),
    )


def _to_allergen(row: dict | None) -> Allergen | None:
    if not row:
        return None
    return Allergen(id=row["id"], allergen_name=row["allergen_name"], category=row["category"])

from uuid import UUID

from pydantic import BaseModel


class User(BaseModel):
    id: UUID
    username: str
    name: str


class Allergen(BaseModel):
    id: UUID
    allergen_name: str
    category: str


class Ingredient(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    allergen: Allergen | None = None


class IngredientCategory(BaseModel):
    id: UUID
    name: str


class RecipeCandidate(BaseModel):
    id: str
    name: str
    cooking_time: int | None = None
    missing_ingredients: list[str] = []
    matched_ingredients: list[str] = []
    match_score: float = 0.0


class SubstituteCandidate(BaseModel):
    ingredient_name: str
    substitute_name: str
    note: str | None = None
    allergy_conflict: bool = False


class RecipeDetail(BaseModel):
    id: str
    name: str
    cooking_time: int | None = None
    difficulty: str | None = None
    category: str | None = None
    cooking_method: str | None = None

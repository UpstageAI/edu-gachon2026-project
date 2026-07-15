from uuid import UUID

from pydantic import BaseModel


class IngredientRef(BaseModel):
    name: str
    category: str | None = None


class RecipeSummary(BaseModel):
    id: str
    name: str
    cooking_time: int | None = None
    missing_ingredients: list[IngredientRef] = []


class SubstituteSummary(BaseModel):
    ingredient_name: str
    substitute_name: str
    note: str | None = None
    allergy_conflict: bool = False


class ClassificationSummary(BaseModel):
    required: list[str] = []
    optional: list[str] = []
    reason: str | None = None


class RecipeDetailResponse(BaseModel):
    recipe_id: str
    name: str
    cooking_time: int | None = None
    difficulty: str | None = None
    category: str | None = None
    cooking_method: str | None = None
    owned_ingredients: list[IngredientRef] = []
    missing_ingredients: list[IngredientRef] = []
    classification: ClassificationSummary | None = None
    substitutes: list[SubstituteSummary] = []
    cooking_steps: list[str] = []


class RecommendResponse(BaseModel):
    recipes: list[RecipeSummary] = []
    detail: RecipeDetailResponse | None = None
    message: str


class SignupResponse(BaseModel):
    id: UUID
    username: str
    name: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: SignupResponse


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AllergenResponse(BaseModel):
    id: UUID
    allergen_name: str
    category: str


class UserAllergensResponse(BaseModel):
    allergens: list[AllergenResponse]


class IngredientResponse(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    allergen: AllergenResponse | None = None


class IngredientCategoryResponse(BaseModel):
    id: UUID
    name: str


class ConfirmIngredientSelectionResponse(BaseModel):
    ingredients: list[IngredientResponse]
    allergens: list[AllergenResponse]


class MyInfoResponse(BaseModel):
    id: UUID
    username: str
    name: str
    allergens: list[AllergenResponse]


class VoiceQueryResponse(BaseModel):
    answer: str

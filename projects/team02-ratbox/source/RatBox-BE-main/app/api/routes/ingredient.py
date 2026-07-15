from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id
from app.api.schemas.request import ConfirmIngredientSelectionRequest
from app.api.schemas.response import (
    AllergenResponse,
    ConfirmIngredientSelectionResponse,
    IngredientCategoryResponse,
    IngredientResponse,
)
from app.domain.models import Allergen, Ingredient, IngredientCategory
from app.services.ingredient_service import (
    CategoryNotFoundError,
    UserNotFoundError,
    confirm_ingredient_selection,
    list_categories,
)

router = APIRouter(prefix="/ingredients", tags=["ingredients"])


def _to_ingredient_response(ingredient: Ingredient) -> IngredientResponse:
    return IngredientResponse(
        id=ingredient.id,
        name=ingredient.name,
        description=ingredient.description,
        allergen=_to_allergen_response(ingredient.allergen),
    )


def _to_category_response(category: IngredientCategory) -> IngredientCategoryResponse:
    return IngredientCategoryResponse(id=category.id, name=category.name)


def _to_allergen_response(allergen: Allergen | None) -> AllergenResponse | None:
    if not allergen:
        return None
    return AllergenResponse(
        id=allergen.id, allergen_name=allergen.allergen_name, category=allergen.category
    )


@router.get("", response_model=list[IngredientCategoryResponse])
async def get_ingredients() -> list[IngredientCategoryResponse]:
    return [_to_category_response(c) for c in list_categories()]


@router.post("/selection", response_model=ConfirmIngredientSelectionResponse)
async def confirm_ingredient_selection_route(
    payload: ConfirmIngredientSelectionRequest,
    user_id: UUID = Depends(get_current_user_id),
) -> ConfirmIngredientSelectionResponse:
    try:
        ingredients, allergens = confirm_ingredient_selection(
            user_id=user_id, category_id=payload.category_id
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except CategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ConfirmIngredientSelectionResponse(
        ingredients=[_to_ingredient_response(i) for i in ingredients],
        allergens=[_to_allergen_response(a) for a in allergens],
    )

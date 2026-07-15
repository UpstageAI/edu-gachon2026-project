from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.api.schemas.request import RegisterAllergensRequest
from app.api.schemas.response import AllergenResponse, UserAllergensResponse
from app.services.user_allergen_service import (
    InvalidAllergenError,
    UserNotFoundError,
    register_user_allergens,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.post("/{user_id}/allergens", response_model=UserAllergensResponse)
async def register_allergens_route(
    user_id: UUID, payload: RegisterAllergensRequest
) -> UserAllergensResponse:
    try:
        allergens = register_user_allergens(user_id=user_id, allergen_ids=payload.allergen_ids)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidAllergenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return UserAllergensResponse(
        allergens=[
            AllergenResponse(id=a.id, allergen_name=a.allergen_name, category=a.category)
            for a in allergens
        ]
    )

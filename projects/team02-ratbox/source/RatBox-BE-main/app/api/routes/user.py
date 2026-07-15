from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user_id
from app.api.schemas.request import RegisterAllergensRequest, UpdateMyInfoRequest
from app.api.schemas.response import AllergenResponse, MyInfoResponse
from app.services.user_allergen_service import InvalidAllergenError, replace_user_allergens
from app.services.user_service import (
    UsernameTakenError,
    UserNotFoundError,
    get_my_info,
    update_my_info,
)

router = APIRouter(prefix="/users/me", tags=["users"])


def _to_response(user, allergens) -> MyInfoResponse:
    return MyInfoResponse(
        id=user.id,
        username=user.username,
        name=user.name,
        allergens=[
            AllergenResponse(id=a.id, allergen_name=a.allergen_name, category=a.category)
            for a in allergens
        ],
    )


@router.get("", response_model=MyInfoResponse)
async def get_my_info_route(user_id: UUID = Depends(get_current_user_id)) -> MyInfoResponse:
    try:
        user, allergens = get_my_info(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _to_response(user, allergens)


@router.patch("", response_model=MyInfoResponse)
async def update_my_info_route(
    payload: UpdateMyInfoRequest, user_id: UUID = Depends(get_current_user_id)
) -> MyInfoResponse:
    try:
        user = update_my_info(user_id, username=payload.username, name=payload.name)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UsernameTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    _, allergens = get_my_info(user_id)
    return _to_response(user, allergens)


@router.put("/allergens", response_model=MyInfoResponse)
async def update_my_allergens_route(
    payload: RegisterAllergensRequest, user_id: UUID = Depends(get_current_user_id)
) -> MyInfoResponse:
    try:
        allergens = replace_user_allergens(user_id, allergen_ids=payload.allergen_ids)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except InvalidAllergenError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    user, _ = get_my_info(user_id)
    return _to_response(user, allergens)

from fastapi import APIRouter

from app.api.schemas.response import AllergenResponse
from app.services.allergen_service import list_allergens

router = APIRouter(prefix="/allergens", tags=["allergens"])


@router.get("", response_model=list[AllergenResponse])
async def get_allergens() -> list[AllergenResponse]:
    return [
        AllergenResponse(id=a.id, allergen_name=a.allergen_name, category=a.category)
        for a in list_allergens()
    ]

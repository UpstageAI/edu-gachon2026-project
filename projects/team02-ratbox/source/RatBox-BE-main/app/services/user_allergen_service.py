from uuid import UUID

from app.data.repositories.allergen_repository import find_allergens_by_ids
from app.data.repositories.user_allergen_repository import (
    create_user_allergens,
    delete_user_allergens,
)
from app.data.repositories.user_repository import find_user_by_id
from app.domain.models import Allergen


class UserNotFoundError(Exception):
    pass


class InvalidAllergenError(Exception):
    pass


def register_user_allergens(user_id: UUID, allergen_ids: list[UUID]) -> list[Allergen]:
    if not find_user_by_id(str(user_id)):
        raise UserNotFoundError(f"존재하지 않는 사용자입니다: {user_id}")

    if not allergen_ids:
        return []

    allergen_rows = find_allergens_by_ids([str(allergen_id) for allergen_id in allergen_ids])
    if len(allergen_rows) != len(set(allergen_ids)):
        raise InvalidAllergenError("존재하지 않는 알레르기가 포함되어 있습니다.")

    create_user_allergens(user_id=str(user_id), allergen_ids=[a["id"] for a in allergen_rows])

    return [
        Allergen(id=a["id"], allergen_name=a["allergen_name"], category=a["category"])
        for a in allergen_rows
    ]


def replace_user_allergens(user_id: UUID, allergen_ids: list[UUID]) -> list[Allergen]:
    if not find_user_by_id(str(user_id)):
        raise UserNotFoundError(f"존재하지 않는 사용자입니다: {user_id}")

    allergen_rows = []
    if allergen_ids:
        allergen_rows = find_allergens_by_ids([str(allergen_id) for allergen_id in allergen_ids])
        if len(allergen_rows) != len(set(allergen_ids)):
            raise InvalidAllergenError("존재하지 않는 알레르기가 포함되어 있습니다.")

    delete_user_allergens(str(user_id))
    if allergen_rows:
        create_user_allergens(user_id=str(user_id), allergen_ids=[a["id"] for a in allergen_rows])

    return [
        Allergen(id=a["id"], allergen_name=a["allergen_name"], category=a["category"])
        for a in allergen_rows
    ]

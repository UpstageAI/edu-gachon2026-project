from uuid import UUID

from app.data.repositories.user_allergen_repository import find_user_allergens
from app.data.repositories.user_repository import (
    find_user_by_id,
    find_user_by_username,
    update_user,
)
from app.domain.models import Allergen, User


class UserNotFoundError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


def get_my_info(user_id: UUID) -> tuple[User, list[Allergen]]:
    row = find_user_by_id(str(user_id))
    if not row:
        raise UserNotFoundError(f"존재하지 않는 사용자입니다: {user_id}")

    allergen_rows = find_user_allergens(str(user_id))
    user = User(id=row["id"], username=row["username"], name=row["name"])
    allergens = [
        Allergen(id=a["id"], allergen_name=a["allergen_name"], category=a["category"])
        for a in allergen_rows
    ]
    return user, allergens


def update_my_info(user_id: UUID, username: str | None, name: str | None) -> User:
    if not find_user_by_id(str(user_id)):
        raise UserNotFoundError(f"존재하지 않는 사용자입니다: {user_id}")

    if username:
        existing = find_user_by_username(username)
        if existing and existing["id"] != str(user_id):
            raise UsernameTakenError(f"이미 사용 중인 아이디입니다: {username}")

    row = update_user(user_id=str(user_id), username=username, name=name)
    return User(id=row["id"], username=row["username"], name=row["name"])

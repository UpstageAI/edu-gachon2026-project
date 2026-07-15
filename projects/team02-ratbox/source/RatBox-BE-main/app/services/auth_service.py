from app.core.config import settings
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    verify_password,
)
from app.data.repositories.refresh_token_repository import (
    delete_refresh_token,
    find_user_id_by_refresh_token,
    store_refresh_token,
)
from app.data.repositories.user_repository import create_user, find_user_by_username
from app.domain.models import User


class UsernameTakenError(Exception):
    pass


class InvalidCredentialsError(Exception):
    pass


class InvalidRefreshTokenError(Exception):
    pass


def signup(username: str, password: str, name: str) -> User:
    if find_user_by_username(username):
        raise UsernameTakenError(f"이미 사용 중인 아이디입니다: {username}")

    row = create_user(username=username, password_hash=hash_password(password), name=name)
    return User(id=row["id"], username=row["username"], name=row["name"])


def login(username: str, password: str) -> tuple[User, str, str]:
    row = find_user_by_username(username)
    if not row or not verify_password(password, row["password"]):
        raise InvalidCredentialsError("아이디 또는 비밀번호가 올바르지 않습니다.")

    user = User(id=row["id"], username=row["username"], name=row["name"])

    access_token = create_access_token(user_id=str(user.id))
    refresh_token = generate_refresh_token()
    store_refresh_token(
        token=refresh_token,
        user_id=str(user.id),
        expire_seconds=settings.refresh_token_expire_days * 24 * 60 * 60,
    )

    return user, access_token, refresh_token


def refresh_access_token(refresh_token: str) -> str:
    user_id = find_user_id_by_refresh_token(refresh_token)
    if not user_id:
        raise InvalidRefreshTokenError("유효하지 않거나 만료된 refresh token입니다.")

    return create_access_token(user_id=user_id)


def logout(refresh_token: str | None) -> None:
    if refresh_token:
        delete_refresh_token(refresh_token)

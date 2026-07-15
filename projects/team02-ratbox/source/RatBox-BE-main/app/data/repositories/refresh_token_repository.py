from app.data.redis_client import get_redis

_KEY_PREFIX = "refresh_token:"


def store_refresh_token(token: str, user_id: str, expire_seconds: int) -> None:
    get_redis().set(f"{_KEY_PREFIX}{token}", user_id, ex=expire_seconds)


def find_user_id_by_refresh_token(token: str) -> str | None:
    return get_redis().get(f"{_KEY_PREFIX}{token}")


def delete_refresh_token(token: str) -> None:
    get_redis().delete(f"{_KEY_PREFIX}{token}")

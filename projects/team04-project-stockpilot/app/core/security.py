"""인증 유틸 — 비밀번호 해싱(bcrypt)과 JWT 토큰."""
from __future__ import annotations

import datetime as dt

import bcrypt
import jwt

from app.core.config import settings

_ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    """평문 비밀번호를 bcrypt 해시로 변환한다. (평문은 절대 저장하지 않음)"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """평문 비밀번호가 저장된 해시와 일치하는지 검증한다."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(user_id: int, username: str) -> str:
    """user_id·username을 담은 서명된 JWT를 발급한다."""
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "username": username,
        "iat": now,
        "exp": now + dt.timedelta(minutes=settings.jwt_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """JWT를 검증·디코드한다. 실패 시 예외를 던진다."""
    return jwt.decode(token, settings.jwt_secret, algorithms=[_ALGORITHM])

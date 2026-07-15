"""API 공용 의존성 — JWT 기반 현재 사용자 추출."""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    """Authorization: Bearer <token>에서 사용자 정보를 꺼낸다."""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "로그인이 필요해요.")
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "세션이 만료되었거나 유효하지 않아요."
        )
    return {"user_id": int(payload["sub"]), "username": payload.get("username")}

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.api.schemas.request import LoginRequest, SignupRequest
from app.api.schemas.response import LoginResponse, RefreshResponse, SignupResponse
from app.core.config import settings
from app.services.auth_service import (
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    UsernameTakenError,
    login,
    logout,
    refresh_access_token,
    signup,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_TOKEN_COOKIE = "refresh_token"


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup_route(payload: SignupRequest) -> SignupResponse:
    try:
        user = signup(username=payload.username, password=payload.password, name=payload.name)
    except UsernameTakenError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return SignupResponse(id=user.id, username=user.username, name=user.name)


@router.post("/login", response_model=LoginResponse)
async def login_route(payload: LoginRequest, response: Response) -> LoginResponse:
    try:
        user, access_token, refresh_token = login(
            username=payload.username, password=payload.password
        )
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="none",
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        path="/auth",
    )
    return LoginResponse(
        access_token=access_token,
        user=SignupResponse(id=user.id, username=user.username, name=user.name),
    )


@router.post("/refresh", response_model=RefreshResponse)
async def refresh_route(
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
) -> RefreshResponse:
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="refresh token이 없습니다."
        )

    try:
        access_token = refresh_access_token(refresh_token)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return RefreshResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout_route(
    response: Response,
    refresh_token: str | None = Cookie(default=None, alias=REFRESH_TOKEN_COOKIE),
) -> None:
    logout(refresh_token)
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE,
        path="/auth",
        secure=settings.cookie_secure,
        samesite="none",
    )

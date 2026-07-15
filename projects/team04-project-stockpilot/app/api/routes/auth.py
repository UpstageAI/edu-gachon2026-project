"""인증 라우트 — 회원가입·로그인."""
from fastapi import APIRouter, HTTPException, status

from app.core.security import create_access_token, hash_password, verify_password
from app.repositories import users as users_repo
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter()


@router.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    """아이디·비밀번호로 가입한다. 비밀번호는 bcrypt로 해싱해 저장한다."""
    if await users_repo.get_user_by_username(req.username):
        raise HTTPException(status.HTTP_409_CONFLICT, "이미 사용 중인 아이디예요.")
    user = await users_repo.create_user(req.username, hash_password(req.password))
    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token, username=user["username"])


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """아이디·비밀번호를 검증하고 JWT를 발급한다."""
    user = await users_repo.get_user_by_username(req.username)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "아이디 또는 비밀번호가 올바르지 않아요."
        )
    token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=token, username=user["username"])

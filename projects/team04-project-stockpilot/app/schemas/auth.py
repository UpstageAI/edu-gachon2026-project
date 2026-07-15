"""인증·즐겨찾기 요청/응답 스키마."""
from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class WatchlistAddRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=100)


class WatchlistItem(BaseModel):
    ticker: str
    name: str | None = None

from __future__ import annotations

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def _canonical_session_id(value: str) -> str:
    """Require a high-entropy UUID bearer identifier for anonymous sessions."""

    try:
        parsed = UUID(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("session_id must be a UUID") from exc
    if parsed.version != 4:
        raise ValueError("session_id must be a random UUIDv4")
    return str(parsed)


class UserProfile(BaseModel):
    age: int | None = None
    employment_status: Literal["unemployed_seeking_job", "employed", "student", "not_specified"] | None = None
    graduation_status: Literal["enrolled", "expected_graduate", "graduated_within_2y", "graduated_over_2y"] | None = (
        None
    )
    region: str | None = None
    interest_fields: list[str] = Field(default_factory=list)
    policy_topic: str | None = None


class UserProfileDefaults(BaseModel):
    """새 채팅에서도 재사용할 수 있는 최소 비민감 사용자 조건."""

    age: int | None = Field(default=None, ge=0, le=120)
    region: str | None = Field(default=None, max_length=100)


class ChatRequest(BaseModel):
    session_id: str = Field(
        default_factory=lambda: str(uuid4()),
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    )
    message: str = Field(min_length=1, max_length=4000)
    profile_defaults: UserProfileDefaults | None = None

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_session_id(value)


class ChatTurnResponse(BaseModel):
    session_id: str
    intent: str
    reply: str
    profile: UserProfile
    missing_slots: list[str] = Field(default_factory=list)
    recommendations: list[dict] = Field(default_factory=list)
    trace_id: str | None = None


class RecommendationFeedbackRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    message_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    trace_id: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    rating: Literal["up", "down"]

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str) -> str:
        return _canonical_session_id(value)

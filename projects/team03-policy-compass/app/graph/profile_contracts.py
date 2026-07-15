"""Validated profile state and explicit profile-update semantics.

LLM extraction output is untrusted input.  Invalid fields are ignored one by
one so a single malformed value cannot discard a previously confirmed profile,
and values are removed only when the user explicitly asks to clear them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Set
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator

EmploymentStatus = Literal["unemployed_seeking_job", "employed", "student", "not_specified"]
PolicyTopic = Literal["일자리", "주거", "교육·직업·훈련", "금융·복지·문화", "참여·기반"]
RequestKind = Literal["youth_policy", "training", "recruitment", "general"]
ProfileText = Annotated[StrictStr, Field(min_length=1, max_length=100)]


class ProfileState(BaseModel):
    """Allowlisted durable profile fields used by routing and search."""

    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    age: StrictInt | None = Field(default=None, ge=0, le=120)
    employment_status: EmploymentStatus | None = None
    region: ProfileText | None = None
    interest_fields: list[ProfileText] | None = Field(default=None, max_length=10)
    desired_job: ProfileText | None = None
    preferred_support_type: ProfileText | None = None
    policy_topic: PolicyTopic | None = None
    request_kind: RequestKind | None = None

    @field_validator("interest_fields")
    @classmethod
    def normalize_interest_fields(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        normalized = list(dict.fromkeys(item.strip() for item in value if item.strip()))
        return normalized or None


PROFILE_FIELDS = frozenset(ProfileState.model_fields)

_CLEAR_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "age": (
        re.compile(r"(?:만\s*)?나이.{0,12}(?:저장|기억).{0,5}(?:하지|말아|마)"),
        re.compile(r"(?:만\s*)?나이.{0,12}(?:지워|삭제|초기화|빼\s*줘|빼줘)"),
    ),
    "region": (
        re.compile(r"(?:거주\s*지역|지역|거주지|사는\s*곳).{0,12}(?:저장|기억).{0,5}(?:하지|말아|마)"),
        re.compile(r"(?:거주\s*지역|지역|거주지|사는\s*곳).{0,12}(?:지워|삭제|초기화|빼\s*줘|빼줘)"),
    ),
    "employment_status": (re.compile(r"(?:취업|재직|구직)\s*상태.{0,12}(?:지워|삭제|초기화|저장하지|기억하지)"),),
    "interest_fields": (re.compile(r"(?:관심\s*분야|관심사).{0,12}(?:지워|삭제|초기화|저장하지|기억하지)"),),
    "desired_job": (re.compile(r"(?:희망\s*직무|원하는\s*직무).{0,12}(?:지워|삭제|초기화|저장하지|기억하지)"),),
    "preferred_support_type": (
        re.compile(r"(?:지원\s*형태|지원\s*유형).{0,12}(?:지워|삭제|초기화|저장하지|기억하지)"),
    ),
    "policy_topic": (re.compile(r"(?:정책\s*분야|정책\s*주제).{0,12}(?:지워|삭제|초기화|저장하지|기억하지)"),),
}
_CLEAR_ALL = re.compile(
    r"(?:내\s*)?(?:프로필|저장된\s*정보|기억한\s*정보|개인\s*정보).{0,12}(?:전부|모두)?.{0,5}(?:지워|삭제|초기화)"
)


def sanitize_profile(raw_profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return valid allowlisted fields while dropping malformed values locally."""

    if not isinstance(raw_profile, Mapping):
        return {}

    sanitized: dict[str, Any] = {}
    for field_name in PROFILE_FIELDS:
        if field_name not in raw_profile:
            continue
        try:
            validated = ProfileState.model_validate({field_name: raw_profile[field_name]}).model_dump(
                exclude_none=True,
                exclude_unset=True,
            )
        except (TypeError, ValueError):
            continue
        value = validated.get(field_name)
        if value not in (None, "", []):
            sanitized[field_name] = value
    return sanitized


def requested_profile_clears(user_input: str) -> set[str]:
    """Identify fields the user explicitly asked the service to forget."""

    normalized = " ".join((user_input or "").split())
    if not normalized:
        return set()
    if _CLEAR_ALL.search(normalized):
        return set(PROFILE_FIELDS - {"request_kind"})
    return {
        field_name
        for field_name, patterns in _CLEAR_PATTERNS.items()
        if any(pattern.search(normalized) for pattern in patterns)
    }


def apply_profile_delta(
    previous_profile: Mapping[str, Any] | None,
    extracted_fields: Mapping[str, Any] | None,
    clears: Set[str] | None = None,
) -> dict[str, Any]:
    """Apply validated SET operations and explicit CLEAR operations.

    Empty or malformed extracted values mean UNCHANGED.  CLEAR wins over a
    conflicting extraction from the same turn because the user's deletion
    request is the safer and more explicit instruction.
    """

    merged = sanitize_profile(previous_profile)
    clear_fields = set(clears or ()).intersection(PROFILE_FIELDS)
    for field_name in clear_fields:
        merged.pop(field_name, None)

    for field_name, value in sanitize_profile(extracted_fields).items():
        if field_name not in clear_fields:
            merged[field_name] = value
    return merged

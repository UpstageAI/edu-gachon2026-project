from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ToolText = Annotated[str, Field(min_length=1, max_length=100)]


class StrictToolInput(BaseModel):
    """Reject unknown filters so callers cannot assume an ignored field applied."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class YouthPolicySearchInput(StrictToolInput):
    """온통청년 청년정책 검색 Tool 입력 계약."""

    region: ToolText | None = None
    age: int | None = Field(default=None, ge=0, le=120)
    employment_status: Literal["unemployed_seeking_job", "employed", "student", "not_specified"] | None = None
    support_types: list[ToolText] = Field(default_factory=list, max_length=10)
    interest_fields: list[ToolText] = Field(default_factory=list, max_length=10)
    keywords: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=10, ge=1, le=100)


class YouthPolicyItem(BaseModel):
    """온통청년 또는 내부 fallback 청년정책 표준 출력."""

    source: str = "youthcenter"
    policy_id: str
    title: str
    organization: str | None = None
    region: str | None = None
    min_age: int | None = None
    max_age: int | None = None
    age_restricted: bool | None = None
    target_summary: str | None = None
    support_summary: str | None = None
    business_period: str | None = None
    business_end_date: str | None = None
    application_period: str | None = None
    application_method: str | None = None
    detail_url: str | None = None
    fallback_reason: str | None = None
    match_scope: Literal["exact", "nationwide", "nearby", "unknown"] = "unknown"
    distance_km: float | None = None
    raw: dict = Field(default_factory=dict)


class TrainingCourseSearchInput(StrictToolInput):
    """고용24 국민내일배움카드 훈련과정 검색 Tool 입력 계약."""

    desired_job: ToolText | None = None
    training_region: ToolText | None = None
    training_region_code: str | None = Field(default=None, max_length=10, pattern=r"^[0-9]+$")
    training_start_date_from: str | None = Field(default=None, max_length=20)
    training_start_date_to: str | None = Field(default=None, max_length=20)
    keywords: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=10, ge=1, le=100)


class TrainingCourseItem(BaseModel):
    """고용24 훈련과정 표준 출력."""

    source: str = "work24_training"
    course_id: str
    course_round: str | None = None
    title: str
    institution: str | None = None
    region: str | None = None
    address: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    cost: str | None = None
    actual_cost: str | None = None
    ncs_code: str | None = None
    target: str | None = None
    capacity: str | None = None
    contact: str | None = None
    detail_url: str | None = None
    institution_url: str | None = None
    fallback_reason: str | None = None
    raw: dict = Field(default_factory=dict)


class RecruitmentInfoSearchInput(StrictToolInput):
    """고용24 채용 보조 정보 검색 Tool 입력 계약."""

    desired_job: ToolText | None = None
    preferred_work_region: ToolText | None = None
    career_level: Literal["신입", "인턴"] | None = None
    keywords: str = Field(default="", max_length=200)
    page: int = Field(default=1, ge=1, le=1000)
    page_size: int = Field(default=10, ge=1, le=100)


class RecruitmentInfoItem(BaseModel):
    """고용24 채용행사/공채속보 또는 탐색 가이드 표준 출력."""

    source: str = "work24_recruitment"
    item_id: str
    item_type: str  # event | open_recruitment | guide
    title: str
    company: str | None = None
    region: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    summary: str | None = None
    detail_url: str | None = None
    fallback_reason: str | None = None
    raw: dict = Field(default_factory=dict)

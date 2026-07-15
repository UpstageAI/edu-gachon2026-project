from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Intent(StrEnum):
    RECOMMEND = "RECOMMEND"
    EXPLAIN = "EXPLAIN"
    ELIGIBILITY_CHECK = "ELIGIBILITY_CHECK"
    GENERAL = "GENERAL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class Action(StrEnum):
    RESPOND = "RESPOND"
    SEARCH = "SEARCH"


class ResponseMode(StrEnum):
    GENERAL = "general"
    EXPLAIN = "explain"
    RECOMMEND = "recommend"
    ELIGIBILITY = "eligibility"
    OUT_OF_SCOPE = "out_of_scope"


class RequestKind(StrEnum):
    YOUTH_POLICY = "youth_policy"
    TRAINING = "training"
    RECRUITMENT = "recruitment"
    GENERAL = "general"


class RoutingDecision(BaseModel):
    """Validated contract returned by the LLM router."""

    model_config = ConfigDict(extra="ignore")

    action: Action
    response_mode: ResponseMode
    request_kind: RequestKind
    search_query: str | None = None
    resume_pending: bool = False

    @property
    def intent(self) -> Intent:
        return {
            ResponseMode.GENERAL: Intent.GENERAL,
            ResponseMode.EXPLAIN: Intent.EXPLAIN,
            ResponseMode.RECOMMEND: Intent.RECOMMEND,
            ResponseMode.ELIGIBILITY: Intent.ELIGIBILITY_CHECK,
            ResponseMode.OUT_OF_SCOPE: Intent.OUT_OF_SCOPE,
        }[self.response_mode]

    @field_validator("search_query")
    @classmethod
    def normalize_search_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split()).strip()
        return normalized[:100] or None

    @model_validator(mode="after")
    def validate_tool_consistency(self) -> RoutingDecision:
        if self.action is Action.RESPOND:
            if self.response_mode not in {
                ResponseMode.GENERAL,
                ResponseMode.EXPLAIN,
                ResponseMode.OUT_OF_SCOPE,
            }:
                raise ValueError("RESPOND 행동은 일반 대화, 설명 또는 범위 밖 응답만 허용합니다.")
            self.request_kind = RequestKind.GENERAL
            self.search_query = None
        elif self.request_kind is RequestKind.GENERAL:
            raise ValueError("SEARCH 행동에는 외부 데이터 도구가 필요합니다.")
        elif self.response_mode not in {
            ResponseMode.EXPLAIN,
            ResponseMode.RECOMMEND,
            ResponseMode.ELIGIBILITY,
        }:
            raise ValueError("SEARCH 행동의 응답 모드가 올바르지 않습니다.")
        return self


VALID_REQUEST_KINDS = {item.value for item in RequestKind}

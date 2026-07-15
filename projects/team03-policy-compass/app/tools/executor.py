from __future__ import annotations

import logging

from pydantic import BaseModel

from app.graph.search_contracts import (
    SearchOutcome,
    SearchSource,
    outcome_from_raw,
    unavailable_outcome,
)
from app.repositories.work24_recruitment import Work24RecruitmentRepository
from app.repositories.work24_training import Work24TrainingRepository
from app.repositories.youthcenter import YouthCenterRepository
from app.tools.schemas import (
    RecruitmentInfoItem,
    RecruitmentInfoSearchInput,
    TrainingCourseItem,
    TrainingCourseSearchInput,
    YouthPolicyItem,
    YouthPolicySearchInput,
)

logger = logging.getLogger(__name__)


def _requested_filters(payload: BaseModel) -> dict:
    """Return only meaningful user-supplied search conditions.

    Pagination controls are transport details rather than evidence filters, and
    empty/default values should not look like conditions the user requested.
    """

    values = payload.model_dump(exclude_none=True, exclude={"page", "page_size"})
    return {key: value for key, value in values.items() if value not in ("", [], {}, ())}


class YouthPolicySearchTool:
    """온통청년 청년정책 또는 내부 fallback 정책을 검색한다."""

    name = "youth_policy_search"
    description = "일자리·주거·교육·금융·복지·문화·참여 분야의 청년정책을 온통청년에서 검색한다."

    def __init__(self, repository: YouthCenterRepository) -> None:
        self._repository = repository

    async def execute(self, payload: YouthPolicySearchInput) -> list[YouthPolicyItem]:
        try:
            return await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("청년정책 검색 Tool 실행 중 오류가 발생하여 빈 결과를 반환합니다.")
            return []

    async def execute_outcome(self, payload: YouthPolicySearchInput) -> SearchOutcome:
        requested_filters = _requested_filters(payload)
        try:
            values = await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("청년정책 검색 Tool 실행 중 오류가 발생했습니다.")
            return unavailable_outcome(
                SearchSource.YOUTH_POLICY,
                "온통청년 청년정책 검색 도구가 일시적으로 응답하지 않아요.",
                requested_filters=requested_filters,
            )
        return outcome_from_raw(
            SearchSource.YOUTH_POLICY,
            values,
            requested_filters=requested_filters,
        )


class TrainingCourseSearchTool:
    """고용24 국민내일배움카드 훈련과정 검색 Tool."""

    name = "training_course_search"
    description = "관심 직무와 훈련지역을 기준으로 고용24 훈련과정을 검색한다."

    def __init__(self, repository: Work24TrainingRepository) -> None:
        self._repository = repository

    async def execute(self, payload: TrainingCourseSearchInput) -> list[TrainingCourseItem]:
        try:
            return await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("훈련과정 검색 Tool 실행 중 오류가 발생하여 빈 결과를 반환합니다.")
            return []

    async def execute_outcome(self, payload: TrainingCourseSearchInput) -> SearchOutcome:
        requested_filters = _requested_filters(payload)
        try:
            values = await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("훈련과정 검색 Tool 실행 중 오류가 발생했습니다.")
            return unavailable_outcome(
                SearchSource.TRAINING,
                "고용24 훈련과정 검색 도구가 일시적으로 응답하지 않아요.",
                requested_filters=requested_filters,
            )
        return outcome_from_raw(
            SearchSource.TRAINING,
            values,
            requested_filters=requested_filters,
        )


class RecruitmentInfoTool:
    """고용24 채용 보조 정보 검색 Tool.

    채용정보목록/상세 권한 제한은 안내형 결과로 변환한다.
    """

    name = "recruitment_info"
    description = "고용24 채용행사/공채속보 또는 채용 탐색 가이드를 제공한다."

    def __init__(self, repository: Work24RecruitmentRepository) -> None:
        self._repository = repository

    async def execute(self, payload: RecruitmentInfoSearchInput) -> list[RecruitmentInfoItem]:
        try:
            return await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("채용정보 Tool 실행 중 오류가 발생하여 안내 fallback을 반환합니다.")
            return []

    async def execute_outcome(self, payload: RecruitmentInfoSearchInput) -> SearchOutcome:
        requested_filters = _requested_filters(payload)
        try:
            values = await self._repository.search(payload)
        except Exception:  # noqa: BLE001
            logger.exception("채용정보 Tool 실행 중 오류가 발생했습니다.")
            return unavailable_outcome(
                SearchSource.RECRUITMENT,
                "고용24 채용 보조정보 검색 도구가 일시적으로 응답하지 않아요.",
                requested_filters=requested_filters,
            )
        return outcome_from_raw(
            SearchSource.RECRUITMENT,
            values,
            requested_filters=requested_filters,
        )

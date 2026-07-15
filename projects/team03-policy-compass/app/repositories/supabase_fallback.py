"""라이브 Open API가 실패하거나(요청 한도 초과, 장애) 키가 미설정일 때
data/scripts/ingest_*.py로 채워둔 Supabase 캐시 테이블에서 대신 검색하는
fallback 계층.

평소에는 전혀 쓰이지 않는다 — 각 repository(YouthCenterRepository,
Work24TrainingRepository, Work24RecruitmentRepository)의 search()가 실제
API 호출에 실패했을 때만 호출된다. 캐시 데이터가 최신이 아닐 수 있다는
전제를 사용자에게 안내하는 건 호출하는 쪽(각 repository)의 책임이다.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.http import log_external_api_error
from app.tools.schemas import (
    RecruitmentInfoItem,
    RecruitmentInfoSearchInput,
    TrainingCourseItem,
    TrainingCourseSearchInput,
    YouthPolicyItem,
    YouthPolicySearchInput,
)

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT_SECONDS = 5


class _SupabaseTableFallback:
    """공통 Supabase REST 조회 로직 (테이블별 서브클래스가 필터/매핑만 담당)."""

    def __init__(self, table: str) -> None:
        settings = get_settings()
        self._base_url = (settings.supabase_url or "").rstrip("/")
        self._key = settings.supabase_key or ""
        self._table = table

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._key)

    async def _select(self, params: dict[str, str]) -> list[dict[str, Any]]:
        if not self.is_configured:
            logger.warning("[캐시 폴백] Supabase %s 미설정(URL/KEY 없음)으로 조회 건너뜀", self._table)
            return []

        headers = {"apikey": self._key, "Authorization": f"Bearer {self._key}"}
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS, headers=headers) as client:
                response = await client.get(f"{self._base_url}/rest/v1/{self._table}", params=params)
                response.raise_for_status()
                return response.json()
        except Exception as exc:  # noqa: BLE001 - fallback 자체 실패가 상위 흐름을 막으면 안 됨
            log_external_api_error(logger, f"Supabase {self._table} 캐시 조회", exc)
            return []


class SupabaseYouthPolicyFallback(_SupabaseTableFallback):
    """온통청년 API 장애/미설정 시 youth_policies 캐시에서 대신 검색한다."""

    def __init__(self) -> None:
        super().__init__("youth_policies")

    async def search(self, query: YouthPolicySearchInput) -> list[YouthPolicyItem]:
        params: dict[str, str] = {
            "select": "*",
            "order": "fetched_at.desc",
            "limit": str(query.page_size),
        }
        if query.region:
            params["region"] = f"ilike.*{query.region}*"
        keyword = query.keywords or (query.support_types[0] if query.support_types else None)
        if keyword:
            params["title"] = f"ilike.*{keyword}*"

        rows = await self._select(params)
        if not rows and "region" in params:
            # 지역 조건이 너무 좁아 0건이면, 전국 캐시라도 보이도록 지역 조건을 풀어 재시도한다.
            rows = await self._select({k: v for k, v in params.items() if k != "region"})

        return [_row_to_youth_policy_item(row) for row in rows]


def _row_to_youth_policy_item(row: dict[str, Any]) -> YouthPolicyItem:
    return YouthPolicyItem(
        source=row.get("source") or "youthcenter",
        policy_id=row["policy_id"],
        title=row["title"],
        organization=row.get("organization"),
        region=row.get("region"),
        min_age=row.get("min_age"),
        max_age=row.get("max_age"),
        age_restricted=row.get("age_restricted"),
        target_summary=row.get("target_summary"),
        support_summary=row.get("support_summary"),
        business_period=row.get("business_period"),
        business_end_date=row.get("business_end_date"),
        application_period=row.get("application_period"),
        application_method=row.get("application_method"),
        detail_url=row.get("detail_url"),
        raw=row.get("raw_payload") or {},
    )


class SupabaseTrainingCourseFallback(_SupabaseTableFallback):
    """고용24 훈련과정 API 장애/미설정 시 training_courses 캐시에서 대신 검색한다."""

    def __init__(self) -> None:
        super().__init__("training_courses")

    async def search(self, query: TrainingCourseSearchInput) -> list[TrainingCourseItem]:
        params: dict[str, str] = {
            "select": "*",
            "order": "start_date.asc",
            "limit": str(query.page_size),
        }
        if query.training_region:
            params["region"] = f"ilike.*{query.training_region}*"
        keyword = query.desired_job or query.keywords
        if keyword:
            params["title"] = f"ilike.*{keyword}*"

        rows = await self._select(params)
        if not rows and "region" in params:
            rows = await self._select({k: v for k, v in params.items() if k != "region"})

        return [_row_to_training_course_item(row) for row in rows]


def _row_to_training_course_item(row: dict[str, Any]) -> TrainingCourseItem:
    return TrainingCourseItem(
        source=row.get("source") or "work24_training",
        course_id=row["course_id"],
        course_round=row.get("course_round"),
        title=row["title"],
        institution=row.get("institution"),
        region=row.get("region"),
        address=row.get("address"),
        start_date=row.get("start_date"),
        end_date=row.get("end_date"),
        cost=row.get("cost"),
        actual_cost=row.get("actual_cost"),
        ncs_code=row.get("ncs_code"),
        target=row.get("target"),
        capacity=row.get("capacity"),
        contact=row.get("contact"),
        detail_url=row.get("detail_url"),
        institution_url=row.get("institution_url"),
        raw=row.get("raw_payload") or {},
    )


class SupabaseRecruitmentInfoFallback(_SupabaseTableFallback):
    """고용24 채용 API 장애/미설정 시 recruitment_infos 캐시에서 대신 검색한다."""

    def __init__(self) -> None:
        super().__init__("recruitment_infos")

    async def search(self, query: RecruitmentInfoSearchInput) -> list[RecruitmentInfoItem]:
        params: dict[str, str] = {
            "select": "*",
            "order": "fetched_at.desc",
            "limit": str(query.page_size),
        }
        if query.preferred_work_region:
            params["region"] = f"ilike.*{query.preferred_work_region}*"
        keyword = query.desired_job or query.keywords
        if keyword:
            params["title"] = f"ilike.*{keyword}*"

        rows = await self._select(params)
        if not rows and "region" in params:
            rows = await self._select({k: v for k, v in params.items() if k != "region"})

        return [_row_to_recruitment_info_item(row) for row in rows]


def _row_to_recruitment_info_item(row: dict[str, Any]) -> RecruitmentInfoItem:
    return RecruitmentInfoItem(
        source=row.get("source") or "work24_recruitment",
        item_id=row["item_id"],
        item_type=row["item_type"],
        title=row["title"],
        company=row.get("company"),
        region=row.get("region"),
        start_date=row.get("start_date"),
        end_date=row.get("end_date"),
        summary=row.get("summary"),
        detail_url=row.get("detail_url"),
        raw=row.get("raw_payload") or {},
    )

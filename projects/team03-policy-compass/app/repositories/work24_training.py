from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote_plus

import httpx

from app.core.config import get_settings, source_http_timeout
from app.core.http import log_external_api_error
from app.core.regions import resolve_region
from app.core.xml_utils import xml_error_message
from app.tools.schemas import TrainingCourseItem, TrainingCourseSearchInput

logger = logging.getLogger(__name__)

_POST_FILTER_FETCH_MULTIPLIER = 3

WORK24_TRAINING_AREA_CODES = {
    "서울": "11",
    "전남광주": "12",
    "부산": "26",
    "대구": "27",
    "인천": "28",
    "대전": "30",
    "울산": "31",
    "세종": "36",
    "경기": "41",
    "충북": "43",
    "충남": "44",
    "전북": "45",
    "경북": "47",
    "경남": "48",
    "제주": "50",
    "강원": "51",
}
_WORK24_COMBINED_AREA_ALIASES = {"광주": "전남광주", "전남": "전남광주"}


def work24_training_area_code(region: str | None) -> str | None:
    """고용24 훈련과정 API의 srchTraArea1 코드로 사용자 지역을 변환한다."""

    if not region:
        return None
    resolved = resolve_region(region)
    if resolved is None:
        return None
    area = _WORK24_COMBINED_AREA_ALIASES.get(resolved.sido, resolved.sido)
    return WORK24_TRAINING_AREA_CODES.get(area)


def _compact_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _node_text(node: ET.Element, name: str) -> str | None:
    child = node.find(name)
    return _compact_text(child.text if child is not None else None)


def default_training_period(today: date | None = None) -> tuple[str, str]:
    base = today or date.today()
    end = base + timedelta(days=183)
    return base.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def normalize_training_courses(xml_text: str) -> list[TrainingCourseItem]:
    root = ET.fromstring(xml_text)
    if error := xml_error_message(root, record_tags={"scn_list"}):
        raise Work24TrainingResponseError(error)
    records = root.findall(".//scn_list")
    courses: list[TrainingCourseItem] = []

    for node in records:
        title = _node_text(node, "title") or "훈련과정명 확인 필요"
        course_id = _node_text(node, "trprId") or title
        item = TrainingCourseItem(
            course_id=course_id,
            course_round=_node_text(node, "trprDegr"),
            title=title,
            institution=_node_text(node, "subTitle"),
            region=_node_text(node, "address"),
            address=_node_text(node, "address"),
            start_date=_node_text(node, "traStartDate"),
            end_date=_node_text(node, "traEndDate"),
            cost=_node_text(node, "courseMan"),
            actual_cost=_node_text(node, "realMan"),
            ncs_code=_node_text(node, "ncsCd"),
            target=_node_text(node, "trainTarget"),
            capacity=_node_text(node, "yardMan"),
            contact=_node_text(node, "telNo"),
            detail_url=_node_text(node, "titleLink"),
            institution_url=_node_text(node, "subTitleLink"),
            raw={child.tag: _compact_text(child.text) for child in list(node)},
        )
        courses.append(item)

    return courses


class Work24TrainingResponseError(ValueError):
    """The API returned valid XML that explicitly represents a failure."""


def _build_work24_training_search_url(query: TrainingCourseSearchInput) -> str:
    desired_job = query.desired_job or query.keywords or ""
    # Work24 changes deep links occasionally, so keep this anchored to the public entry point
    # while carrying the keyword in a query string users can copy from the answer.
    params = quote_plus(desired_job.strip())
    return f"https://www.work24.go.kr/cm/main.do?keyword={params}" if params else "https://www.work24.go.kr/cm/main.do"


def _compact_training_keyword(value: str | None) -> str | None:
    if not value:
        return None
    keyword_rules = [
        (("데이터", "분석"), "데이터 분석"),
        (("빅데이터",), "빅데이터"),
        (("인공지능",), "인공지능"),
        (("AI",), "AI"),
        (("개발",), "개발"),
        (("프로그래밍",), "프로그래밍"),
        (("마케팅",), "마케팅"),
        (("디자인",), "디자인"),
    ]
    for needles, keyword in keyword_rules:
        if all(needle in value for needle in needles):
            return keyword
    text = re.sub(
        r"(국비지원|국민내일배움카드|훈련과정|훈련|과정|찾아줘|추천|취업|준비|중이야|쪽으로|에서)",
        " ",
        value,
    )
    text = re.sub(r"[^\w가-힣+# ]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def training_fallback_guide(reason: str, query: TrainingCourseSearchInput) -> TrainingCourseItem:
    desired_job = _compact_training_keyword(query.desired_job) or _compact_training_keyword(query.keywords)
    desired_job = desired_job or "관심 직무"
    region = query.training_region or "희망 지역"
    return TrainingCourseItem(
        course_id="work24-training-guide",
        title="고용24 훈련과정 검색 결과를 바로 찾지 못했어요",
        institution="고용24",
        region=query.training_region,
        detail_url=_build_work24_training_search_url(query),
        fallback_reason=(
            f"{reason}. 고용24 국민내일배움카드 훈련과정 화면에서 "
            f"검색어 '{desired_job}', 지역 '{region}', 훈련 시작일 6개월 범위로 다시 확인해보세요."
        ),
        raw={"search_keyword": desired_job, "search_region": region},
    )


class Work24TrainingRepository:
    """고용24 국민내일배움카드 훈련과정 API 접근 계층.

    fallback_repository는 라이브 API 키 미설정 또는 호출 자체 실패(요청 한도 초과,
    장애, 파싱 실패 등) 시에만 사용되는 Supabase 캐시 조회 계층이다
    (app.repositories.supabase_fallback.SupabaseTrainingCourseFallback와 호환되는
    search(query) -> list[TrainingCourseItem] 메서드가 있으면 된다). 라이브 호출이
    정상 응답했는데 결과가 0건인 경우는 캐시로 대체하지 않는다 — 그건 API 장애가
    아니라 실제로 조건에 맞는 과정이 없다는 뜻이라서다.
    """

    def __init__(self, fallback_repository: object | None = None) -> None:
        self._settings = get_settings()
        self._fallback_repository = fallback_repository

    async def _fallback_search(self, query: TrainingCourseSearchInput) -> list[TrainingCourseItem]:
        if self._fallback_repository is None:
            return []
        try:
            items = await self._fallback_repository.search(query)
        except Exception:  # noqa: BLE001 - 캐시 fallback 실패가 상위 흐름을 막으면 안 됨
            logger.exception("[캐시 폴백] 고용24 훈련과정 캐시 조회 실패")
            return []
        if items:
            logger.info("[캐시 폴백] 고용24 훈련과정 캐시에서 %d건 반환", len(items))
        else:
            logger.info("[캐시 폴백] 고용24 훈련과정 캐시에도 결과 없음")
        return items

    async def search(self, query: TrainingCourseSearchInput) -> list[TrainingCourseItem]:
        if not self._settings.employment24_training_api_key:
            logger.warning("[캐시 폴백] EMPLOYMENT24_TRAINING_API_KEY 미설정 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
            return [training_fallback_guide("EMPLOYMENT24_TRAINING_API_KEY 미설정", query)]

        start, end = default_training_period()
        params: dict[str, Any] = {
            "authKey": self._settings.employment24_training_api_key,
            "returnType": "XML",
            "outType": "1",
            "pageNum": str(query.page),
            # Work24 only supports a broad 시·도 filter. Fetch a bounded pool
            # before the graph applies an exact 시·군·구 evidence gate.
            "pageSize": str(min(query.page_size * _POST_FILTER_FETCH_MULTIPLIER, 100)),
            "srchTraStDt": query.training_start_date_from or start,
            "srchTraEndDt": query.training_start_date_to or end,
            "sort": "ASC",
            "sortCol": "2",
        }
        training_region_code = query.training_region_code or work24_training_area_code(query.training_region)
        if training_region_code:
            params["srchTraArea1"] = training_region_code
        search_keyword = _compact_training_keyword(query.desired_job) or _compact_training_keyword(query.keywords)
        if search_keyword:
            params["srchTraProcessNm"] = search_keyword

        try:
            async with httpx.AsyncClient(timeout=source_http_timeout(self._settings)) as client:
                response = await client.get(self._settings.employment24_training_api_url, params=params)
                response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log_external_api_error(logger, "고용24 훈련과정 API", exc)
            logger.warning("[캐시 폴백] 고용24 훈련과정 API 호출 실패 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
            return [training_fallback_guide("고용24 훈련과정 API 호출 실패", query)]

        try:
            items = normalize_training_courses(response.text)
        except (ET.ParseError, Work24TrainingResponseError):
            logger.warning("고용24 훈련과정 XML 파싱 실패", exc_info=True)
            logger.warning("[캐시 폴백] 고용24 훈련과정 응답 파싱 실패 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
            return [training_fallback_guide("고용24 훈련과정 응답 오류로 조회할 수 없음", query)]

        if items:
            return items

        fallback_query = query.model_copy(update={"desired_job": search_keyword})
        return [training_fallback_guide("고용24 훈련과정 검색 결과 없음", fallback_query)]

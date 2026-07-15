from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.config import get_settings, source_http_timeout
from app.core.http import log_external_api_error
from app.core.regions import resolve_region
from app.core.xml_utils import xml_error_message
from app.tools.schemas import RecruitmentInfoItem, RecruitmentInfoSearchInput

logger = logging.getLogger(__name__)

_POST_FILTER_FETCH_MULTIPLIER = 3

_PERSONAL_KEY_LIMIT_MESSAGE = "개인회원은 사용할 수 없는 OPEN-API"
_WORK24_HOME = "https://www.work24.go.kr/"
_EVENT_AREA_CODES = {
    "서울": "51",
    "강원": "51",
    "부산": "52",
    "울산": "52",
    "경남": "52",
    "대구": "53",
    "경북": "53",
    "경기": "54",
    "인천": "54",
    "광주": "55",
    "전남": "55",
    "전남광주": "55",
    "전북": "55",
    "제주": "55",
    "대전": "56",
    "충남": "56",
    "충북": "56",
    "세종": "56",
}


def _event_area_code(region: str | None) -> str | None:
    resolved = resolve_region(region)
    return _EVENT_AREA_CODES.get(resolved.sido) if resolved else None


def _compact_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _record_values(node: ET.Element) -> dict[str, str | None]:
    return {_local_name(child.tag): _compact_text(child.text) for child in list(node)}


def _first(values: dict[str, str | None], *keys: str) -> str | None:
    return next((values[key] for key in keys if values.get(key)), None)


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\D", "", value)
    if len(compact) == 8:
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:]}"
    return value


def _event_end_date(event_term: str | None) -> str | None:
    dates = re.findall(r"\d{4}[-./]?\d{2}[-./]?\d{2}", event_term or "")
    return _normalize_date(dates[-1]) if dates else None


def is_personal_key_limited_response(text: str) -> bool:
    return _PERSONAL_KEY_LIMIT_MESSAGE in text


def recruitment_fallback_guide(reason: str, query: RecruitmentInfoSearchInput) -> RecruitmentInfoItem:
    desired_job = query.desired_job or query.keywords or "관심 직무"
    region = query.preferred_work_region or "희망 지역"
    summary = (
        "현재 개인회원 API 권한으로 채용정보목록/상세를 직접 조회하기 어렵습니다. "
        "대신 채용행사·공채속보 API를 조회합니다. "
        f"결과가 없으면 고용24에서 '{desired_job}', '{region}', 신입/인턴/공채 조건으로 확인해보세요."
    )
    return RecruitmentInfoItem(
        item_id="work24-recruitment-guide",
        item_type="guide",
        title="고용24 채용 탐색 가이드",
        region=query.preferred_work_region,
        summary=summary,
        detail_url=_WORK24_HOME,
        fallback_reason=reason,
    )


def normalize_recruitment_items(
    xml_text: str,
    item_type: str | None = None,
) -> list[RecruitmentInfoItem]:
    if is_personal_key_limited_response(xml_text):
        return []

    root = ET.fromstring(xml_text)
    record_specs = {
        "event": {"empEvent"},
        "open_recruitment": {"dhsOpenEmpInfo", "item"},
    }
    allowed_tags = record_specs.get(item_type, set().union(*record_specs.values()))
    if error := xml_error_message(root, record_tags=allowed_tags):
        raise Work24RecruitmentResponseError(error)
    records = [node for node in root.iter() if _local_name(node.tag) in allowed_tags]
    items: list[RecruitmentInfoItem] = []

    for idx, node in enumerate(records, start=1):
        values = _record_values(node)
        resolved_type = item_type or _infer_item_type(node)
        if resolved_type == "event":
            items.append(_normalize_event(values, idx))
        else:
            items.append(_normalize_open_recruitment(values, idx))
    return items


class Work24RecruitmentResponseError(ValueError):
    """The API returned valid XML that explicitly represents a failure."""


def _infer_item_type(node: ET.Element) -> str:
    tag = _local_name(node.tag)
    if tag == "empEvent":
        return "event"
    return "open_recruitment"


def _normalize_event(values: dict[str, str | None], idx: int) -> RecruitmentInfoItem:
    event_term = values.get("eventTerm")
    return RecruitmentInfoItem(
        item_id=values.get("eventNo") or f"event-{idx}",
        item_type="event",
        title=values.get("eventNm") or "채용행사명 확인 필요",
        region=values.get("area"),
        start_date=_normalize_date(values.get("startDt")),
        end_date=_event_end_date(event_term),
        summary=event_term,
        detail_url=_WORK24_HOME,
        raw=values,
    )


def _normalize_open_recruitment(values: dict[str, str | None], idx: int) -> RecruitmentInfoItem:
    summary_parts = [values.get("coClcdNm"), values.get("empWantedTypeNm")]
    summary = " / ".join(part for part in summary_parts if part)
    return RecruitmentInfoItem(
        item_id=_first(values, "wantedAuthNo", "empSeqno", "id") or f"open-{idx}",
        item_type="open_recruitment",
        title=_first(values, "empWantedTitle", "wantedTitle", "title", "empNm") or "공채속보 제목 확인 필요",
        company=_first(values, "company", "corpNm", "empBusiNm"),
        region=_first(values, "region", "workRegion"),
        start_date=_normalize_date(_first(values, "empWantedStdt", "startDate", "receiptSdt")),
        end_date=_normalize_date(_first(values, "empWantedEndt", "endDate", "receiptEdt", "closeDt")),
        summary=_first(values, "jobCont", "summary") or summary or None,
        detail_url=_first(
            values,
            "empWantedHomepgDetail",
            "empWantedMobileUrl",
            "wantedInfoUrl",
            "url",
        ),
        raw=values,
    )


def _round_robin(groups: Sequence[list[RecruitmentInfoItem]], limit: int) -> list[RecruitmentInfoItem]:
    result: list[RecruitmentInfoItem] = []
    for index in range(max((len(group) for group in groups), default=0)):
        for group in groups:
            if index < len(group):
                result.append(group[index])
                if len(result) >= limit:
                    return result
    return result


class Work24RecruitmentRepository:
    """고용24 개인회원에 허용된 채용 보조 정보 API 접근 계층.

    fallback_repository는 라이브 API 키 미설정 또는 2개 하위 API 호출이 전부
    실패했을 때만 사용되는 Supabase 캐시 조회 계층이다
    (app.repositories.supabase_fallback.SupabaseRecruitmentInfoFallback와 호환되는
    search(query) -> list[RecruitmentInfoItem] 메서드가 있으면 된다).
    """

    def __init__(self, fallback_repository: object | None = None) -> None:
        self._settings = get_settings()
        self._fallback_repository = fallback_repository

    async def _fallback_search(self, query: RecruitmentInfoSearchInput) -> list[RecruitmentInfoItem]:
        if self._fallback_repository is None:
            return []
        try:
            items = await self._fallback_repository.search(query)
        except Exception:  # noqa: BLE001 - 캐시 fallback 실패가 상위 흐름을 막으면 안 됨
            logger.exception("[캐시 폴백] 고용24 채용정보 캐시 조회 실패")
            return []
        if items:
            logger.info("[캐시 폴백] 고용24 채용정보 캐시에서 %d건 반환", len(items))
        else:
            logger.info("[캐시 폴백] 고용24 채용정보 캐시에도 결과 없음")
        return items

    async def search(self, query: RecruitmentInfoSearchInput) -> list[RecruitmentInfoItem]:
        if not self._settings.employment24_job_api_key:
            logger.warning("[캐시 폴백] EMPLOYMENT24_JOB_API_KEY 미설정 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
            return [recruitment_fallback_guide("EMPLOYMENT24_JOB_API_KEY 미설정", query)]

        fetch_size = min(query.page_size * _POST_FILTER_FETCH_MULTIPLIER, 100)
        common_params: dict[str, Any] = {
            "authKey": self._settings.employment24_job_api_key,
            "callTp": "L",
            "returnType": "XML",
            "startPage": str(query.page),
            "display": str(fetch_size),
        }
        keyword = query.desired_job or query.keywords
        groups: list[list[RecruitmentInfoItem]] = []
        failed_sources: list[str] = []

        def collect(result: list[RecruitmentInfoItem] | None, label: str) -> None:
            if result is None:
                failed_sources.append(label)
            else:
                groups.append(result)

        async with httpx.AsyncClient(timeout=source_http_timeout(self._settings)) as client:
            open_params = dict(common_params)
            if keyword:
                open_params["empWantedTitle"] = keyword
            if query.career_level and "신입" in query.career_level:
                open_params["empWantedCareerCd"] = "30"
            elif query.career_level and "인턴" in query.career_level:
                open_params["empWantedCareerCd"] = "40"

            event_params = dict(common_params)
            if keyword:
                event_params["keyword"] = keyword
            area_code = _event_area_code(query.preferred_work_region)
            if area_code:
                event_params["areaCd"] = area_code

            open_result, event_result = await asyncio.gather(
                self._fetch(
                    client,
                    self._settings.employment24_open_recruitment_api_url,
                    open_params,
                    "open_recruitment",
                    "공채속보",
                ),
                self._fetch(
                    client,
                    self._settings.employment24_job_event_api_url,
                    event_params,
                    "event",
                    "채용행사",
                ),
            )
            collect(open_result, "공채속보")
            collect(event_result, "채용행사")

        # Region/career evidence is checked after normalization, so preserve a
        # bounded oversampled pool rather than truncating before those gates.
        items = _round_robin(groups, fetch_size)
        if items:
            if failed_sources:
                reason = f"일부 고용24 채용 보조 API 호출 실패: {', '.join(failed_sources)}"
                return [*items, recruitment_fallback_guide(reason, query)]
            return items
        # A successful empty live response is authoritative NO_MATCH, not an
        # outage. Only replace it with cache data when every live endpoint
        # failed; otherwise stale cache rows could be presented as current.
        if len(failed_sources) == 2:
            logger.warning("[캐시 폴백] 고용24 채용 API 호출 전면 실패 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
        if failed_sources:
            reason = f"고용24 채용 보조 API 호출 실패: {', '.join(failed_sources)}"
            return [recruitment_fallback_guide(reason, query)]
        return [recruitment_fallback_guide("허용된 고용24 채용 API 결과 없음", query)]

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, Any],
        item_type: str,
        label: str,
    ) -> list[RecruitmentInfoItem] | None:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001 - one endpoint must not block the others
            log_external_api_error(logger, f"고용24 {label} API", exc)
            return None

        if is_personal_key_limited_response(response.text):
            logger.warning("고용24 %s API가 현재 개인키 권한을 허용하지 않습니다.", label)
            return None

        try:
            return normalize_recruitment_items(response.text, item_type)
        except (ET.ParseError, Work24RecruitmentResponseError):
            logger.warning("고용24 %s XML 오류 응답", label)
            return None

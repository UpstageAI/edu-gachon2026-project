from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Any

import httpx

from app.core.config import get_settings, source_http_timeout
from app.core.http import log_external_api_error
from app.core.regions import (
    SIDO_CODE_PREFIXES,
    region_distance_km,
    resolve_region,
    youth_local_authority_region_label,
    youth_policy_region_scope,
    youth_region_label,
)
from app.core.xml_utils import xml_error_message
from app.tools.schemas import YouthPolicyItem, YouthPolicySearchInput

logger = logging.getLogger(__name__)

# 설정값(.env의 YOUTHCENTER_POLICY_API_URL)이 없을 때를 위한 공식 문서 기준 기본 엔드포인트.
OFFICIAL_YOUTH_POLICY_API_URL = "https://www.youthcenter.go.kr/go/ythip/getPlcy"
_GENERIC_POLICY_QUERIES = {
    "청년",
    "청년 정책",
    "청년정책",
    "정책",
    "정책 검색",
    "정책 검색 요청",
    "지원",
    "지원 사업",
    "지원사업",
    "청년 지원",
    "청년지원",
    "청년 지원 정책",
    "청년지원정책",
    "청년 지원사업",
    "청년지원사업",
}
_POLICY_TOPIC_ALIASES = (
    (("거주지원", "주거지원", "주거비", "월세", "전세", "주거"), "주거"),
    (("취업지원", "구직지원", "취업", "구직", "일경험", "일자리"), "취업"),
    (("교육지원", "직업훈련", "역량강화", "교육", "훈련"), "교육"),
    (("금융지원", "자산형성", "복지지원", "생활지원", "문화지원", "금융", "복지", "문화"), "복지"),
    (("청년참여", "청년권리", "정책참여", "참여", "권리", "기반"), "참여"),
)
_REGION_PREFIXES = SIDO_CODE_PREFIXES
_NEARBY_RESULT_LIMIT = 3
_BROAD_POLICY_TOPIC_MARKERS = (
    "취업지원",
    "구직지원",
    "일자리",
    "거주지원",
    "주거지원",
    "주거정책",
    "교육지원",
    "직업훈련",
    "복지지원",
    "청년참여",
    "정책참여",
)
_NARROW_POLICY_TOPIC_MARKERS = ("월세", "전세", "주거비", "금융", "자산형성", "문화", "건강")


class YouthCenterAPIUnavailableError(RuntimeError):
    """The official Youth Center API could not provide a valid response."""


def youth_policy_fallback_guide(reason: str) -> YouthPolicyItem:
    return YouthPolicyItem(
        policy_id="youthcenter-guide",
        title="온통청년 청년정책 조회 안내",
        organization="온통청년",
        fallback_reason=reason,
    )


def _compact_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    return text or None


def _first(values: dict[str, str | None], *keys: str) -> str | None:
    for key in keys:
        value = values.get(key)
        if value:
            return value
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _record_values(node: ET.Element) -> dict[str, str | None]:
    return {
        _local_name(child.tag): _compact_text(child.text)
        for child in node.iter()
        if child is not node and len(child) == 0
    }


def normalize_youth_policy_items(xml_text: str) -> list[YouthPolicyItem]:
    root = ET.fromstring(xml_text)
    record_tags = {"youthPolicy", "policy", "item", "plcy"}
    records = [node for node in root.iter() if _local_name(node.tag) in record_tags]
    items: list[YouthPolicyItem] = []

    for idx, node in enumerate(records, start=1):
        values = _record_values(node)
        title = _first(values, "polyBizSjnm", "plcyNm", "policyName", "title") or "청년정책명 확인 필요"
        min_age, max_age, age_restricted = _age_bounds(values)
        item = YouthPolicyItem(
            policy_id=_first(values, "bizId", "plcyNo", "policyId", "id") or str(idx),
            title=title,
            organization=_first(values, "cnsgNmor", "sprvsnInstCdNm", "operInstCdNm", "operOrgan", "organization"),
            region=_effective_region_label(values) or _first(values, "regionNm", "region", "polyBizSecd"),
            min_age=min_age,
            max_age=max_age,
            age_restricted=age_restricted,
            target_summary=_first(values, "ageInfo", "plcySprtTrgtCn", "target", "rqutPrdCn"),
            support_summary=_first(values, "sporCn", "plcySprtCn", "support", "content"),
            business_period=_business_period(values),
            business_end_date=_iso_date(values.get("bizPrdEndYmd")),
            application_period=_first(values, "rqutPrdCn", "aplyYmd", "applicationPeriod"),
            application_method=_first(values, "rqutProcCn", "plcyAplyMthdCn", "applicationMethod"),
            detail_url=_first(values, "rfcSiteUrla1", "aplyUrlAddr", "detailUrl", "url"),
            raw=values,
        )
        items.append(item)

    return items


def normalize_youth_policy_json(payload: dict[str, Any]) -> list[YouthPolicyItem]:
    result = payload.get("result") or {}
    records = result.get("youthPolicyList") if isinstance(result, dict) else []
    if not isinstance(records, list):
        return []

    items: list[YouthPolicyItem] = []
    for idx, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            continue
        values = {key: _compact_text(str(value)) for key, value in record.items() if value is not None}
        min_age, max_age, age_restricted = _age_bounds(values)
        target_parts = [
            _first(values, "ptcpPrpTrgtCn", "addAplyQlfcCndCn"),
            _age_summary(values),
        ]
        items.append(
            YouthPolicyItem(
                policy_id=_first(values, "plcyNo", "bizId", "id") or str(idx),
                title=_first(values, "plcyNm", "polyBizSjnm", "title") or "청년정책명 확인 필요",
                organization=_first(
                    values,
                    "operInstCdNm",
                    "sprvsnInstCdNm",
                    "rgtrInstCdNm",
                    "rgtrHghrkInstCdNm",
                ),
                region=_effective_region_label(values) or _first(values, "regionNm", "region"),
                min_age=min_age,
                max_age=max_age,
                age_restricted=age_restricted,
                target_summary=" / ".join(part for part in target_parts if part) or None,
                support_summary=_first(values, "plcySprtCn", "plcyExplnCn", "support"),
                business_period=_business_period(values),
                business_end_date=_iso_date(values.get("bizPrdEndYmd")),
                application_period=_first(values, "aplyYmd", "rqutPrdCn", "applicationPeriod"),
                application_method=_first(values, "plcyAplyMthdCn", "rqutProcCn", "applicationMethod"),
                detail_url=_first(values, "aplyUrlAddr", "refUrlAddr1", "refUrlAddr2", "url"),
                raw=values,
            )
        )
    return items


def _positive_age(value: str | None) -> int | None:
    if not value:
        return None
    try:
        age = int(value)
    except (TypeError, ValueError):
        return None
    return age if age > 0 else None


def _age_bounds(values: dict[str, str | None]) -> tuple[int | None, int | None, bool | None]:
    limit_flag = (values.get("sprtTrgtAgeLmtYn") or "").strip().upper()
    if limit_flag == "N":
        return None, None, False

    minimum = _positive_age(values.get("sprtTrgtMinAge"))
    maximum = _positive_age(values.get("sprtTrgtMaxAge"))
    if minimum is not None or maximum is not None:
        return minimum, maximum, True

    raw_minimum = values.get("sprtTrgtMinAge")
    raw_maximum = values.get("sprtTrgtMaxAge")
    if raw_minimum == "0" or raw_maximum == "0":
        return None, None, False
    if limit_flag == "Y":
        return None, None, True
    return None, None, None


def _age_summary(values: dict[str, str | None]) -> str | None:
    minimum, maximum, age_restricted = _age_bounds(values)
    if age_restricted is False:
        return "연령 제한 없음"
    if minimum is not None and maximum is not None:
        return f"만 {minimum}~{maximum}세"
    if minimum is not None:
        return f"만 {minimum}세 이상"
    if maximum is not None:
        return f"만 {maximum}세 이하"
    return None


def _iso_date(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"\D", "", value)
    if len(compact) != 8:
        return value
    try:
        return datetime.strptime(compact, "%Y%m%d").date().isoformat()
    except ValueError:
        return value


def _business_period(values: dict[str, str | None]) -> str | None:
    start = _iso_date(values.get("bizPrdBgngYmd"))
    end = _iso_date(values.get("bizPrdEndYmd"))
    if start and end:
        return f"{start} ~ {end}"
    if start:
        return f"{start}부터"
    if end:
        return f"{end}까지"
    return values.get("bizPrdEtcCn")


def _region_label(zip_codes: str | None) -> str | None:
    return youth_region_label(zip_codes)


def _effective_region_label(values: dict[str, str | None]) -> str | None:
    zip_label = _region_label(values.get("zipCd"))
    if zip_label != "전국":
        return zip_label

    authority_region = youth_local_authority_region_label(
        values.get("rgtrInstCdNm"),
        values.get("rgtrHghrkInstCdNm"),
        values.get("sprvsnInstCdNm"),
        values.get("operInstCdNm"),
    )
    return authority_region or zip_label


def _filter_youth_policies_by_region(
    items: list[YouthPolicyItem],
    region: str | None,
) -> list[YouthPolicyItem]:
    if not region:
        return items
    return [
        item
        for item in items
        if youth_policy_region_scope(region, str(item.raw.get("zipCd") or ""), item.region) in {"exact", "nationwide"}
    ]


def _mark_youth_region_matches(items: list[YouthPolicyItem], region: str | None) -> list[YouthPolicyItem]:
    marked: list[YouthPolicyItem] = []
    for item in items:
        scope = youth_policy_region_scope(region, str(item.raw.get("zipCd") or ""), item.region)
        if scope not in {"exact", "nationwide"}:
            continue
        marked.append(item.model_copy(update={"match_scope": scope, "distance_km": None}))
    return marked


def _nearby_youth_policies(items: list[YouthPolicyItem], region: str | None) -> list[YouthPolicyItem]:
    nearby: list[YouthPolicyItem] = []
    for item in items:
        scope = youth_policy_region_scope(region, str(item.raw.get("zipCd") or ""), item.region)
        if scope != "mismatch":
            continue
        distance = region_distance_km(region, [item.region] if item.region else [])
        if distance is None:
            continue
        nearby.append(item.model_copy(update={"match_scope": "nearby", "distance_km": distance}))

    unique: dict[str, YouthPolicyItem] = {}
    for item in sorted(nearby, key=lambda candidate: candidate.distance_km or float("inf")):
        unique.setdefault(item.policy_id, item)
    return list(unique.values())[:_NEARBY_RESULT_LIMIT]


def _filter_active_youth_policies(
    items: list[YouthPolicyItem],
    today: date | None = None,
) -> list[YouthPolicyItem]:
    reference_date = today or date.today()
    active: list[YouthPolicyItem] = []
    for item in items:
        application_end_date = _latest_date_in_period(item.application_period)
        if application_end_date and application_end_date < reference_date:
            continue
        if not item.business_end_date:
            active.append(item)
            continue
        try:
            end_date = date.fromisoformat(item.business_end_date)
        except ValueError:
            active.append(item)
            continue
        if end_date >= reference_date:
            active.append(item)
    return active


def _latest_date_in_period(value: str | None) -> date | None:
    if not value:
        return None

    parsed: list[date] = []
    pattern = re.compile(r"(?<!\d)(20\d{2})(?:[.\-/년]\s*)?(\d{1,2})(?:[.\-/월]\s*)?(\d{1,2})(?:일)?(?!\d)")
    for year, month, day in pattern.findall(value):
        try:
            parsed.append(date(int(year), int(month), int(day)))
        except ValueError:
            continue
    return max(parsed) if parsed else None


def is_generic_youth_policy_query(value: str | None) -> bool:
    if not value:
        return True
    normalized = " ".join(value.split()).strip()
    compact = re.sub(r"\s+", "", normalized)
    compact_generic_queries = {re.sub(r"\s+", "", item) for item in _GENERIC_POLICY_QUERIES}
    if normalized in _GENERIC_POLICY_QUERIES or compact in compact_generic_queries:
        return True

    if any(alias in compact for aliases, _ in _POLICY_TOPIC_ALIASES for alias in aliases):
        return False

    broad_phrases = ("청년정책", "청년지원정책", "청년지원사업", "청년지원")
    return any(phrase in compact for phrase in broad_phrases)


def is_narrow_youth_policy_query(value: str | None) -> bool:
    """구체 하위 유형·정책명이라 상위 분야로 완화하면 안 되는 검색인지 판정한다."""

    if not value or is_generic_youth_policy_query(value):
        return False
    compact = re.sub(r"\s+", "", value)
    if compact in {"주거", "취업", "교육", "훈련", "복지", "참여", "금융·복지·문화", "금융복지문화"}:
        return False
    if any(marker in compact for marker in _NARROW_POLICY_TOPIC_MARKERS):
        return True
    if any(marker in compact for marker in _BROAD_POLICY_TOPIC_MARKERS):
        return False
    return True


def _build_youth_search_terms(query: YouthPolicySearchInput) -> list[str | None]:
    """Build progressively broader title searches for the current Youth Center API."""

    terms: list[str] = []
    recognized_topic = False
    keyword = " ".join(query.keywords.split()).strip()
    has_specific_keyword = bool(keyword and not is_generic_youth_policy_query(keyword))
    keep_specific_scope = has_specific_keyword and is_narrow_youth_policy_query(keyword)
    candidates = (
        [query.keywords] if has_specific_keyword else [query.keywords, *query.support_types, *query.interest_fields]
    )

    for candidate in candidates:
        normalized = " ".join(candidate.split()).strip()
        if not normalized:
            continue
        if not is_generic_youth_policy_query(normalized) and normalized not in terms:
            terms.append(normalized[:50])

        if keep_specific_scope and candidate == query.keywords:
            continue

        compact = re.sub(r"\s+", "", normalized)
        for aliases, topic in _POLICY_TOPIC_ALIASES:
            if any(alias in compact for alias in aliases):
                recognized_topic = True
                if topic not in terms:
                    terms.append(topic)

    if not recognized_topic and query.employment_status == "unemployed_seeking_job" and "취업" not in terms:
        terms.append("취업")

    return terms[:3] or [None]


class YouthCenterRepository:
    """온통청년 청년정책 Open API 접근 계층.

    fallback_repository는 라이브 API 키 미설정 또는 호출 전면 실패(요청 한도 초과,
    장애 등) 시에만 사용되는 Supabase 캐시 조회 계층이다
    (app.repositories.supabase_fallback.SupabaseYouthPolicyFallback와 호환되는
    search(query) -> list[YouthPolicyItem] 메서드가 있으면 된다).
    """

    def __init__(self, fallback_repository: object | None = None) -> None:
        self._settings = get_settings()
        self._fallback_repository = fallback_repository

    async def _fallback_search(self, query: YouthPolicySearchInput) -> list[YouthPolicyItem]:
        if self._fallback_repository is None:
            return []
        try:
            items = await self._fallback_repository.search(query)
        except Exception:  # noqa: BLE001 - 캐시 fallback 실패가 상위 흐름을 막으면 안 됨
            logger.exception("[캐시 폴백] 온통청년 캐시 조회 실패")
            return []
        if items:
            logger.info("[캐시 폴백] 온통청년 캐시에서 %d건 반환", len(items))
        else:
            logger.info("[캐시 폴백] 온통청년 캐시에도 결과 없음")
        return items

    async def search(self, query: YouthPolicySearchInput) -> list[YouthPolicyItem]:
        if not self._settings.youthcenter_policy_api_key:
            logger.warning("[캐시 폴백] YOUTHCENTER_POLICY_API_KEY 미설정 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
            return [youth_policy_fallback_guide("온통청년 API 키가 설정되지 않아 현재 조회할 수 없어요.")]

        base_params = {
            "apiKeyNm": self._settings.youthcenter_policy_api_key,
            "pageNum": str(query.page),
            "pageSize": str(min(max(query.page_size * 20, 50), 100) if query.region else query.page_size),
        }
        api_url = self._settings.youthcenter_policy_api_url or OFFICIAL_YOUTH_POLICY_API_URL
        successful_fetches = 0
        failed_fetches = 0
        allow_nearby_results = not is_narrow_youth_policy_query(query.keywords)

        def with_partial_warning(items: list[YouthPolicyItem]) -> list[YouthPolicyItem]:
            selected = items[: query.page_size]
            if failed_fetches:
                selected.append(
                    youth_policy_fallback_guide("온통청년 일부 조회가 일시적으로 완료되지 않아 확인된 결과만 안내해요.")
                )
            return selected

        async with httpx.AsyncClient(
            timeout=source_http_timeout(self._settings),
            follow_redirects=False,
        ) as client:
            nearby_pool: list[YouthPolicyItem] = []
            resolved_region = resolve_region(query.region)

            async def fetch_active(params: dict[str, str]) -> list[YouthPolicyItem]:
                nonlocal failed_fetches, successful_fetches
                try:
                    items = await self._fetch(client, api_url, params)
                except YouthCenterAPIUnavailableError:
                    failed_fetches += 1
                    return []
                successful_fetches += 1
                return _filter_active_youth_policies(items)

            for search_term in _build_youth_search_terms(query):
                params = dict(base_params)
                if search_term:
                    params["plcyNm"] = search_term

                if resolved_region and resolved_region.youth_code:
                    exact_params = {**params, "zipCd": resolved_region.youth_code}
                    exact_items = await fetch_active(exact_params)
                    exact_matches = _mark_youth_region_matches(exact_items, query.region)
                    if exact_matches:
                        return with_partial_warning(exact_matches)

                broad_items = await fetch_active(params)
                primary_matches = _mark_youth_region_matches(broad_items, query.region)
                if primary_matches:
                    return with_partial_warning(primary_matches)
                if allow_nearby_results:
                    nearby_pool.extend(_nearby_youth_policies(broad_items, query.region))

        if nearby_pool:
            return with_partial_warning(_nearby_youth_policies(nearby_pool, query.region))
        if failed_fetches and not successful_fetches:
            logger.warning("[캐시 폴백] 온통청년 API 호출 전면 실패 → 캐시 조회 시도")
            cached = await self._fallback_search(query)
            if cached:
                return cached
        if failed_fetches:
            return [
                youth_policy_fallback_guide(
                    "온통청년 API가 일시적으로 응답하지 않아 정책 유무를 확인하지 못했어요. 잠시 후 다시 검색해주세요."
                )
            ]
        return []

    async def _fetch(
        self,
        client: httpx.AsyncClient,
        api_url: str,
        params: dict[str, str],
    ) -> list[YouthPolicyItem]:
        try:
            response = await client.get(api_url, params=params)
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            # Retry is owned by the traceable retrieve→assess_evidence graph
            # edge, so the repository must not add a hidden second attempt.
            log_external_api_error(logger, "온통청년 API", exc)
            raise YouthCenterAPIUnavailableError from exc

        if "json" in response.headers.get("content-type", "").lower() or response.text.lstrip().startswith("{"):
            try:
                payload = response.json()
            except ValueError:
                logger.warning("온통청년 JSON 파싱 실패")
                raise YouthCenterAPIUnavailableError from None
            if str(payload.get("resultCode")) != "200":
                logger.warning("온통청년 API 비정상 응답 (result_code=%s)", payload.get("resultCode"))
                raise YouthCenterAPIUnavailableError
            return normalize_youth_policy_json(payload)

        try:
            root = ET.fromstring(response.text)
            if xml_error_message(root, record_tags={"youthpolicy", "policy", "item", "plcy"}):
                logger.warning("온통청년 XML 오류 응답")
                raise YouthCenterAPIUnavailableError
            return normalize_youth_policy_items(response.text)
        except ET.ParseError:
            logger.warning("온통청년 XML 파싱 실패")
            raise YouthCenterAPIUnavailableError from None

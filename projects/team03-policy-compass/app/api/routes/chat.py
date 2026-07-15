"""채팅 API 라우트.

/api/chat : 동기 방식 (테스트/단순 클라이언트용)
/api/chat/stream : SSE 스트리밍 방식

SSE는 LangGraph 노드 완료 상태를 허용된 사용자 문구로 즉시 전송한다.
최종 응답은 가드레일과 finalize를 통과한 후에만 자연스러운 청크 단위로
전송한다 (LLM 토큰 단위 스트리밍은 별도 후속 과제).
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.core.dates import deadline_status
from app.core.observability import create_langfuse_handler, get_langfuse_client, langfuse_trace_context
from app.core.privacy import (
    detect_sensitive_data,
    privacy_guard_reply,
    redact_sensitive_structure,
    redact_sensitive_text,
)
from app.core.session_control import SessionLockPool, SlidingWindowRateLimiter
from app.graph.graph import get_agent_graph
from app.graph.profile_contracts import sanitize_profile
from app.graph.state import fresh_turn_fields
from app.repositories.chat_memory import ChatMemoryContext, SupabaseChatMemoryRepository
from app.repositories.feedback import SupabaseFeedbackRepository
from app.schemas.chat import ChatRequest, ChatTurnResponse, RecommendationFeedbackRequest, UserProfile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

_STREAM_CHUNK_SIZE = 24
_MAX_RECOMMENDATIONS = 3  # app/core/prompts.py의 "최대 3개 결과" 규칙과 맞춘 상한
_chat_memory = SupabaseChatMemoryRepository()
_feedback_repo = SupabaseFeedbackRepository()
_session_locks = SessionLockPool()
_chat_rate_limiter = SlidingWindowRateLimiter()
_feedback_rate_limiter = SlidingWindowRateLimiter()


def _sanitize_legacy_profile(raw_profile: dict | None) -> dict:
    """Validate stored profiles while silently dropping removed legacy fields."""

    return sanitize_profile(raw_profile)


def _sanitize_legacy_pending(raw_pending: dict | None) -> dict:
    pending = dict(raw_pending or {})
    return {} if pending.get("request_kind") == "business" else pending


_LAST_SEARCH_FILTER_KEYS = {
    "region",
    "training_region",
    "work_region",
    "training_keyword",
    "keyword",
    "career_level",
    "policy_keyword",
    "active_only",
    "region_mode",
}
_DURABLE_PROFILE_FIELDS = {"age", "region", "employment_status"}


def _sanitize_last_search_plan(raw_plan: dict | None) -> dict:
    """Keep only the minimal completed-search contract needed for a later refinement."""

    if not isinstance(raw_plan, dict) or raw_plan.get("request_kind") not in {
        "youth_policy",
        "training",
        "recruitment",
    }:
        return {}
    plan = {
        "request_kind": raw_plan["request_kind"],
        "response_mode": raw_plan.get("response_mode")
        if raw_plan.get("response_mode") in {"recommend", "explain", "eligibility"}
        else "recommend",
        "source_status": raw_plan.get("source_status")
        if raw_plan.get("source_status") in {"success", "no_match", "partial", "unavailable"}
        else None,
    }
    search_query = raw_plan.get("search_query")
    if isinstance(search_query, str) and search_query.strip():
        plan["search_query"] = " ".join(search_query.split())[:100]
    raw_filters = raw_plan.get("effective_filters")
    if isinstance(raw_filters, dict):
        plan["effective_filters"] = redact_sensitive_structure(
            {
                key: value
                for key, value in raw_filters.items()
                if key in _LAST_SEARCH_FILTER_KEYS and value not in (None, "", [], {})
            }
        )
    else:
        plan["effective_filters"] = {}
    return {key: value for key, value in plan.items() if value is not None}


def _last_search_plan_update(result: dict) -> dict | None:
    outcome = result.get("search_outcome") or {}
    if result.get("action") != "SEARCH" or not outcome.get("status"):
        return None
    context = result.get("search_context") or {}
    filters = dict(outcome.get("applied_filters") or {})
    filters["region_mode"] = result.get("region_filter_mode", "specific")
    return _sanitize_last_search_plan(
        {
            "request_kind": result.get("request_kind"),
            "response_mode": result.get("response_mode"),
            "search_query": context.get("search_query") or result.get("search_query"),
            "effective_filters": filters,
            "source_status": outcome.get("status"),
        }
    )


def _profile_for_memory(result: dict) -> dict:
    """Persist task fields only while they are needed to resume clarification."""

    profile = _sanitize_legacy_profile(result.get("profile") or {})
    if result.get("pending_request"):
        return profile
    return {key: value for key, value in profile.items() if key in _DURABLE_PROFILE_FIELDS}


def _result_status_message(result: dict) -> str:
    """Return a user-facing progress message from the validated router result."""

    if result.get("privacy_blocked"):
        return "민감정보를 감지해 입력을 보호 처리했어요."
    if result.get("timed_out"):
        return "처리 제한 시간을 초과해 이번 요청을 안전하게 중단했어요."
    request_kind = result.get("request_kind", "general")
    missing_slots = result.get("missing_slots") or []
    labels = {
        "youth_policy": "청년정책",
        "training": "고용24 훈련과정",
        "recruitment": "채용 보조정보",
    }

    if request_kind in labels:
        label = labels[request_kind]
        if missing_slots:
            return f"{label} 추천에 필요한 조건을 정리했어요."
        return f"{label} 검색 결과를 확인했어요."

    return {
        "EXPLAIN": "질문에 맞는 설명을 정리했어요.",
        "OUT_OF_SCOPE": "지원 가능한 상담 범위를 확인했어요.",
    }.get(result.get("intent", "GENERAL"), "대화 내용을 바탕으로 답변을 정리했어요.")


_REQUEST_KIND_LABELS = {
    "youth_policy": "청년정책",
    "training": "고용24 훈련과정",
    "recruitment": "채용 보조정보",
}


def _node_status_message(node_name: str, state: dict) -> str | None:
    """Map allowlisted graph progress to user text without exposing node state."""

    label = _REQUEST_KIND_LABELS.get(state.get("request_kind"), "관련 정보")
    if node_name == "prepare_request":
        if state.get("missing_slots"):
            return f"{label} 안내에 필요한 조건을 확인했어요."
        if state.get("action") == "SEARCH":
            return f"{label} 검색 조건을 확인하고 있어요."
        return "질문 의도와 대화 맥락을 확인했어요."
    if node_name == "retrieve":
        if int(state.get("search_attempt_count") or 0) > 1:
            return f"{label}를 다시 조회했고, 결과 근거를 확인하고 있어요."
        return f"{label} 조회 결과의 근거를 확인하고 있어요."
    if node_name == "assess_evidence":
        return "검색 결과와 요청 조건을 비교했어요."
    if node_name == "rewrite_query":
        return "요청 조건은 유지하고 검색 표현을 보완했어요."
    if node_name == "build_answer":
        if int(state.get("response_revision_count") or 0) > 0:
            return "검증 결과를 반영한 답변을 다시 확인하고 있어요."
        return "검색 결과로 만든 답변의 근거를 확인하고 있어요."
    if node_name == "direct_response":
        if int(state.get("response_revision_count") or 0) > 0:
            return "검증 결과를 반영해 안전한 답변으로 다시 정리했어요."
        return "답변의 범위와 안전성을 확인하고 있어요."
    if node_name == "verify_answer":
        if state.get("response_validation_status") == "passed":
            return "답변의 근거와 안전성 검증을 마쳤어요."
        return "검증 결과를 반영해 답변을 다시 정리하고 있어요."
    if node_name == "finalize":
        return "검증된 답변을 전달할게요."
    return None


def _format_cost(value: str | None) -> str | None:
    """'582560' 같은 순수 숫자 문자열을 '582,560원'으로 바꾼다.
    이미 단위/문자가 섞여 있거나 숫자가 아니면 원본 그대로 둔다."""

    if not value or not value.isdigit():
        return value
    return f"{int(value):,}원"


def _evidence_card_metadata(item: dict) -> tuple[str, list[str], list[str]]:
    """Normalize the three-state evidence contract for the frontend envelope."""

    unverified_reasons = [
        str(reason)
        for reason in item.get("unverified_reasons") or []
        if reason in {"age_unverified", "region_unverified", "career_unverified"}
    ]
    evidence_status = (
        "unverified"
        if item.get("evidence_status") == "unverified" or item.get("match_scope") == "unknown"
        else "verified"
    )
    if evidence_status == "verified":
        return evidence_status, [], []

    labels = {
        "age_unverified": "연령 조건",
        "region_unverified": "지역 조건",
        "career_unverified": "경력 조건",
    }
    checks = [f"공식 원문에서 {labels[reason]}을 확인해 주세요." for reason in unverified_reasons]
    if not checks:
        checks = ["공식 원문에서 실제 지원·신청 조건을 확인해 주세요."]
    return evidence_status, unverified_reasons, checks


def _training_to_recommendation(item: dict) -> dict:
    cost_text = _format_cost(item.get("actual_cost")) or _format_cost(item.get("cost")) or "문의 필요"
    match_scope = item.get("match_scope") if item.get("match_scope") in {"exact", "nationwide"} else "unknown"
    evidence_status, unverified_reasons, follow_up_checks = _evidence_card_metadata(item)
    is_recommendable = match_scope != "unknown" and evidence_status == "verified"
    recommendation_scope = match_scope if is_recommendable else "excluded"
    policy = {
        "id": item.get("course_id", ""),
        "title": item.get("title", ""),
        "agency": item.get("institution") or "",
        "category": "훈련과정",
        "target_description": item.get("target") or "",
        "region": [item["region"]] if item.get("region") else ["전국"],
        "min_age": None,
        "max_age": None,
        "apply_start": item.get("start_date"),
        "apply_end": item.get("end_date"),
        "apply_method": item.get("contact") or "고용24 참조",
        "support_content": f"훈련비: {cost_text}",
        "source_url": item.get("detail_url") or item.get("institution_url") or "",
        "match_scope": match_scope,
        "distance_km": None,
    }
    return {
        "policy": policy,
        "match_score": 0.0,
        "evidence_coverage": 0.0,
        "match_reasons": [
            "요청 지역과 일치하는 훈련과정으로 확인됐어요."
            if is_recommendable
            else "지역 표기가 구조화되지 않아 고용24 원문 확인이 필요한 참고 결과예요."
        ],
        "follow_up_checks": [] if is_recommendable else follow_up_checks,
        "hard_mismatches": [],
        "is_recommendable": is_recommendable,
        "recommendation_scope": recommendation_scope,
        "evidence_status": evidence_status,
        "unverified_reasons": unverified_reasons,
        "deadline_status": deadline_status(item.get("end_date")),
    }


_YOUTH_SCOPE_TO_RECOMMENDATION_SCOPE = {
    "exact": "exact",
    "nationwide": "nationwide",
    "nearby": "nearby_reference",
    "unknown": "excluded",
}


def _youth_policy_to_recommendation(item: dict) -> dict:
    match_scope = (
        item.get("match_scope") if item.get("match_scope") in _YOUTH_SCOPE_TO_RECOMMENDATION_SCOPE else "unknown"
    )
    evidence_status, unverified_reasons, follow_up_checks = _evidence_card_metadata(item)
    recommendation_scope = _YOUTH_SCOPE_TO_RECOMMENDATION_SCOPE.get(match_scope, "excluded")
    is_recommendable = match_scope not in {"nearby", "unknown"} and evidence_status == "verified"

    reasons = ["조건에 맞는 청년정책으로 검색됐어요."]
    if match_scope == "nearby":
        distance = item.get("distance_km")
        distance_text = f" 약 {distance:g}km" if isinstance(distance, int | float) else ""
        reasons = [f"요청 지역에서{distance_text} 떨어진 지역의 참고 결과예요."]
    elif evidence_status == "unverified":
        reasons = ["일부 지원 조건을 확인할 근거가 부족해 공식 원문 확인이 필요한 참고 결과예요."]

    policy = {
        "id": item.get("policy_id", ""),
        "title": item.get("title", ""),
        "agency": item.get("organization") or "",
        "category": "청년정책",
        "target_description": item.get("target_summary") or "",
        "region": [item["region"]] if item.get("region") else ["전국"],
        "min_age": item.get("min_age"),
        "max_age": item.get("max_age"),
        "apply_start": item.get("application_period"),
        "apply_end": None,
        "apply_method": item.get("application_method") or "",
        "support_content": item.get("support_summary") or "",
        "source_url": item.get("detail_url") or "",
        "match_scope": match_scope,
        "distance_km": item.get("distance_km"),
    }
    return {
        "policy": policy,
        "match_score": 0.0,
        "evidence_coverage": 0.0,
        "match_reasons": reasons,
        "follow_up_checks": follow_up_checks if evidence_status == "unverified" else [],
        "hard_mismatches": [],
        "is_recommendable": is_recommendable,
        "recommendation_scope": recommendation_scope,
        "evidence_status": evidence_status,
        "unverified_reasons": unverified_reasons,
        "deadline_status": deadline_status(item.get("business_end_date")),
    }


def _recruitment_to_recommendation(item: dict) -> dict:
    match_scope = item.get("match_scope") if item.get("match_scope") in {"exact", "nationwide"} else "unknown"
    evidence_status, unverified_reasons, follow_up_checks = _evidence_card_metadata(item)
    is_recommendable = match_scope != "unknown" and evidence_status == "verified"
    recommendation_scope = match_scope if is_recommendable else "excluded"
    item_type_label = "채용행사" if item.get("item_type") == "event" else "공채속보"
    if is_recommendable:
        match_reasons = ["요청 지역과 일치하는 고용24 채용 보조정보예요."]
    elif "career_unverified" in unverified_reasons and "region_unverified" not in unverified_reasons:
        match_reasons = ["경력 조건 근거가 부족해 고용24 원문 확인이 필요한 참고 정보예요."]
    else:
        match_reasons = ["근무 지역이 명확하지 않아 고용24 원문 확인이 필요한 참고 정보예요."]
    policy = {
        "id": item.get("item_id", ""),
        "title": item.get("title", ""),
        "agency": item.get("company") or "고용24",
        "category": item_type_label,
        "target_description": item.get("summary") or "고용24 원문에서 대상 조건 확인 필요",
        "region": [item["region"]] if item.get("region") else ["지역 확인 필요"],
        "min_age": None,
        "max_age": None,
        "apply_start": item.get("start_date"),
        "apply_end": item.get("end_date"),
        "apply_method": "고용24 원문 확인",
        "support_content": item.get("summary") or "채용 관련 상세 조건은 고용24 원문 확인 필요",
        "source_url": item.get("detail_url") or "",
        "match_scope": match_scope,
        "distance_km": None,
    }
    return {
        "policy": policy,
        "match_score": 0.0,
        "evidence_coverage": 0.0,
        "match_reasons": match_reasons,
        "follow_up_checks": [] if is_recommendable else follow_up_checks,
        "hard_mismatches": [],
        "is_recommendable": is_recommendable,
        "recommendation_scope": recommendation_scope,
        "evidence_status": evidence_status,
        "unverified_reasons": unverified_reasons,
        "deadline_status": deadline_status(item.get("end_date")),
    }


def _dedupe_by_title(items: list[dict], *, title_of: Callable[[dict], str]) -> list[dict]:
    """같은 과정/정책이 회차·페이지네이션 등으로 제목이 같은 채 여러 번 나오면
    첫 번째 항목만 남긴다 (예: 같은 훈련과정의 다른 회차)."""

    seen: set[str] = set()
    deduped: list[dict] = []
    for item in items:
        title = title_of(item).strip()
        if title and title in seen:
            continue
        if title:
            seen.add(title)
        deduped.append(item)
    return deduped


def _build_recommendations(result: dict) -> list[dict]:
    """Convert supported source results to the legacy frontend card envelope.

    The numeric score fields remain transport-only compatibility placeholders;
    the graph no longer ranks or decides eligibility with weighted scores.
    fallback_reason이 있는 항목(실제 검색 결과가 아닌 안내용 합성 레코드)은 제외하고,
    답변 텍스트와 동일하게 중복 제거 후 최대 _MAX_RECOMMENDATIONS개로 제한한다.
    """

    if not _has_verified_search_results(result):
        return []

    training = [
        item
        for item in result.get("training_results") or []
        if not item.get("fallback_reason") and item.get("match_scope") in {"exact", "nationwide", "unknown"}
    ]
    if training:
        training = _dedupe_by_title(training, title_of=lambda item: item.get("title") or "")[:_MAX_RECOMMENDATIONS]
        return [_training_to_recommendation(item) for item in training]

    youth = [
        item
        for item in result.get("youth_policy_results") or []
        if not item.get("fallback_reason") and item.get("match_scope") in {"exact", "nationwide", "nearby", "unknown"}
    ]
    if youth:
        youth = _dedupe_by_title(youth, title_of=lambda item: item.get("title") or "")[:_MAX_RECOMMENDATIONS]
        return [_youth_policy_to_recommendation(item) for item in youth]

    recruitment = [
        item
        for item in result.get("recruitment_results") or []
        if not item.get("fallback_reason")
        and item.get("item_type") in {"event", "open_recruitment"}
        and item.get("match_scope") in {"exact", "nationwide", "unknown"}
    ]
    if recruitment:
        recruitment = _dedupe_by_title(recruitment, title_of=lambda item: item.get("title") or "")[
            :_MAX_RECOMMENDATIONS
        ]
        return [_recruitment_to_recommendation(item) for item in recruitment]

    return []


def _has_verified_search_results(result: dict) -> bool:
    outcome = result.get("search_outcome") or {}
    return (
        result.get("action") == "SEARCH"
        and result.get("response_validation_status") == "passed"
        and outcome.get("status") in {"success", "partial"}
    )


_SNAPSHOT_FIELDS = {
    "youth_policy": (
        "policy_id",
        "title",
        "organization",
        "region",
        "min_age",
        "max_age",
        "target_summary",
        "support_summary",
        "application_period",
        "application_method",
        "detail_url",
        "match_scope",
        "evidence_status",
        "unverified_reasons",
    ),
    "training": (
        "course_id",
        "title",
        "institution",
        "region",
        "address",
        "start_date",
        "end_date",
        "cost",
        "actual_cost",
        "ncs_code",
        "detail_url",
        "match_scope",
        "evidence_status",
        "unverified_reasons",
    ),
    "recruitment": (
        "item_id",
        "item_type",
        "title",
        "company",
        "region",
        "start_date",
        "end_date",
        "summary",
        "detail_url",
        "match_scope",
        "evidence_status",
        "unverified_reasons",
    ),
}

_SNAPSHOT_ID_FIELDS = {
    "youth_policy": "policy_id",
    "training": "course_id",
    "recruitment": "item_id",
}
_LEGACY_GUIDE_IDS = {
    "youthcenter-guide",
    "work24-training-guide",
    "work24-recruitment-guide",
}


def _sanitize_candidate_snapshot(values: object) -> list[dict]:
    """Revalidate durable candidates so legacy/corrupt rows cannot bypass gates."""

    if not isinstance(values, list):
        return []
    sanitized: list[dict] = []
    for raw in values[:12]:
        if not isinstance(raw, dict):
            continue
        source = raw.get("source")
        if source not in _SNAPSHOT_FIELDS or raw.get("fallback_reason") or raw.get("item_type") == "guide":
            continue
        identifier_field = _SNAPSHOT_ID_FIELDS[source]
        identifier = raw.get(identifier_field)
        if not isinstance(identifier, str) or not identifier.strip() or identifier in _LEGACY_GUIDE_IDS:
            continue
        if not isinstance(raw.get("title"), str) or not raw["title"].strip():
            continue
        allowed_scopes = (
            {"exact", "nationwide", "nearby", "unknown"}
            if source == "youth_policy"
            else {"exact", "nationwide", "unknown"}
        )
        if raw.get("match_scope") not in allowed_scopes:
            continue
        if raw.get("match_scope") == "unknown" and raw.get("evidence_status") != "unverified":
            continue
        if source == "recruitment" and raw.get("item_type") not in {"event", "open_recruitment"}:
            continue

        item = {
            "source": source,
            **{key: value for key in _SNAPSHOT_FIELDS[source] if (value := raw.get(key)) not in (None, "", [], {})},
        }
        search_query = raw.get("search_query")
        if isinstance(search_query, str) and search_query.strip():
            item["search_query"] = " ".join(search_query.split())[:100]
        for url_field in ("detail_url", "institution_url", "source_url"):
            url = item.get(url_field)
            if isinstance(url, str) and urlparse(url).scheme not in {"http", "https"}:
                item.pop(url_field, None)
        sanitized.append(item)
        if len(sanitized) == _MAX_RECOMMENDATIONS:
            break
    return sanitized


def _presented_candidate_snapshot(result: dict) -> list[dict] | None:
    """Build an allowlisted snapshot only when this turn displayed candidates."""

    if not _has_verified_search_results(result) or result.get("missing_slots"):
        return None

    source_and_items = (
        ("youth_policy", result.get("youth_policy_results") or []),
        ("training", result.get("training_results") or []),
        ("recruitment", result.get("recruitment_results") or []),
    )
    raw_search_query = (result.get("search_context") or {}).get("search_query") or result.get("search_query")
    normalized_search_query = " ".join(raw_search_query.split()) if isinstance(raw_search_query, str) else ""
    snapshot_search_query = normalized_search_query[:100] or None
    for source, items in source_and_items:
        allowed_types = {"event", "open_recruitment"} if source == "recruitment" else None
        allowed_scopes = (
            {"exact", "nationwide", "nearby", "unknown"}
            if source == "youth_policy"
            else {"exact", "nationwide", "unknown"}
        )
        safe_items = [
            item
            for item in items
            if not item.get("fallback_reason")
            and item.get("item_type") != "guide"
            and (allowed_types is None or item.get("item_type") in allowed_types)
            and item.get("match_scope") in allowed_scopes
            and (item.get("match_scope") != "unknown" or item.get("evidence_status") == "unverified")
        ]
        if not safe_items:
            continue
        return [
            {
                "source": source,
                **({"search_query": snapshot_search_query} if snapshot_search_query else {}),
                **{
                    key: value for key in _SNAPSHOT_FIELDS[source] if (value := item.get(key)) not in (None, "", [], {})
                },
            }
            for item in safe_items[:_MAX_RECOMMENDATIONS]
        ]
    return None


def _candidate_snapshot_update(result: dict) -> list[dict] | None:
    """Return SET, CLEAR, or UNCHANGED semantics for durable candidate state."""

    snapshot = _presented_candidate_snapshot(result)
    if snapshot is not None:
        return snapshot
    outcome = result.get("search_outcome") or {}
    if result.get("action") == "SEARCH" and outcome.get("status"):
        # A completed newer search with no safe presented candidates invalidates
        # older numbering; [] means CLEAR while None means UNCHANGED.
        return []
    return None


@dataclass
class _PreparedAgentTurn:
    memory: ChatMemoryContext
    candidate_snapshot: list[dict]
    profile: dict
    pending_request: dict
    last_search_plan: dict
    graph: Any
    config: dict
    initial_state: dict
    trace_id: str | None
    tracing_enabled: bool


async def _run_agent(payload: ChatRequest) -> dict:
    # One process must not interleave the read/modify/write cycle for the same
    # session. Different sessions still execute concurrently.
    async with _session_locks.hold(payload.session_id):
        return await _run_agent_locked(payload)


async def _stream_agent(payload: ChatRequest) -> AsyncIterator[dict]:
    """Stream allowlisted graph progress while keeping load → graph → save locked."""

    async with _session_locks.hold(payload.session_id):
        async for event in _stream_agent_locked(payload):
            yield event


async def _enforce_chat_rate_limit(payload: ChatRequest, request: Request) -> None:
    settings = get_settings()
    retry_after = await _chat_rate_limiter.acquire(
        f"session:{payload.session_id}",
        limit=settings.chat_session_rate_limit_per_minute,
    )
    if retry_after is None:
        client_host = request.client.host if request.client else "unknown"
        retry_after = await _chat_rate_limiter.acquire(
            f"ip:{client_host}",
            limit=settings.chat_ip_rate_limit_per_minute,
        )
    if retry_after is not None:
        retry_seconds = max(1, math.ceil(retry_after))
        raise HTTPException(
            status_code=429,
            detail="요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(retry_seconds)},
        )


async def _enforce_feedback_rate_limit(payload: RecommendationFeedbackRequest, request: Request) -> None:
    settings = get_settings()
    retry_after = await _feedback_rate_limiter.acquire(
        f"session:{payload.session_id}",
        limit=settings.feedback_session_rate_limit_per_minute,
    )
    if retry_after is None:
        client_host = request.client.host if request.client else "unknown"
        retry_after = await _feedback_rate_limiter.acquire(
            f"ip:{client_host}",
            limit=settings.feedback_ip_rate_limit_per_minute,
        )
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="피드백 요청이 너무 많아요. 잠시 후 다시 시도해 주세요.",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )


async def _prepare_agent_turn(payload: ChatRequest) -> tuple[_PreparedAgentTurn | None, dict | None]:
    memory = await _chat_memory.load(payload.session_id)
    candidate_snapshot = _sanitize_candidate_snapshot(memory.last_presented_candidates)
    profile = payload.profile_defaults.model_dump(exclude_none=True) if payload.profile_defaults else {}
    if memory.profile:
        # 같은 채팅에서 확인한 조건이 브라우저 기본값보다 우선한다.
        profile.update(_sanitize_legacy_profile(memory.profile))
    profile = _sanitize_legacy_profile(profile)
    pending_request = _sanitize_legacy_pending(memory.pending_request)
    last_search_plan = _sanitize_last_search_plan(memory.last_search_plan)

    detected_sensitive_data = detect_sensitive_data(payload.message)
    if detected_sensitive_data:
        safe_message = redact_sensitive_text(payload.message)
        reply = privacy_guard_reply(detected_sensitive_data)
        await _chat_memory.save_turn(
            session_id=payload.session_id,
            user_message=safe_message,
            assistant_message=reply,
            intent="PRIVACY_BLOCKED",
            profile=profile,
            pending_request=pending_request,
            last_presented_candidates=candidate_snapshot,
            last_search_plan=last_search_plan,
        )
        return None, {
            "intent": "PRIVACY_BLOCKED",
            "action": "RESPOND",
            "response_mode": "out_of_scope",
            "request_kind": "general",
            "final_response": reply,
            "profile": profile,
            "pending_request": pending_request,
            "missing_slots": [],
            "youth_policy_results": [],
            "training_results": [],
            "recruitment_results": [],
            "privacy_blocked": True,
            "last_presented_candidates": candidate_snapshot,
            "last_search_plan": last_search_plan,
        }

    graph = get_agent_graph()
    config: dict = {
        "run_name": "policy-compass-chat",
        "metadata": {"session_id": payload.session_id},
    }
    langfuse_client = get_langfuse_client()
    # 그래프 실행이 끝나면 콜백이 만든 span의 컨텍스트가 닫혀서 사후에는 trace_id를
    # 조회할 수 없다. 그래서 미리 하나 만들어 CallbackHandler에 그대로 주입한다
    # (나중에 사용자 피드백을 이 trace_id로 연결하기 위함).
    trace_id = langfuse_client.create_trace_id() if langfuse_client is not None else None
    langfuse_handler = create_langfuse_handler(trace_id=trace_id)
    if langfuse_handler is not None:
        config["callbacks"] = [langfuse_handler]
    initial_state: dict = {
        **fresh_turn_fields(),
        "session_id": payload.session_id,
        "user_input": payload.message,
    }
    if memory.messages:
        initial_state["conversation_history"] = memory.messages
    if profile:
        initial_state["profile"] = profile
    if pending_request:
        initial_state["pending_request"] = pending_request
    if candidate_snapshot:
        initial_state["last_presented_candidates"] = candidate_snapshot
    if last_search_plan:
        initial_state["last_search_plan"] = last_search_plan

    return (
        _PreparedAgentTurn(
            memory=memory,
            candidate_snapshot=candidate_snapshot,
            profile=profile,
            pending_request=pending_request,
            last_search_plan=last_search_plan,
            graph=graph,
            config=config,
            initial_state=initial_state,
            trace_id=trace_id,
            tracing_enabled=langfuse_handler is not None,
        ),
        None,
    )


def _timeout_result(payload: ChatRequest, prepared: _PreparedAgentTurn) -> dict:
    return {
        **fresh_turn_fields(),
        "session_id": payload.session_id,
        "intent": "GENERAL",
        "action": "RESPOND",
        "response_mode": "general",
        "request_kind": "general",
        "final_response": "처리 시간이 길어져 이번 요청을 안전하게 중단했어요. 잠시 후 다시 시도해 주세요.",
        "profile": prepared.profile,
        "pending_request": prepared.pending_request,
        "conversation_history": prepared.memory.messages,
        "last_presented_candidates": prepared.candidate_snapshot,
        "last_search_plan": prepared.last_search_plan,
        "timed_out": True,
    }


async def _save_agent_result(payload: ChatRequest, prepared: _PreparedAgentTurn, result: dict) -> dict:
    result["trace_id"] = prepared.trace_id if prepared.tracing_enabled else None
    snapshot_update = _candidate_snapshot_update(result)
    search_plan_update = _last_search_plan_update(result)
    await _chat_memory.save_turn(
        session_id=payload.session_id,
        user_message=payload.message,
        assistant_message=result.get("final_response", ""),
        intent=result.get("intent", "GENERAL"),
        profile=_profile_for_memory(result),
        pending_request=_sanitize_legacy_pending(result.get("pending_request") or {}),
        last_presented_candidates=(prepared.candidate_snapshot if snapshot_update is None else snapshot_update),
        last_search_plan=prepared.last_search_plan if search_plan_update is None else search_plan_update,
    )
    return result


async def _run_agent_locked(payload: ChatRequest) -> dict:
    prepared, early_result = await _prepare_agent_turn(payload)
    if early_result is not None:
        return early_result
    if prepared is None:  # pragma: no cover - tuple contract guard
        raise RuntimeError("Agent turn preparation returned no execution context.")

    try:
        async with asyncio.timeout(get_settings().agent_turn_timeout_seconds):
            with langfuse_trace_context(payload.session_id, enabled=prepared.tracing_enabled):
                result = await prepared.graph.ainvoke(prepared.initial_state, config=prepared.config)
    except TimeoutError:
        logger.warning("Agent turn timed out session=%s", payload.session_id)
        result = _timeout_result(payload, prepared)
    return await _save_agent_result(payload, prepared, result)


async def _stream_agent_locked(payload: ChatRequest) -> AsyncIterator[dict]:
    prepared, early_result = await _prepare_agent_turn(payload)
    if early_result is not None:
        yield {"type": "result", "result": early_result}
        return
    if prepared is None:  # pragma: no cover - tuple contract guard
        raise RuntimeError("Agent turn preparation returned no execution context.")

    result: dict | None = None
    current_state = dict(prepared.initial_state)
    try:
        async with asyncio.timeout(get_settings().agent_turn_timeout_seconds):
            with langfuse_trace_context(payload.session_id, enabled=prepared.tracing_enabled):
                async for mode, chunk in prepared.graph.astream(
                    prepared.initial_state,
                    config=prepared.config,
                    stream_mode=["updates", "values"],
                ):
                    if mode == "values" and isinstance(chunk, dict):
                        result = chunk
                        current_state = dict(chunk)
                        continue
                    if mode != "updates" or not isinstance(chunk, dict):
                        continue
                    for node_name, update in chunk.items():
                        if isinstance(update, dict):
                            current_state.update(update)
                        message = _node_status_message(node_name, current_state)
                        if message:
                            yield {
                                "type": "status",
                                "stage": node_name,
                                "message": message,
                            }
    except TimeoutError:
        logger.warning("Agent turn timed out session=%s", payload.session_id)
        result = _timeout_result(payload, prepared)
        yield {
            "type": "status",
            "stage": "timeout",
            "message": _result_status_message(result),
        }

    if result is None:
        raise RuntimeError("Agent graph stream completed without a final state.")
    result = await _save_agent_result(payload, prepared, result)
    yield {"type": "result", "result": result}


@router.post("", response_model=ChatTurnResponse)
async def chat(payload: ChatRequest, request: Request) -> ChatTurnResponse:
    await _enforce_chat_rate_limit(payload, request)
    result = await _run_agent(payload)
    return ChatTurnResponse(
        session_id=payload.session_id,
        intent=result.get("intent", "GENERAL"),
        reply=result.get("final_response", ""),
        profile=UserProfile(**(result.get("profile") or {})),
        missing_slots=result.get("missing_slots", []),
        recommendations=_build_recommendations(result),
        trace_id=result.get("trace_id"),
    )


@router.post("/stream")
async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
    await _enforce_chat_rate_limit(payload, request)

    async def event_generator():
        status_event = {
            "type": "status",
            "stage": "accepted",
            "message": "질문 의도와 필요한 정보를 확인하고 있어요.",
        }
        yield f"event: status\ndata: {json.dumps(status_event, ensure_ascii=False)}\n\n"

        result: dict | None = None
        saw_node_status = False
        try:
            async for agent_event in _stream_agent(payload):
                if agent_event.get("type") == "status":
                    saw_node_status = True
                    yield f"event: status\ndata: {json.dumps(agent_event, ensure_ascii=False)}\n\n"
                elif agent_event.get("type") == "result":
                    result = agent_event.get("result")
        except Exception:  # noqa: BLE001 - 스트림 중 에러도 SSE로 전달
            logger.exception("Agent 실행 중 오류가 발생했습니다.")
            error_event = {
                "type": "error",
                "message": "일시적인 오류가 발생했어요. 잠시 후 다시 시도해주세요.",
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        if result is None:
            error_event = {
                "type": "error",
                "message": "답변을 만들지 못했어요. 조건을 조금 더 구체적으로 입력해 다시 시도해주세요.",
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        # Privacy-blocked requests deliberately skip LangGraph and therefore
        # have no node event. Preserve a specific status for that safe path.
        if not saw_node_status:
            routed_status_event = {
                "type": "status",
                "stage": "complete",
                "message": _result_status_message(result),
            }
            yield f"event: status\ndata: {json.dumps(routed_status_event, ensure_ascii=False)}\n\n"

        reply = result.get("final_response", "")
        if not reply:
            error_event = {
                "type": "error",
                "message": "답변을 만들지 못했어요. 조건을 조금 더 구체적으로 입력해 다시 시도해주세요.",
            }
            yield f"event: error\ndata: {json.dumps(error_event, ensure_ascii=False)}\n\n"
            return

        for i in range(0, len(reply), _STREAM_CHUNK_SIZE):
            chunk = {"type": "token", "content": reply[i : i + _STREAM_CHUNK_SIZE]}
            yield f"event: token\ndata: {json.dumps(chunk, ensure_ascii=False)}\n\n"

        done_payload = {
            "type": "done",
            "intent": result.get("intent", "GENERAL"),
            "missing_slots": result.get("missing_slots", []),
            "recommendations": _build_recommendations(result),
            # Explicit nulls are CLEAR operations. Omitting them would let the
            # browser merge a value the user just asked the agent to forget.
            "profile_defaults": {key: (result.get("profile") or {}).get(key) for key in ("age", "region")},
            "trace_id": result.get("trace_id"),
        }
        yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/feedback")
async def submit_recommendation_feedback(
    payload: RecommendationFeedbackRequest,
    request: Request,
) -> dict[str, bool]:
    await _enforce_feedback_rate_limit(payload, request)
    saved = await _feedback_repo.save(
        session_id=payload.session_id,
        message_id=payload.message_id,
        trace_id=payload.trace_id,
        rating=payload.rating,
    )

    if saved and payload.trace_id:
        client = get_langfuse_client()
        if client is not None:
            try:
                client.create_score(
                    trace_id=payload.trace_id,
                    name="user-thumbs",
                    value=1 if payload.rating == "up" else 0,
                    data_type="BOOLEAN",
                )
            except Exception:  # noqa: BLE001 - observability must not break the API
                logger.exception("Langfuse 피드백 score 저장 실패")

    return {"saved": saved}

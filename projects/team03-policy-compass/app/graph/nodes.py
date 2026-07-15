"""LangGraph 노드 구현.

각 노드는 가능하면 Upstage Solar LLM을 사용하고, API 키가 없거나 호출이
실패하면 규칙 기반 휴리스틱으로 안전하게 폴백한다 (LLM 미설정 상태에서도
데모/테스트가 항상 동작하도록 하기 위함).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from pydantic import ValidationError

from app.core.config import get_settings
from app.core.llm import LLMUnavailableError, SolarLLMClient, extract_json
from app.core.prompts import (
    MISSING_SLOT_LABELS,
    PROFILE_EXTRACTION_SYSTEM_PROMPT,
    ROUTER_SYSTEM_PROMPT,
)
from app.core.regions import resolve_region, user_region_reference
from app.graph.contracts import VALID_REQUEST_KINDS, RoutingDecision
from app.graph.evidence import assess_search_outcome
from app.graph.fallbacks import (
    classify_request_kind as _classify_request_kind,
)
from app.graph.fallbacks import (
    extract_training_search_keyword as _extract_training_search_keyword,
)
from app.graph.fallbacks import (
    has_supported_domain,
    is_brief_social_message,
    is_pending_cancel,
    is_region_unrestricted_request,
    pending_answer_fills_required_slot,
    source_selection_plan,
)
from app.graph.fallbacks import (
    heuristic_extract_profile as _heuristic_extract_profile,
)
from app.graph.fallbacks import (
    heuristic_route as _heuristic_route,  # noqa: F401 - fallback 테스트 호환용 재노출
)
from app.graph.fallbacks import routing_plan as _fallback_routing_plan
from app.graph.profile_contracts import apply_profile_delta, requested_profile_clears, sanitize_profile
from app.graph.response_composer import (
    clarification_template,
    clean_response_text,
    compose_card_summary_reply,
    compose_clarification_reply,
    compose_conversation_fallback,
    compose_conversation_reply,
    compose_grounded_response,
    compose_recent_candidate_followup,
    compose_search_status_reply,
    compose_search_status_response,
    references_recent_candidates,
)
from app.graph.search_contracts import (
    SearchOutcome,
    SearchSource,
    SearchStatus,
    outcome_from_raw,
    unavailable_outcome,
)
from app.graph.state import AgentState, fresh_turn_fields
from app.graph.validators import validate_response_state, validate_route_state
from app.repositories.supabase_fallback import (
    SupabaseRecruitmentInfoFallback,
    SupabaseTrainingCourseFallback,
    SupabaseYouthPolicyFallback,
)
from app.repositories.work24_recruitment import Work24RecruitmentRepository
from app.repositories.work24_training import Work24TrainingRepository, work24_training_area_code
from app.repositories.youthcenter import YouthCenterRepository, is_generic_youth_policy_query
from app.tools.executor import (
    RecruitmentInfoTool,
    TrainingCourseSearchTool,
    YouthPolicySearchTool,
)
from app.tools.schemas import (
    RecruitmentInfoSearchInput,
    TrainingCourseSearchInput,
    YouthPolicySearchInput,
)

logger = logging.getLogger(__name__)

_llm = SolarLLMClient()
_youth_policy_tool = YouthPolicySearchTool(YouthCenterRepository(SupabaseYouthPolicyFallback()))
_training_tool = TrainingCourseSearchTool(Work24TrainingRepository(SupabaseTrainingCourseFallback()))
_recruitment_tool = RecruitmentInfoTool(Work24RecruitmentRepository(SupabaseRecruitmentInfoFallback()))

_QUERY_REWRITES = {
    "데이터 분석": "데이터",
    "클라우드 엔지니어": "클라우드",
    "소프트웨어 개발": "개발",
    "인공지능": "AI",
    "UX/UI 디자인": "디자인",
}

# ---------------------------------------------------------------------------
# Router Node
# ---------------------------------------------------------------------------


async def router_node(state: AgentState) -> dict[str, Any]:
    user_input = state["user_input"]
    pending = state.get("pending_request") or {}
    last_search_plan = state.get("last_search_plan") or {}
    discarded_legacy_pending = pending.get("request_kind") == "business"
    if discarded_legacy_pending:
        pending = {}
    turn_fields = fresh_turn_fields()
    pending_filled = bool(pending) and pending_answer_fills_required_slot(user_input, pending)
    action = None
    response_mode = None
    intent = None
    request_kind = None
    search_query = None
    routing_source = "heuristic"
    resumed_pending = False
    resume_requested = False
    pending_action = "NONE"

    if pending and is_pending_cancel(user_input):
        return {
            **turn_fields,
            "intent": "GENERAL",
            "action": "RESPOND",
            "response_mode": "general",
            "request_kind": "general",
            "search_query": None,
            "routing_source": "pending_transition",
            "resumed_pending": False,
            "pending_action": "CANCEL",
            "pending_request": {},
            "turn_relation": "CANCEL",
        }

    if is_region_unrestricted_request(user_input):
        legacy_profile = state.get("profile") or {}
        followup_plan = (
            pending
            or last_search_plan
            or {
                "request_kind": state.get("request_kind") or legacy_profile.get("request_kind"),
                "response_mode": state.get("response_mode", "recommend"),
                "search_query": state.get("search_query") or legacy_profile.get("desired_job"),
            }
        )
        followup_kind = followup_plan.get("request_kind")
        if followup_kind in VALID_REQUEST_KINDS - {"general"}:
            followup_mode = followup_plan.get("response_mode", "recommend")
            return {
                **turn_fields,
                "intent": {
                    "recommend": "RECOMMEND",
                    "eligibility": "ELIGIBILITY_CHECK",
                    "explain": "EXPLAIN",
                }.get(followup_mode, "RECOMMEND"),
                "action": "SEARCH",
                "response_mode": followup_mode,
                "request_kind": followup_kind,
                "search_query": followup_plan.get("search_query"),
                "routing_source": "deterministic_followup",
                "resumed_pending": bool(pending),
                "pending_action": "RESUME" if pending else "NONE",
                "turn_relation": "RESUME" if pending else "REFINE",
                "region_filter_mode": "any",
            }

    if state.get("last_presented_candidates") and references_recent_candidates(user_input):
        return {
            **turn_fields,
            "intent": "EXPLAIN",
            "action": "RESPOND",
            "response_mode": "explain",
            "request_kind": "general",
            "search_query": None,
            "routing_source": "candidate_reference",
            "resumed_pending": False,
            "pending_action": "KEEP" if pending else "NONE",
            "turn_relation": "FOLLOW_UP",
        }

    if references_recent_candidates(user_input):
        return {
            **turn_fields,
            "intent": "GENERAL",
            "action": "RESPOND",
            "response_mode": "general",
            "request_kind": "general",
            "search_query": None,
            "routing_source": "candidate_reference_missing",
            "resumed_pending": False,
            "pending_action": "KEEP" if pending else "NONE",
            "turn_relation": "FOLLOW_UP",
        }

    snapshot_candidates = state.get("last_presented_candidates") or []
    previous_snapshot = (
        snapshot_candidates[0] if snapshot_candidates and isinstance(snapshot_candidates[0], dict) else {}
    )
    previous_request_kind = (
        last_search_plan.get("request_kind")
        or state.get("request_kind")
        or previous_snapshot.get("source")
        or (state.get("profile") or {}).get("request_kind")
    )
    previous_search_query = (
        last_search_plan.get("search_query") or state.get("search_query") or previous_snapshot.get("search_query")
    )
    is_completed_search_region_correction = bool(
        not pending
        and re.search(r"말고|아니라|아니고|대신", user_input)
        and user_region_reference(user_input)
        and previous_request_kind in VALID_REQUEST_KINDS - {"general"}
    )
    if is_completed_search_region_correction:
        previous_mode = state.get("response_mode", "recommend")
        return {
            **turn_fields,
            "intent": {
                "recommend": "RECOMMEND",
                "eligibility": "ELIGIBILITY_CHECK",
                "explain": "EXPLAIN",
            }.get(previous_mode, "RECOMMEND"),
            "action": "SEARCH",
            "response_mode": previous_mode,
            "request_kind": previous_request_kind,
            "search_query": previous_search_query,
            "routing_source": "deterministic_followup",
            "resumed_pending": False,
            "pending_action": "NONE",
            "turn_relation": "REFINE",
            "region_filter_mode": "specific",
        }

    deterministic_plan = _fallback_routing_plan(user_input, state.get("profile"))

    if _llm.is_configured:
        try:
            routing_context = {
                "message": user_input,
                "known_profile": state.get("profile") or {},
                "recent_history": (state.get("conversation_history") or [])[-6:],
                "pending_request": pending,
            }
            raw = await _llm.complete(
                [
                    {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(routing_context, ensure_ascii=False)},
                ],
                response_format_json=True,
                operation_name="router",
            )
            decision = RoutingDecision.model_validate(extract_json(raw))
            action = decision.action.value
            response_mode = decision.response_mode.value
            intent = decision.intent.value
            request_kind = decision.request_kind.value
            search_query = decision.search_query
            resume_requested = decision.resume_pending and bool(pending)
            if resume_requested and not pending_filled:
                fallback = _fallback_routing_plan(user_input, state.get("profile"))
                action = fallback["action"]
                response_mode = fallback["response_mode"]
                intent = fallback["intent"]
                request_kind = fallback["request_kind"]
                search_query = fallback["search_query"]
                routing_source = "pending_validation_fallback"
                resume_requested = False
            if request_kind == "youth_policy" and is_generic_youth_policy_query(user_input):
                search_query = None
            if routing_source != "pending_validation_fallback":
                routing_source = "llm"
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 라우터 휴리스틱을 사용합니다.")
        except ValidationError as exc:
            logger.warning("라우터 LLM 응답 계약 검증 실패, 휴리스틱으로 폴백합니다: %s", exc.errors())
        except Exception:  # noqa: BLE001 - LLM 실패 시 휴리스틱으로 안전하게 폴백
            logger.exception("라우터 LLM 호출 실패, 휴리스틱으로 폴백합니다.")

    if action is None:
        fallback = _fallback_routing_plan(user_input, state.get("profile"))
        action = fallback["action"]
        response_mode = fallback["response_mode"]
        intent = fallback["intent"]
        request_kind = fallback["request_kind"]
        search_query = fallback["search_query"]
        routing_source = "heuristic"

    llm_scope_misclassification = bool(
        routing_source == "llm" and action == "RESPOND" and response_mode in {"general", "out_of_scope"}
    )
    should_resume_general_answer = action == "RESPOND" and response_mode == "general"
    deterministic_slot_answer = pending_filled and deterministic_plan.get("response_mode") == "general"
    if pending and pending_filled and (resume_requested or should_resume_general_answer or deterministic_slot_answer):
        guarded_pending_resume = not resume_requested or llm_scope_misclassification
        action = "SEARCH"
        response_mode = pending.get("response_mode", response_mode)
        intent = {
            "recommend": "RECOMMEND",
            "eligibility": "ELIGIBILITY_CHECK",
            "explain": "EXPLAIN",
        }.get(response_mode, intent)
        request_kind = pending.get("request_kind", request_kind)
        search_query = pending.get("search_query") or search_query
        resumed_pending = True
        pending_action = "RESUME"
        if guarded_pending_resume:
            routing_source = "pending_slot_guard"
    elif pending and action == "SEARCH":
        # A new search replaces the previous incomplete plan.  Clearing it here
        # prevents policy_search_node from borrowing the old query/request text.
        pending_action = "REPLACE"
    elif pending:
        pending_action = "KEEP"

    logger.info(
        "routing_decision source=%s action=%s mode=%s request_kind=%s has_search_query=%s",
        routing_source,
        action,
        response_mode,
        request_kind,
        bool(search_query),
    )

    result = {
        **turn_fields,
        "intent": intent,
        "action": action,
        "response_mode": response_mode,
        "request_kind": request_kind,
        "search_query": search_query,
        "routing_source": routing_source,
        "resumed_pending": resumed_pending,
        "pending_action": pending_action,
        "turn_relation": (
            "RESUME"
            if resumed_pending
            else "REPLACE"
            if action == "SEARCH"
            and (
                pending_action == "REPLACE"
                or (
                    previous_request_kind in VALID_REQUEST_KINDS - {"general"} and previous_request_kind != request_kind
                )
            )
            else "NEW"
        ),
    }
    if pending_action == "REPLACE":
        result["pending_request"] = {}
    elif discarded_legacy_pending:
        result["pending_action"] = "CANCEL"
        result["pending_request"] = {}
    return result


async def route_validator_node(state: AgentState) -> dict[str, Any]:
    """Verify both the route contract and high-confidence semantic invariants.

    The LLM may return structurally valid JSON while still classifying an
    explicit lookup as a general response (or the inverse while a clarification
    is pending). Only action-level contradictions and explicit source markers
    are overridden here; ambiguous choices remain with the validated LLM route.
    """

    errors = validate_route_state(state)
    fallback = _fallback_routing_plan(state.get("user_input", ""), state.get("profile"))
    source_plan = source_selection_plan(state.get("user_input", ""), state.get("profile"))
    validation_source = "route_validation_fallback"

    if not errors and state.get("routing_source") == "llm":
        current_action = state.get("action")
        fallback_action = fallback["action"]
        pending = state.get("pending_request") or {}
        pending_slot_answer = bool(pending) and pending_answer_fills_required_slot(state.get("user_input", ""), pending)

        if fallback_action == "SEARCH" and current_action == "RESPOND":
            errors = ["explicit_search_request_misclassified"]
            validation_source = "semantic_guard"
        elif (
            fallback_action == "SEARCH"
            and current_action == "SEARCH"
            and source_plan.get("source_is_explicit")
            and state.get("request_kind") != source_plan.get("primary_source")
        ):
            errors = ["explicit_source_misclassified"]
            validation_source = "semantic_guard"
        elif (
            is_brief_social_message(state.get("user_input", ""))
            and current_action == "SEARCH"
            and not pending_slot_answer
        ):
            errors = ["non_search_request_misclassified"]
            validation_source = "semantic_guard"
        elif fallback.get("response_mode") == "out_of_scope" and current_action == "SEARCH" and not pending_slot_answer:
            errors = ["non_search_request_misclassified"]
            validation_source = "semantic_guard"
        elif (
            is_brief_social_message(state.get("user_input", ""))
            and current_action == "RESPOND"
            and state.get("response_mode") == "out_of_scope"
        ):
            errors = ["brief_social_misclassified"]
            validation_source = "semantic_guard"
        elif (
            fallback.get("response_mode") == "out_of_scope"
            and current_action == "RESPOND"
            and state.get("response_mode") == "general"
        ):
            errors = ["explicit_out_of_scope_misclassified"]
            validation_source = "semantic_guard"

    if not errors:
        return {"route_validation_status": "passed", "route_validation_errors": []}

    logger.warning("경로 2차 검증 실패로 안전한 fallback을 사용합니다: %s", errors)
    pending = state.get("pending_request") or {}
    pending_action = "NONE"
    if pending:
        pending_action = "REPLACE" if fallback.get("action") == "SEARCH" else "KEEP"

    result: dict[str, Any] = {
        **fallback,
        "routing_source": validation_source,
        "resumed_pending": False,
        "pending_action": pending_action,
        "route_validation_status": "revised",
        "route_validation_errors": errors,
    }
    previous_kind = (state.get("last_search_plan") or {}).get("request_kind")
    if (
        fallback.get("action") == "SEARCH"
        and previous_kind in VALID_REQUEST_KINDS - {"general"}
        and previous_kind != fallback.get("request_kind")
    ):
        result["turn_relation"] = "REPLACE"
    if pending_action == "REPLACE":
        result["pending_request"] = {}
    elif pending_action == "KEEP":
        result["pending_request"] = pending
    return {
        **result,
    }


async def prepare_request_node(state: AgentState) -> dict[str, Any]:
    """Create one validated request plan instead of exposing bookkeeping nodes."""

    updates: dict[str, Any] = {}
    working: AgentState = dict(state)
    original_pending_request = dict(working.get("pending_request") or {})

    # Profile deletion is a deterministic state transition and must work even
    # when the current turn is routed to a fixed RESPOND path (no extractor).
    clear_fields = requested_profile_clears(state.get("user_input", ""))
    if clear_fields:
        cleared_profile = apply_profile_delta(state.get("profile") or {}, {}, clear_fields)
        updates["profile"] = cleared_profile
        working["profile"] = cleared_profile

    routed = await router_node(working)
    updates.update(routed)
    working.update(routed)
    # A tentative LLM SEARCH route can mark the old pending plan for
    # replacement.  Keep the original visible to the route validator until
    # that route has passed semantic checks; otherwise a misclassified greeting
    # would be corrected to RESPOND only after the pending task was erased.
    if routed.get("pending_action") == "REPLACE" and original_pending_request:
        working["pending_request"] = original_pending_request

    validated = await route_validator_node(working)
    updates.update(validated)
    working.update(validated)

    if working.get("action") != "SEARCH":
        if working.get("response_mode") == "general" and has_supported_domain(state.get("user_input", "")):
            passive_fields = {"age", "region", "employment_status"}
            passive_delta = {
                key: value
                for key, value in _heuristic_extract_profile(state.get("user_input", "")).items()
                if key in passive_fields
            }
            if passive_delta:
                passive_profile = apply_profile_delta(working.get("profile") or {}, passive_delta)
                updates["profile"] = passive_profile
                working["profile"] = passive_profile
        updates["direct_response_reason"] = working.get("response_mode") or "general"
        return updates

    extracted = await profile_extractor_node(working)
    updates.update(extracted)
    working.update(extracted)

    effective_filters = _derive_effective_filters(working)
    updates["effective_filters"] = effective_filters
    working["effective_filters"] = effective_filters

    slot_check = await missing_slot_node(working)
    updates.update(slot_check)
    if slot_check.get("missing_slots"):
        updates["direct_response_reason"] = "missing_slots"
    return updates


# ---------------------------------------------------------------------------
# Profile Extractor Node
# ---------------------------------------------------------------------------


async def profile_extractor_node(state: AgentState) -> dict[str, Any]:
    user_input = state["user_input"]
    previous_profile = sanitize_profile(state.get("profile") or {})

    extracted: dict[str, Any] = {}
    if _llm.is_configured:
        try:
            extraction_context = {
                "message": user_input,
                "known_profile": previous_profile,
                "recent_history": (state.get("conversation_history") or [])[-6:],
                "pending_request": state.get("pending_request") or {},
            }
            raw = await _llm.complete(
                [
                    {"role": "system", "content": PROFILE_EXTRACTION_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(extraction_context, ensure_ascii=False)},
                ],
                response_format_json=True,
                operation_name="profile-extraction",
            )
            raw_extracted = extract_json(raw)
            extracted = raw_extracted if isinstance(raw_extracted, dict) else {}
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 프로필 추출 휴리스틱을 사용합니다.")
        except Exception:  # noqa: BLE001
            logger.exception("프로필 추출 LLM 호출 실패, 휴리스틱으로 폴백합니다.")

    if not extracted:
        extracted = _heuristic_extract_profile(user_input)

    # 지역은 LLM이 known_profile이나 상식으로 시·도를 보완하지 못하게 현재 발화의
    # 공식 행정구역 표현만 다시 읽어 덮어쓴다. 모호한 고성군·중구는 그대로 남겨
    # Missing Slot 단계가 시·도 확인 질문을 하도록 한다.
    explicit_region = user_region_reference(user_input)
    if explicit_region:
        extracted["region"] = explicit_region
    else:
        extracted.pop("region", None)

    broad_policy_request = is_generic_youth_policy_query(user_input)
    if broad_policy_request:
        extracted.pop("policy_topic", None)

    merged = apply_profile_delta(
        previous_profile,
        extracted,
        requested_profile_clears(user_input),
    )
    if broad_policy_request:
        merged.pop("policy_topic", None)

    request_kind = state.get("request_kind")
    if request_kind not in VALID_REQUEST_KINDS or request_kind == "general":
        request_kind = _classify_request_kind(user_input, merged)
    merged["request_kind"] = request_kind

    return {
        "profile": merged,
        "profile_delta": sanitize_profile(extracted),
        "request_kind": request_kind,
    }


def _derive_effective_filters(state: AgentState) -> dict[str, Any]:
    """Project durable facts into source-specific filters for this turn only."""

    request_kind = state.get("request_kind", "youth_policy")
    profile = state.get("profile") or {}
    delta = state.get("profile_delta") or {}
    last_plan = state.get("last_search_plan") or {}
    last_filters = last_plan.get("effective_filters") or {}
    relation = state.get("turn_relation", "NEW")
    region_mode = state.get("region_filter_mode", "specific")

    filters: dict[str, Any] = {"region_mode": region_mode}
    if request_kind == "youth_policy":
        if region_mode != "any" and profile.get("region"):
            filters["residence_region"] = profile["region"]
        for key in ("age", "employment_status", "policy_topic", "preferred_support_type"):
            if profile.get(key) not in (None, "", [], {}):
                filters[key] = profile[key]
        return filters

    region_key = "training_region" if request_kind == "training" else "work_region"
    if region_mode != "any":
        if delta.get("region"):
            filters[region_key] = delta["region"]
        elif relation in {"REFINE", "RESUME"} and last_plan.get("request_kind") == request_kind:
            prior_region = last_filters.get(region_key) or last_filters.get("region")
            if prior_region:
                filters[region_key] = prior_region
        elif state.get("resumed_pending") and profile.get("region"):
            filters[region_key] = profile["region"]

    search_query = state.get("search_query")
    if not search_query and relation == "REFINE" and last_plan.get("request_kind") == request_kind:
        search_query = last_plan.get("search_query")
    if not search_query and delta.get("desired_job"):
        search_query = delta["desired_job"]
    if not search_query and delta.get("interest_fields"):
        search_query = " ".join(delta["interest_fields"])
    if not search_query and relation != "REPLACE" and (not last_plan or last_plan.get("request_kind") == request_kind):
        search_query = profile.get("desired_job") or " ".join(profile.get("interest_fields") or []) or None
    if search_query:
        filters["search_query"] = search_query

    if request_kind == "recruitment":
        career_markers = [marker for marker in ("신입", "인턴") if marker in state.get("user_input", "")]
        if len(career_markers) == 1:
            filters["career_level"] = career_markers[0]
    return filters


# ---------------------------------------------------------------------------
# Missing Slot Node
# ---------------------------------------------------------------------------


async def missing_slot_node(state: AgentState) -> dict[str, Any]:
    profile = state.get("profile") or {}
    effective_filters = state.get("effective_filters") or _derive_effective_filters(state)
    request_kind = state.get("request_kind") or profile.get("request_kind") or "youth_policy"
    missing: list[str] = []

    topic_listing_explanation = request_kind == "youth_policy" and bool(profile.get("policy_topic"))
    if state.get("response_mode") == "explain" and not topic_listing_explanation:
        return {"missing_slots": []}

    region = {
        "training": effective_filters.get("training_region"),
        "recruitment": effective_filters.get("work_region"),
    }.get(request_kind, effective_filters.get("residence_region") or profile.get("region"))
    region_is_any = effective_filters.get("region_mode") == "any"
    unresolved_region = bool(region and resolve_region(region) is None)

    if request_kind == "training":
        if not effective_filters.get("search_query"):
            missing.append("desired_job")
        if not region and not region_is_any:
            missing.append("training_region")
        elif unresolved_region:
            missing.append("region_detail")
    elif request_kind == "recruitment":
        # Work24's connected recruitment sources can be browsed without a
        # job/region filter. Those fields improve precision but are not gates.
        if unresolved_region:
            missing.append("region_detail")
    else:
        if not region and not region_is_any:
            missing.append("region")
        elif unresolved_region:
            missing.append("region_detail")
        if profile.get("age") is None:
            missing.append("age")
        policy_topic = profile.get("policy_topic")
        has_specific_query = bool(
            state.get("search_query") and not is_generic_youth_policy_query(state.get("search_query"))
        )
        if (
            not policy_topic
            and not has_specific_query
            and not profile.get("preferred_support_type")
            and not profile.get("interest_fields")
        ):
            missing.append("policy_topic")
        if policy_topic == "일자리" and profile.get("employment_status") is None:
            missing.append("employment_status")

    return {"missing_slots": missing}


async def clarification_node(state: AgentState) -> dict[str, Any]:
    missing = state.get("missing_slots", [])
    existing = state.get("pending_request") or {}
    if state.get("resumed_pending") and existing:
        pending = dict(existing)
    else:
        pending = {
            "original_request": state.get("user_input", ""),
            "request_kind": state.get("request_kind", "youth_policy"),
            "response_mode": state.get("response_mode", "recommend"),
            "search_query": state.get("search_query"),
        }
    next_query = state.get("search_query")
    policy_topic = (state.get("profile") or {}).get("policy_topic")
    if policy_topic and is_generic_youth_policy_query(next_query):
        next_query = policy_topic
    if next_query:
        pending["search_query"] = next_query
    pending["required_slots"] = list(missing)
    labels = [MISSING_SLOT_LABELS.get(slot, slot) for slot in missing]
    question = await compose_clarification_reply(
        _llm,
        original_request=pending.get("original_request") or state.get("user_input", ""),
        profile=state.get("profile") or {},
        labels=labels,
        history=state.get("conversation_history") or [],
        validation_errors=state.get("response_validation_errors") or [],
        previous_response=state.get("final_response"),
    )
    return {
        "final_response": question,
        "pending_request": pending,
        "youth_policy_results": [],
        "training_results": [],
        "recruitment_results": [],
    }


# ---------------------------------------------------------------------------
# Policy Search Node
# ---------------------------------------------------------------------------


async def _execute_search_outcome(
    tool: Any,
    payload: Any,
    *,
    source: SearchSource,
    applied_filters: dict[str, Any],
) -> SearchOutcome:
    """Use the typed Tool contract while keeping small test fakes compatible."""

    try:
        async with asyncio.timeout(get_settings().source_search_timeout_seconds):
            if execute_outcome := getattr(tool, "execute_outcome", None):
                outcome = await execute_outcome(payload)
            else:
                raw_results = await tool.execute(payload)
                outcome = outcome_from_raw(source, raw_results)
    except TimeoutError:
        logger.warning("source_search_timeout source=%s", source.value)
        outcome = unavailable_outcome(
            source,
            "공식 데이터 소스의 응답 시간이 초과되어 현재 결과를 확인하지 못했어요.",
        )
    return outcome.model_copy(
        update={
            "applied_filters": {
                **outcome.applied_filters,
                **{key: value for key, value in applied_filters.items() if value not in (None, "", [], {})},
            }
        }
    )


async def policy_search_node(state: AgentState) -> dict[str, Any]:
    profile = state.get("profile") or {}
    effective_filters = state.get("effective_filters") or _derive_effective_filters(state)
    request_kind = state.get("request_kind") or profile.get("request_kind") or "youth_policy"
    pending = (state.get("pending_request") or {}) if state.get("resumed_pending") else {}
    existing_context = state.get("search_context") or {}
    state_query = state.get("search_query")
    pending_query = pending.get("search_query")
    if request_kind == "youth_policy":
        if state_query and not is_generic_youth_policy_query(state_query):
            planned_query = state_query
        elif profile.get("policy_topic"):
            planned_query = profile["policy_topic"]
        elif pending_query and not is_generic_youth_policy_query(pending_query):
            planned_query = pending_query
        else:
            planned_query = state_query or pending_query
    else:
        planned_query = state_query or pending_query
    original_request = (
        pending.get("original_request") or existing_context.get("original_request") or state["user_input"]
    )
    search_context = {
        "original_request": original_request,
        "search_query": planned_query,
        "request_kind": request_kind,
        "effective_filters": effective_filters,
    }
    search_attempt_count = int(state.get("search_attempt_count") or 0) + 1

    if request_kind == "training":
        desired_job = (
            effective_filters.get("search_query")
            or planned_query
            or _extract_training_search_keyword(state["user_input"])
            or state["user_input"]
        )
        search_context["search_query"] = desired_job
        training_input = TrainingCourseSearchInput(
            desired_job=desired_job[:100],
            training_region=effective_filters.get("training_region"),
            keywords=original_request[:200],
        )
        area_code = work24_training_area_code(training_input.training_region)
        outcome = await _execute_search_outcome(
            _training_tool,
            training_input,
            source=SearchSource.TRAINING,
            applied_filters={
                "training_region": training_input.training_region,
                "training_region_code": area_code,
                "training_keyword": desired_job,
            },
        )
        return {
            "youth_policy_results": [],
            "training_results": outcome.items,
            "recruitment_results": [],
            "pending_request": {},
            "search_context": search_context,
            "search_outcome": outcome.model_dump(mode="json"),
            "search_attempt_count": search_attempt_count,
        }

    if request_kind == "recruitment":
        recruitment_query = effective_filters.get("search_query") or planned_query
        career_level = effective_filters.get("career_level")
        search_context["search_query"] = recruitment_query
        recruitment_input = RecruitmentInfoSearchInput(
            desired_job=recruitment_query,
            preferred_work_region=effective_filters.get("work_region"),
            career_level=career_level,
            # Do not send conversational correction text (for example
            # "청년정책 말고 고용24 공고") as an upstream keyword.
            keywords=(recruitment_query or "")[:200],
        )
        outcome = await _execute_search_outcome(
            _recruitment_tool,
            recruitment_input,
            source=SearchSource.RECRUITMENT,
            applied_filters={
                "keyword": recruitment_input.desired_job or recruitment_input.keywords,
                "work_region": recruitment_input.preferred_work_region,
                "career_level": career_level,
            },
        )
        return {
            "youth_policy_results": [],
            "training_results": [],
            "recruitment_results": outcome.items,
            "pending_request": {},
            "search_context": search_context,
            "search_outcome": outcome.model_dump(mode="json"),
            "search_attempt_count": search_attempt_count,
        }

    youth_input = YouthPolicySearchInput(
        region=effective_filters.get("residence_region"),
        age=effective_filters.get("age"),
        employment_status=effective_filters.get("employment_status"),
        support_types=[
            value
            for value in (
                effective_filters.get("policy_topic"),
                effective_filters.get("preferred_support_type"),
            )
            if value
        ],
        interest_fields=profile.get("interest_fields", []),
        keywords=(planned_query or original_request)[:200],
    )
    outcome = await _execute_search_outcome(
        _youth_policy_tool,
        youth_input,
        source=SearchSource.YOUTH_POLICY,
        applied_filters={
            "region": youth_input.region,
            "active_only": True,
            "policy_keyword": youth_input.keywords,
        },
    )
    return {
        "youth_policy_results": outcome.items,
        "training_results": [],
        "recruitment_results": [],
        "pending_request": {},
        "search_context": search_context,
        "search_outcome": outcome.model_dump(mode="json"),
        "search_attempt_count": search_attempt_count,
    }


async def evidence_assessment_node(state: AgentState) -> dict[str, Any]:
    """Apply the common no-score gate before candidates reach generation/UI."""

    raw_outcome = state.get("search_outcome") or {}
    if not raw_outcome:
        source = {
            "training": SearchSource.TRAINING,
            "recruitment": SearchSource.RECRUITMENT,
        }.get(state.get("request_kind"), SearchSource.YOUTH_POLICY)
        legacy_items = {
            SearchSource.YOUTH_POLICY: state.get("youth_policy_results") or [],
            SearchSource.TRAINING: state.get("training_results") or [],
            SearchSource.RECRUITMENT: state.get("recruitment_results") or [],
        }[source]
        outcome = outcome_from_raw(source, legacy_items)
    else:
        outcome = SearchOutcome.model_validate(raw_outcome)

    gate_profile = dict(state.get("profile") or {})
    effective_filters = (
        state.get("effective_filters")
        or (state.get("search_context") or {}).get("effective_filters")
        or _derive_effective_filters(state)
    )
    requested_region = {
        "training": effective_filters.get("training_region"),
        "recruitment": effective_filters.get("work_region"),
    }.get(state.get("request_kind"), effective_filters.get("residence_region"))
    if requested_region:
        gate_profile["region"] = requested_region
    else:
        gate_profile.pop("region", None)

    assessed, assessment = assess_search_outcome(
        outcome,
        profile=gate_profile,
        search_query=(state.get("search_context") or {}).get("search_query") or state.get("search_query"),
    )
    items_by_source = {
        SearchSource.YOUTH_POLICY: (assessed.items, [], []),
        SearchSource.TRAINING: ([], assessed.items, []),
        SearchSource.RECRUITMENT: ([], [], assessed.items),
    }
    youth, training, recruitment = items_by_source[assessed.source]
    return {
        "search_outcome": assessed.model_dump(mode="json"),
        "evidence_assessment": assessment,
        "youth_policy_results": youth,
        "training_results": training,
        "recruitment_results": recruitment,
    }


def rewritten_search_query(state: AgentState) -> str | None:
    """Return the only allowed deterministic rewrite without relaxing hard filters."""

    if state.get("request_kind") == "youth_policy":
        return None
    current = (state.get("search_context") or {}).get("search_query") or state.get("search_query")
    if not isinstance(current, str):
        return None
    normalized = " ".join(current.split())
    return _QUERY_REWRITES.get(normalized)


async def rewrite_query_node(state: AgentState) -> dict[str, Any]:
    rewritten = rewritten_search_query(state)
    context = dict(state.get("search_context") or {})
    effective_filters = dict(state.get("effective_filters") or {})
    if rewritten:
        context["search_query"] = rewritten
        effective_filters["search_query"] = rewritten
    return {
        "search_query": rewritten or state.get("search_query"),
        "search_context": context,
        "effective_filters": effective_filters,
        "query_rewrite_count": int(state.get("query_rewrite_count") or 0) + 1,
        "search_outcome": {},
        "evidence_assessment": {},
    }


# ---------------------------------------------------------------------------
# Response Node
# ---------------------------------------------------------------------------


def _companion_sources_for_state(state: AgentState) -> list[str]:
    context = state.get("search_context") or {}
    original_request = context.get("original_request") or state.get("user_input", "")
    plan = source_selection_plan(original_request, state.get("profile"))
    if plan.get("primary_source") != state.get("request_kind"):
        return []
    return list(plan.get("companion_sources") or [])


async def response_node(state: AgentState) -> dict[str, Any]:
    youth_policies = state.get("youth_policy_results", [])
    training_courses = state.get("training_results", [])
    recruitment_items = state.get("recruitment_results", [])
    profile = state.get("profile") or {}
    search_context = state.get("search_context") or {}
    outcome = state.get("search_outcome") or {}
    companion_sources = _companion_sources_for_state(state)

    candidates: list[dict[str, Any]] = []
    if training_courses:
        candidates = training_courses
    elif recruitment_items:
        candidates = recruitment_items
    elif youth_policies:
        candidates = youth_policies

    if candidates:
        generated = await compose_grounded_response(
            _llm,
            user_input=search_context.get("original_request") or state.get("user_input", ""),
            response_mode=state.get("response_mode", "recommend"),
            request_kind=state.get("request_kind", "youth_policy"),
            source_status=outcome.get("status", SearchStatus.SUCCESS),
            profile=profile,
            candidates=candidates,
            history=state.get("conversation_history") or [],
            applied_filters=outcome.get("applied_filters") or {},
            companion_sources=companion_sources,
            validation_errors=state.get("response_validation_errors") or [],
            previous_response=state.get("final_response"),
        )
        fallback_summary = compose_card_summary_reply(
            request_kind=state.get("request_kind", "youth_policy"),
            source_status=outcome.get("status", SearchStatus.SUCCESS),
            candidates=candidates,
            companion_sources=companion_sources,
        )
        return {"final_response": _prepare_search_response(state, generated or fallback_summary)}

    # The graph normally routes empty evidence to direct_response. Keep this
    # defensive branch grounded in the typed source status as well.
    status = outcome.get("status")
    if status not in {SearchStatus.NO_MATCH, SearchStatus.UNAVAILABLE, SearchStatus.PARTIAL}:
        status = SearchStatus.UNAVAILABLE
    return {
        "final_response": await compose_search_status_response(
            _llm,
            user_input=search_context.get("original_request") or state.get("user_input", ""),
            status=status,
            request_kind=state.get("request_kind", "youth_policy"),
            profile=profile,
            search_query=search_context.get("search_query"),
            warnings=outcome.get("warnings") or [],
            applied_filters=outcome.get("applied_filters") or {},
            companion_sources=companion_sources,
            history=state.get("conversation_history") or [],
            validation_errors=state.get("response_validation_errors") or [],
            previous_response=state.get("final_response"),
        )
    }


async def direct_response_node(state: AgentState) -> dict[str, Any]:
    """Render non-search and abstention paths without free-form evidence claims."""

    outcome = state.get("search_outcome") or {}
    if (
        state.get("direct_response_reason") == "card_summary_fallback"
        and state.get("response_validation_status") == "failed"
    ):
        return {
            "final_response": (
                "공식 조회 결과를 안전하게 검증하지 못해 이번 답변은 중단했어요. "
                "잠시 후 같은 조건으로 다시 검색해 주세요."
            ),
            "direct_response_reason": "validation_fatal",
            "abstention_reason": "answer_verification_failed",
            "youth_policy_results": [],
            "training_results": [],
            "recruitment_results": [],
        }
    if (
        state.get("direct_response_reason") == "candidate_followup_fallback"
        and state.get("response_validation_status") == "failed"
    ):
        return {
            "final_response": (
                "직전 카드의 세부 정보를 안전하게 검증하지 못해 이번 답변은 중단했어요. "
                "공식 원문은 카드에서 직접 확인해 주세요."
            ),
            "direct_response_reason": "validation_fatal",
            "abstention_reason": "answer_verification_failed",
        }
    if state.get("direct_response_reason") == "validation_fatal" or state.get("response_validation_status") == "failed":
        if state.get("missing_slots"):
            labels = [MISSING_SLOT_LABELS.get(slot, slot) for slot in state.get("missing_slots") or []]
            failure_reply = clarification_template(labels)
        elif state.get("last_presented_candidates") and references_recent_candidates(state.get("user_input", "")):
            return {
                "final_response": compose_recent_candidate_followup(
                    state.get("user_input", ""),
                    state.get("last_presented_candidates") or [],
                ),
                "direct_response_reason": "candidate_followup_fallback",
                "abstention_reason": "llm_candidate_followup_replaced",
            }
        elif state.get("action") == "SEARCH" and outcome.get("status") in {
            SearchStatus.SUCCESS,
            SearchStatus.PARTIAL,
        }:
            candidates = (
                state.get("training_results")
                or state.get("recruitment_results")
                or state.get("youth_policy_results")
                or []
            )
            if candidates:
                failure_reply = _prepare_search_response(
                    state,
                    compose_card_summary_reply(
                        request_kind=state.get("request_kind", "youth_policy"),
                        source_status=outcome["status"],
                        candidates=candidates,
                        companion_sources=_companion_sources_for_state(state),
                    ),
                )
                return {
                    "final_response": failure_reply,
                    "direct_response_reason": "card_summary_fallback",
                    "abstention_reason": "llm_card_summary_replaced",
                }
            context = state.get("search_context") or {}
            failure_reply = compose_search_status_reply(
                status=outcome["status"],
                request_kind=state.get("request_kind", "youth_policy"),
                profile=state.get("profile") or {},
                search_query=context.get("search_query") or state.get("search_query"),
                warnings=outcome.get("warnings") or [],
                applied_filters=outcome.get("applied_filters") or {},
                companion_sources=_companion_sources_for_state(state),
            )
        elif outcome.get("status") in {SearchStatus.NO_MATCH, SearchStatus.UNAVAILABLE, SearchStatus.PARTIAL}:
            context = state.get("search_context") or {}
            failure_reply = compose_search_status_reply(
                status=outcome["status"],
                request_kind=state.get("request_kind", "youth_policy"),
                profile=state.get("profile") or {},
                search_query=context.get("search_query") or state.get("search_query"),
                warnings=outcome.get("warnings") or [],
                applied_filters=outcome.get("applied_filters") or {},
                companion_sources=_companion_sources_for_state(state),
            )
        elif state.get("action") != "SEARCH" and (
            state.get("response_mode") == "out_of_scope" or is_brief_social_message(state.get("user_input", ""))
        ):
            failure_reply = compose_conversation_fallback(
                state.get("user_input", ""),
                state.get("response_mode", "general"),
            )
        elif state.get("action") == "SEARCH":
            failure_reply = (
                "공식 조회 결과를 안전하게 검증하지 못해 이번 답변은 중단했어요. "
                "잠시 후 같은 조건으로 다시 검색해 주세요."
            )
        else:
            # A failed free-form explanation can still recover to the
            # deterministic, non-quantitative domain guide. Do not turn a
            # recoverable writing error into an unrelated fatal refusal.
            failure_reply = compose_conversation_fallback(
                state.get("user_input", ""),
                state.get("response_mode", "general"),
            )
        return {
            "final_response": failure_reply,
            "direct_response_reason": "validation_fatal",
            "abstention_reason": "answer_verification_failed",
            "youth_policy_results": [],
            "training_results": [],
            "recruitment_results": [],
        }

    if state.get("missing_slots"):
        return await clarification_node(state)

    if outcome.get("status") in {SearchStatus.NO_MATCH, SearchStatus.UNAVAILABLE, SearchStatus.PARTIAL}:
        context = state.get("search_context") or {}
        return {
            "final_response": await compose_search_status_response(
                _llm,
                user_input=context.get("original_request") or state.get("user_input", ""),
                status=outcome["status"],
                request_kind=state.get("request_kind", "youth_policy"),
                profile=state.get("profile") or {},
                search_query=context.get("search_query") or state.get("search_query"),
                warnings=outcome.get("warnings") or [],
                applied_filters=outcome.get("applied_filters") or {},
                companion_sources=_companion_sources_for_state(state),
                history=state.get("conversation_history") or [],
                validation_errors=state.get("response_validation_errors") or [],
                previous_response=state.get("final_response"),
            ),
            "direct_response_reason": outcome["status"],
        }

    return await conversation_node(state)


# ---------------------------------------------------------------------------
# Conversation Node
# ---------------------------------------------------------------------------


async def conversation_node(state: AgentState) -> dict[str, Any]:
    user_input = state.get("user_input", "")
    response_mode = state.get("response_mode", "general")
    return {
        "final_response": await compose_conversation_reply(
            _llm,
            query=user_input,
            response_mode=response_mode,
            history=state.get("conversation_history") or [],
            profile=state.get("profile") or {},
            recent_candidates=state.get("last_presented_candidates") or [],
            validation_errors=state.get("response_validation_errors") or [],
            previous_response=state.get("final_response"),
        )
    }


# ---------------------------------------------------------------------------
# Response Validator Node
# ---------------------------------------------------------------------------


async def response_validator_node(state: AgentState) -> dict[str, Any]:
    errors = validate_response_state(state)
    revision_count = int(state.get("response_revision_count") or 0)
    should_retry = bool(errors) and revision_count < 1
    if should_retry:
        revision_count += 1
    return {
        "response_validation_status": "retry" if should_retry else "failed" if errors else "passed",
        "response_validation_errors": errors,
        "response_revision_count": revision_count,
    }


# ---------------------------------------------------------------------------
# Pre-verification safety and non-mutating finalize
# ---------------------------------------------------------------------------

_FORBIDDEN_PATTERNS = [
    (re.compile(r"반드시\s*(신청|지원)\s*가능(합니다|해요)?"), "확인해볼 만해요"),
    (re.compile(r"무조건\s*(지원|선정)?\s*(됩니다|돼요|가능합니다)?"), "조건이 맞는지 확인이 필요해요"),
    (re.compile(r"100\s*%\s*(확실|가능)"), "가능성이 높지만 추가 확인이 필요"),
]

_DISCLAIMER = "\n\n최종 신청 가능 여부는 공식 공고나 담당 기관에서 한 번 더 확인해 주세요."
_GENERATED_DISCLAIMER = re.compile(
    r"(?m)^\s*(?:[-•]\s*)?(?:※\s*)?(?:모든\s*정책\s*)?(?:최종\s*)?자격.*"
    r"(?:공식\s*공고|담당\s*기관).*$"
)


def _prepare_search_response(state: AgentState, text: str) -> str:
    """Apply deterministic safety edits before answer verification."""

    prepared = clean_response_text(text)
    if (state.get("search_outcome") or {}).get("status") == SearchStatus.PARTIAL and not (
        "일부" in prepared[:160] and "조회" in prepared[:160]
    ):
        prepared = (
            "일부 하위 조회가 완료되지 않아, 아래 내용은 현재 공식 소스에서 확인된 범위만 안내해요.\n\n" + prepared
        )
    for pattern, replacement in _FORBIDDEN_PATTERNS:
        prepared = pattern.sub(replacement, prepared)
    if state.get("action") == "SEARCH":
        prepared = prepared.replace(_DISCLAIMER.strip(), "")
        prepared = clean_response_text(_GENERATED_DISCLAIMER.sub("", prepared)).rstrip()
        prepared += _DISCLAIMER
    return prepared


async def finalize_response_node(state: AgentState) -> dict[str, Any]:
    """Persist history without changing the already verified response body."""

    text = state.get("final_response", "")
    history = list(state.get("conversation_history") or [])
    history.extend(
        [
            {"role": "user", "content": state.get("user_input", "")},
            {"role": "assistant", "content": text},
        ]
    )
    return {"final_response": text, "conversation_history": history[-8:]}

from __future__ import annotations

from app.graph.state import AgentState

_NON_REWRITABLE_REJECTIONS = {
    "age_mismatch",
    "age_unverified",
    "region_mismatch",
    "region_unverified",
    "closed",
    "career_unverified",
    "unsupported_recruitment_type",
}


def route_after_prepare(state: AgentState) -> str:
    if state.get("action") != "SEARCH" or state.get("missing_slots"):
        return "direct_response"
    return "retrieve"


def route_after_evidence(state: AgentState) -> str:
    outcome = state.get("search_outcome") or {}
    status = outcome.get("status")
    retryable_without_items = status == "unavailable" or (status == "partial" and not outcome.get("items"))
    if retryable_without_items and outcome.get("retryable") and int(state.get("search_attempt_count") or 0) < 2:
        return "retrieve"
    if status == "no_match":
        rejection_reasons = (state.get("evidence_assessment") or {}).get("rejection_reasons") or {}
        if _NON_REWRITABLE_REJECTIONS.intersection(rejection_reasons):
            return "direct_response"
        from app.graph.nodes import rewritten_search_query

        if (
            int(state.get("search_attempt_count") or 0) < 2
            and int(state.get("query_rewrite_count") or 0) < 1
            and rewritten_search_query(state)
        ):
            return "rewrite_query"
        return "direct_response"
    if outcome.get("items"):
        return "build_answer"
    return "direct_response"


def route_after_verification(state: AgentState) -> str:
    status = state.get("response_validation_status")
    if status == "retry":
        # Missing-slot and source-status replies still have action=SEARCH, but
        # they were intentionally built by direct_response and must never jump
        # into the grounded answer builder without candidates.
        if state.get("direct_response_reason"):
            return "direct_response"
        return "build_answer" if state.get("action") == "SEARCH" else "direct_response"
    if status == "failed":
        if state.get("direct_response_reason") == "validation_fatal":
            return "finalize"
        return "direct_response"
    return "finalize"

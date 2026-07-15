from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """LangGraph 그래프에서 노드 간에 전달되는 상태.

    `profile`, `conversation_history`, `pending_request`, `last_search_plan`은
    session_id 기준으로 명시적 세션 저장소에 보관된다. 검색 결과 배열과 검증
    상태는 턴 전용이고, 직전 결과 후속 설명에는 allowlist된
    `last_presented_candidates`만 사용한다.
    """

    session_id: str
    user_input: str
    intent: str
    action: str
    response_mode: str
    request_kind: str
    search_query: str | None
    routing_source: str
    resumed_pending: bool
    pending_action: str
    route_validation_status: str
    route_validation_errors: list[str]
    profile: dict
    conversation_history: list[dict[str, str]]
    pending_request: dict
    last_presented_candidates: list[dict]
    last_search_plan: dict
    turn_relation: str
    region_filter_mode: str
    profile_delta: dict
    effective_filters: dict
    search_context: dict
    search_outcome: dict
    evidence_assessment: dict
    search_attempt_count: int
    query_rewrite_count: int
    direct_response_reason: str | None
    abstention_reason: str | None
    missing_slots: list[str]
    youth_policy_results: list[dict]
    training_results: list[dict]
    recruitment_results: list[dict]
    final_response: str
    response_validation_status: str
    response_validation_errors: list[str]
    response_revision_count: int
    privacy_blocked: bool


def fresh_turn_fields() -> AgentState:
    """Return state that must never leak from a previous graph invocation.

    Durable profile/history/pending/candidate-snapshot fields are loaded by the
    API repository. Search evidence, validation output, and the draft answer
    belong to one request only and are reset at both the API and Router entry.
    """

    return {
        "search_context": {},
        "turn_relation": "NEW",
        "region_filter_mode": "specific",
        "profile_delta": {},
        "effective_filters": {},
        "search_outcome": {},
        "evidence_assessment": {},
        "search_attempt_count": 0,
        "query_rewrite_count": 0,
        "direct_response_reason": None,
        "abstention_reason": None,
        "missing_slots": [],
        "youth_policy_results": [],
        "training_results": [],
        "recruitment_results": [],
        "final_response": "",
        "route_validation_status": "pending",
        "route_validation_errors": [],
        "response_validation_status": "pending",
        "response_validation_errors": [],
        "response_revision_count": 0,
        "privacy_blocked": False,
    }

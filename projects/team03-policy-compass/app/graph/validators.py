from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from app.graph.contracts import RoutingDecision
from app.graph.fallbacks import brief_social_message_kind
from app.graph.response_composer import references_recent_candidates
from app.graph.state import AgentState

_URL_PATTERN = re.compile(r"https?://[^\s)]+")
_SPECIFIC_OUT_OF_SCOPE_LABELS = ("세무", "법률")
_UNSUPPORTED_EXPLANATION_FACT = re.compile(
    r"(?:\d[\d,.]*\s*(?:백|천)?\s*(?:만|억)?\s*원)|"
    r"(?:\d[\d,.]*\s*%)|(?:\d{1,3}\s*[~～-]\s*\d{1,3}\s*세)|"
    r"(?:\d+\s*(?:개월|년))|(?:20\d{2}\s*(?:년|[-./]))|(?:https?://)"
)
_STRUCTURED_CLAIM = re.compile(
    r"(?:\d[\d,.]*\s*(?:백|천)?\s*(?:만|억)?\s*원)|(?:\d[\d,.]*\s*%)|"
    r"(?:\d{1,3}\s*[~～-]\s*\d{1,3}\s*세)|(?:\d+\s*(?:개월|년))|"
    r"(?:20\d{2}(?:\s*년(?:\s*\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?)?|[-./]\d{1,2}(?:[-./]\d{1,2})?))"
)
_INTERNAL_STATUS_DETAIL = re.compile(
    r"\b(?:[A-Z][A-Z0-9]*_){2,}[A-Z0-9]+\b|"
    r"(?:API[_\s-]?KEY|SUPABASE|LANGFUSE|TRACEBACK|STACK\s+TRACE)|"
    r"(?:\d+\s*건.{0,20}(?:제외|탈락|필터링))",
    re.IGNORECASE,
)
_SENSITIVE_INFORMATION_LABEL = re.compile(
    r"주민\s*(?:등록)?\s*번호|외국인\s*등록\s*번호|상세\s*주소|"
    r"계좌\s*번호|통장\s*번호|전화\s*번호|휴대(?:폰|전화)\s*번호|연락처"
)
_SENSITIVE_INFORMATION_REQUEST = re.compile(r"알려|입력|제공|보내|적어|말해|필요|요구|제출")
_UNSUPPORTED_HISTORY_REFERENCE = re.compile(r"다시|오랜만|지난번|전에\s*(?:말씀|문의)|기억(?:하고|해)")
_GREETING_INVITATION = re.compile(r"물어|말씀|알려|도와|질문|찾아")
_CARD_DETAIL_LANGUAGE = re.compile(
    r"지원\s*내용|자격\s*(?:조건|요건)?|신청\s*(?:방법|기간|자격|가능)|"
    r"전국\s*(?:단위|대상)|지역\s*(?:제한|요건)|연령\s*(?:기준|제한)|"
    r"\d{1,2}\s*세(?:\s|인|청년)|거주(?:하는|지)"
)
_UNVERIFIED_MATCH_CLAIM = re.compile(r"조건에\s*맞는|신청\s*가능(?:한|합니다|해요)")
_SUPPORTED_SCOPE_LABELS = ("청년정책", "청년 정책", "구직", "취업", "직업훈련", "훈련", "채용정보", "채용")
_MISSING_SLOT_MARKERS = {
    "region": ("지역", "거주지"),
    "region_detail": ("시·도", "시도", "지역명"),
    "training_region": ("지역", "훈련 장소"),
    "work_region": ("지역", "근무지"),
    "age": ("나이", "연령"),
    "employment_status": ("구직", "재직", "재학", "취업 상태"),
    "policy_topic": ("분야", "관심 정책"),
    "desired_job": ("직무", "분야", "배우"),
}


def validate_route_state(state: AgentState) -> list[str]:
    """Validate the normalized route without replacing a valid LLM decision."""

    payload = {
        "action": state.get("action"),
        "response_mode": state.get("response_mode"),
        "request_kind": state.get("request_kind"),
        "search_query": state.get("search_query"),
        "resume_pending": state.get("resumed_pending", False),
    }
    try:
        decision = RoutingDecision.model_validate(payload)
    except ValidationError:
        return ["route_contract_invalid"]

    normalized_fields = {
        "action": decision.action.value,
        "response_mode": decision.response_mode.value,
        "request_kind": decision.request_kind.value,
        "search_query": decision.search_query,
    }
    if any(state.get(key) != value for key, value in normalized_fields.items()):
        return ["route_contract_normalization_mismatch"]

    intent = state.get("intent")
    if intent and intent != decision.intent.value:
        return ["route_intent_mismatch"]
    return []


def validate_response_state(state: AgentState) -> list[str]:
    """Check role alignment and grounded identifiers before the final guardrail."""

    text = (state.get("final_response") or "").strip()
    if not text:
        return ["response_empty"]

    errors: list[str] = []
    for slot in state.get("missing_slots") or []:
        markers = _MISSING_SLOT_MARKERS.get(slot, (slot,))
        if not any(marker in text for marker in markers):
            errors.append(f"clarification_slot_missing:{slot}")
    if (
        state.get("missing_slots")
        and _SENSITIVE_INFORMATION_LABEL.search(text)
        and _SENSITIVE_INFORMATION_REQUEST.search(text)
    ):
        errors.append("sensitive_information_requested")

    response_mode = state.get("response_mode")
    if response_mode == "general":
        if len(text) > 800:
            errors.append("general_response_too_long")
        if state.get("action") != "SEARCH" and _UNSUPPORTED_EXPLANATION_FACT.search(text):
            errors.append("ungrounded_general_fact")
        if brief_social_message_kind(state.get("user_input", "")) == "greeting":
            if not state.get("conversation_history") and _UNSUPPORTED_HISTORY_REFERENCE.search(text):
                errors.append("unsupported_conversation_history")
            if "정책나침반" not in text and not any(label in text for label in _SUPPORTED_SCOPE_LABELS):
                errors.append("greeting_scope_missing")
            if not _GREETING_INVITATION.search(text):
                errors.append("greeting_invitation_missing")
    elif response_mode == "out_of_scope":
        if not any(label in text for label in _SUPPORTED_SCOPE_LABELS):
            errors.append("policy_scope_redirect_missing")
        if any(label in text for label in _SPECIFIC_OUT_OF_SCOPE_LABELS):
            errors.append("specific_out_of_scope_label_exposed")
        if _UNSUPPORTED_EXPLANATION_FACT.search(text):
            errors.append("unsupported_out_of_scope_fact")
    elif response_mode == "explain" and state.get("action") != "SEARCH":
        has_snapshot_reference = bool(state.get("last_presented_candidates")) and references_recent_candidates(
            state.get("user_input", "")
        )
        if not has_snapshot_reference and _UNSUPPORTED_EXPLANATION_FACT.search(text):
            errors.append("ungrounded_explanation_fact")

    source_status = (state.get("search_outcome") or {}).get("status")
    if source_status == "unavailable" and not (
        "결과가 없다는 뜻" in text or ("조회" in text and any(word in text for word in ("불가능", "어려", "실패")))
    ):
        errors.append("unavailable_status_not_disclosed")
    elif source_status == "partial" and not ("일부" in text and "조회" in text):
        errors.append("partial_status_not_disclosed")

    titles, allowed_urls, requires_grounding = _grounding_evidence(state)
    if source_status in {"no_match", "unavailable", "partial"} and not requires_grounding:
        if _URL_PATTERN.search(text):
            errors.append("unsupported_status_url")
        if _STRUCTURED_CLAIM.search(text):
            errors.append("unsupported_status_fact")
        if _INTERNAL_STATUS_DETAIL.search(text):
            errors.append("internal_status_detail_exposed")
    if not requires_grounding:
        return errors

    response_urls = {_normalize_url(value) for value in _URL_PATTERN.findall(text)}
    if state.get("action") == "SEARCH":
        card_summary_text = text.split("최종 신청 가능 여부", maxsplit=1)[0]
        if "카드" not in text:
            errors.append("card_summary_missing")
        if any(title in text for title in titles):
            errors.append("card_detail_duplicated")
        if response_urls:
            errors.append("card_url_duplicated")
        if _CARD_DETAIL_LANGUAGE.search(card_summary_text):
            errors.append("card_detail_language_exposed")
        if any(
            item.get("match_scope") == "unknown" or item.get("evidence_status") == "unverified"
            for item in _grounding_candidates(state)
        ) and _UNVERIFIED_MATCH_CLAIM.search(card_summary_text):
            errors.append("unverified_card_overclaimed")
        if len(text) > 500:
            errors.append("card_summary_too_long")
        source_text = " ".join(str(value) for item in _grounding_candidates(state) for value in item.values())
        has_unsupported_claim = any(
            _normalize_claim(match.group(0)) not in _normalize_claim(source_text)
            for match in _STRUCTURED_CLAIM.finditer(text)
        )
        if has_unsupported_claim:
            errors.append("unsupported_structured_claim")
        return errors

    if titles:
        missing_titles = {title for title in titles if title not in text}
        if len(missing_titles) == len(titles):
            errors.append("grounded_title_missing")

    unsupported_urls = response_urls - allowed_urls
    if unsupported_urls:
        errors.append("unsupported_source_url")
    if allowed_urls:
        if not response_urls.intersection(allowed_urls):
            errors.append("grounded_source_url_missing")
    source_text = " ".join(str(value) for item in _grounding_candidates(state) for value in item.values())
    has_unsupported_claim = any(
        _normalize_claim(match.group(0)) not in _normalize_claim(source_text)
        for match in _STRUCTURED_CLAIM.finditer(text)
    )
    if has_unsupported_claim:
        errors.append("unsupported_structured_claim")
    return errors


def _grounding_evidence(state: AgentState) -> tuple[set[str], set[str], bool]:
    candidates = _grounding_candidates(state)
    if not candidates:
        return set(), set(), False

    substantive = [item for item in candidates if not _is_guide_item(item)]
    evidence_items = substantive or candidates
    titles = {str(item["title"]).strip() for item in evidence_items if item.get("title")}
    urls: set[str] = set()
    for item in evidence_items:
        canonical_url = item.get("detail_url") or item.get("institution_url") or item.get("source_url")
        if canonical_url:
            urls.add(_normalize_url(str(canonical_url)))
    return titles, urls, bool(substantive)


def _grounding_candidates(state: AgentState) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    if state.get("action") == "SEARCH":
        for key in ("youth_policy_results", "training_results", "recruitment_results"):
            candidates.extend(state.get(key) or [])
    elif state.get("response_mode") == "explain" and references_recent_candidates(state.get("user_input", "")):
        candidates.extend(state.get("last_presented_candidates") or [])
    else:
        return []
    return candidates


def _is_guide_item(item: dict[str, Any]) -> bool:
    return bool(
        item.get("policy_id") == "youthcenter-guide"
        or item.get("course_id") == "work24-training-guide"
        or item.get("item_type") == "guide"
    )


def _normalize_url(value: str) -> str:
    return value.rstrip(".,;]")


def _normalize_claim(value: str) -> str:
    return re.sub(r"[\s,]", "", value)

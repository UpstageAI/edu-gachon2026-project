from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.core.llm import LLMUnavailableError, SolarLLMClient
from app.core.prompts import (
    CANDIDATE_FOLLOWUP_SYSTEM_PROMPT,
    CLARIFICATION_SYSTEM_PROMPT,
    CONVERSATION_SYSTEM_PROMPT,
    GROUNDED_RESPONSE_SYSTEM_PROMPT,
    POLICY_CAPABILITY_REPLY,
    POLICY_GREETING_REPLY,
    POLICY_SCOPE_REPLY,
    POLICY_THANKS_REPLY,
    SEARCH_STATUS_SYSTEM_PROMPT,
)
from app.graph.fallbacks import brief_social_message_kind
from app.graph.fallbacks import general_reply as fallback_general_reply
from app.graph.search_contracts import SearchStatus

logger = logging.getLogger(__name__)

_MARKDOWN_LINK = re.compile(r"\[([^\]]+)]\((https?://[^)]+)\)")
_FORMAL_INTRO = re.compile(
    r"사용자님의\s*질문\s*\([^\n]*\)\s*에\s*따라,[^\n]*(?:추천|안내)합니다\.?\s*",
)
_INTERNAL_FIELD_LABELS = {
    "application_period": "신청 기간",
    "application_method": "신청 방법",
    "detail_url": "상세 링크",
    "business_period": "사업 기간",
}
_RECENT_REFERENCE = re.compile(
    r"(?:방금|아까|앞서|위의?|직전|이전)\s*(?:본|말한|안내한)?|"
    r"(?:그|이)\s*(?:정책|과정|공고|결과|항목)|"
    r"(?:[1-3]\s*번|첫\s*번째|두\s*번째|세\s*번째)"
)
_REVISION_MARKER = re.compile(r"(?m)^\s*수정된\s*답변\s*:?[ \t]*$")
_EMOJI_PATTERN = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")

_CARD_SOURCE_NAMES = {
    "youth_policy": "청년정책",
    "training": "고용24 훈련과정",
    "recruitment": "고용24 공채속보·채용행사",
}

_COMPANION_ACTION_LABELS = {
    "youth_policy": "온통청년의 관련 지원정책",
    "training": "고용24의 실제 훈련과정",
    "recruitment": "고용24 공채속보·채용행사",
}

_MISSING_CANDIDATE_CONTEXT_REPLY = (
    "직전 카드 정보를 현재 대화에서 확인할 수 없어요. 정책명을 알려주시거나 같은 조건으로 다시 검색해 주세요."
)


def _compact_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove repository internals before candidates cross the LLM boundary."""

    compact: list[dict[str, Any]] = []
    for candidate in candidates[:3]:
        item: dict[str, Any] = {}
        for key, value in candidate.items():
            if key == "raw" or value in (None, "", [], {}):
                continue
            if isinstance(value, str):
                item[key] = value[:1200]
            elif isinstance(value, dict):
                item[key] = {
                    nested_key: nested_value
                    for nested_key, nested_value in value.items()
                    if nested_key != "raw" and nested_value not in (None, "", [], {})
                }
            else:
                item[key] = value
        compact.append(item)
    return compact


def _display_card_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mirror the API card title de-duplication before describing card counts."""

    displayed: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    for candidate in candidates:
        title = str(candidate.get("title") or "").strip()
        if title and title in seen_titles:
            continue
        if title:
            seen_titles.add(title)
        displayed.append(candidate)
        if len(displayed) == 3:
            break
    return displayed


def _companion_actions(companion_sources: list[str] | None) -> list[str]:
    return [
        _COMPANION_ACTION_LABELS[source]
        for source in dict.fromkeys(companion_sources or [])
        if source in _COMPANION_ACTION_LABELS
    ]


def _with_companion_cta(text: str, companion_sources: list[str] | None) -> str:
    """Offer a second source without implying that it was already queried."""

    actions = _companion_actions(companion_sources)
    if not actions:
        return text
    if "이어" in text and any(action.split("의", 1)[0] in text for action in actions):
        return text
    if len(actions) == 1:
        action_text = actions[0]
    else:
        action_text = "과 ".join(actions)
    return f"{text.rstrip()} 원하시면 {action_text}도 이어서 찾아드릴게요."


def _public_search_conditions(
    *,
    search_query: str | None,
    applied_filters: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep only filters that were actually sent to a source and are safe to show."""

    public_keys = {
        "region",
        "training_region",
        "work_region",
        "training_keyword",
        "keyword",
        "career_level",
        "policy_keyword",
        "active_only",
    }
    conditions = {
        key: value
        for key, value in (applied_filters or {}).items()
        if key in public_keys and value not in (None, "", [], {})
    }
    if search_query and not any(key in conditions for key in ("training_keyword", "keyword", "policy_keyword")):
        conditions["search_query"] = search_query
    return conditions


def clean_response_text(text: str) -> str:
    """Keep chat responses readable in a plain-text UI even if an LLM emits Markdown."""

    cleaned = _FORMAL_INTRO.sub("", text or "")
    if _REVISION_MARKER.search(cleaned):
        cleaned = _REVISION_MARKER.split(cleaned)[-1]
    cleaned = _MARKDOWN_LINK.sub(r"\1 (\2)", cleaned)
    cleaned = _EMOJI_PATTERN.sub("", cleaned)
    for internal_name, label in _INTERNAL_FIELD_LABELS.items():
        cleaned = cleaned.replace(internal_name, label)

    lines: list[str] = []
    for raw_line in cleaned.splitlines():
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", raw_line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"^\s*\*\s+", "- ", line)
        line = line.replace("**", "").replace("__", "").replace("`", "")
        if line.strip() == "---":
            continue
        if line.strip().rstrip(":") in {"답변", "수정된 답변", "추천 정책", "안내 사항"}:
            continue
        if "누락된 신청 정보" in line:
            continue
        lines.append(line.rstrip())

    result = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


async def compose_clarification_reply(
    llm: SolarLLMClient,
    *,
    original_request: str,
    profile: dict[str, Any],
    labels: list[str],
    history: list[dict[str, str]],
    validation_errors: list[str] | None = None,
    previous_response: str | None = None,
) -> str:
    if llm.is_configured:
        payload = {
            "original_request": original_request,
            "known_profile": profile,
            "missing_slots": labels,
            "recent_history": history[-6:],
            "validation_errors": validation_errors or [],
            "previous_response": previous_response if validation_errors else None,
        }
        try:
            return clean_response_text(
                await llm.complete(
                    [
                        {"role": "system", "content": CLARIFICATION_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    operation_name="clarification",
                )
            )
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 조건 확인 템플릿을 사용합니다.")
        except Exception:  # noqa: BLE001
            logger.exception("조건 확인 LLM 호출 실패, 템플릿으로 폴백합니다.")
    return clarification_template(labels)


def clarification_template(labels: list[str]) -> str:
    return "정확한 결과를 찾으려면 다음 정보가 필요해요: " + ", ".join(labels) + "."


def compose_search_status_reply(
    *,
    status: str,
    request_kind: str,
    profile: dict[str, Any],
    search_query: str | None,
    warnings: list[str] | None = None,
    applied_filters: dict[str, Any] | None = None,
    companion_sources: list[str] | None = None,
) -> str:
    """Render a deterministic abstention without treating failures as no-match."""

    source_names = {
        "youth_policy": "온통청년 청년정책",
        "training": "고용24 훈련과정",
        "recruitment": "고용24 채용행사·공채속보",
    }
    source_name = source_names.get(request_kind, "공식 정책 데이터")
    if status == SearchStatus.UNAVAILABLE:
        return _with_companion_cta(
            f"현재 {source_name} 조회가 일시적으로 불가능해요. "
            "검색 결과가 없다는 뜻은 아니며, 잠시 후 다시 시도해 주세요.",
            companion_sources,
        )
    if status == SearchStatus.PARTIAL:
        return _with_companion_cta(
            f"현재 {source_name} 하위 조회 중 일부가 완료되지 않았고, "
            "확인된 범위에서는 조건을 통과한 결과가 없었어요. "
            "전체 결과가 없다고 단정할 수 없으니 잠시 후 다시 시도해 주세요.",
            companion_sources,
        )

    public_conditions = _public_search_conditions(
        search_query=search_query,
        applied_filters=applied_filters,
    )
    applied_region = next(
        (
            public_conditions.get(key)
            for key in ("region", "training_region", "work_region")
            if public_conditions.get(key)
        ),
        None,
    )
    conditions = [
        f"{applied_region} 지역" if applied_region else None,
        f"'{search_query}' 검색어" if search_query else None,
    ]
    condition_text = "·".join(value for value in conditions if value)
    condition_prefix = f" ({condition_text})" if condition_text else ""
    return _with_companion_cta(
        f"{source_name}에서 현재 조건{condition_prefix}에 맞는 결과를 찾지 못했어요. "
        "조건을 임의로 완화해 다른 지역이나 대상의 결과를 추천하지는 않을게요.",
        companion_sources,
    )


async def compose_search_status_response(
    llm: SolarLLMClient,
    *,
    user_input: str,
    status: str,
    request_kind: str,
    profile: dict[str, Any],
    search_query: str | None,
    warnings: list[str] | None = None,
    applied_filters: dict[str, Any] | None = None,
    companion_sources: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    validation_errors: list[str] | None = None,
    previous_response: str | None = None,
) -> str:
    if llm.is_configured:
        payload = {
            "user_input": user_input,
            "source_status": status,
            "request_kind": request_kind,
            "public_search_conditions": _public_search_conditions(
                search_query=search_query,
                applied_filters=applied_filters,
            ),
            "search_query": search_query,
            "source_has_warnings": bool(warnings),
            "companion_actions": _companion_actions(companion_sources),
            "validation_errors": validation_errors or [],
            "previous_response": previous_response if validation_errors else None,
        }
        try:
            generated = clean_response_text(
                await llm.complete(
                    [
                        {"role": "system", "content": SEARCH_STATUS_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    operation_name="search-status",
                )
            )
            return _with_companion_cta(generated, companion_sources)
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 검색 상태 템플릿을 사용합니다.")
        except Exception:  # noqa: BLE001
            logger.exception("검색 상태 LLM 응답 생성 실패, 템플릿으로 폴백합니다.")
    return compose_search_status_reply(
        status=status,
        request_kind=request_kind,
        profile=profile,
        search_query=search_query,
        warnings=warnings,
        applied_filters=applied_filters,
        companion_sources=companion_sources,
    )


async def compose_conversation_reply(
    llm: SolarLLMClient,
    *,
    query: str,
    response_mode: str,
    history: list[dict[str, str]],
    profile: dict[str, Any] | None = None,
    recent_candidates: list[dict[str, Any]] | None = None,
    validation_errors: list[str] | None = None,
    previous_response: str | None = None,
) -> str:
    if recent_candidates and references_recent_candidates(query):
        return await compose_candidate_followup(
            llm,
            query=query,
            candidates=recent_candidates,
            history=history,
            validation_errors=validation_errors,
            previous_response=previous_response,
        )
    if references_recent_candidates(query):
        return _MISSING_CANDIDATE_CONTEXT_REPLY

    # Scope classification can use the LLM, but the refusal copy is a stable
    # product contract and must not drift into answering or recommending the
    # unrelated topic.
    if response_mode == "out_of_scope":
        return POLICY_SCOPE_REPLY

    if llm.is_configured:
        try:
            payload = {
                "user_input": query,
                "response_mode": response_mode,
                "recent_history": history[-8:],
                "known_profile": profile or {},
                "validation_errors": validation_errors or [],
                "previous_response": previous_response if validation_errors else None,
            }
            return clean_response_text(
                await llm.complete(
                    [
                        {"role": "system", "content": CONVERSATION_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.3,
                    operation_name=f"conversation-{response_mode}",
                )
            )
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 일반 대화 템플릿을 사용합니다.")
        except Exception:  # noqa: BLE001
            logger.exception("일반 대화 LLM 호출 실패, 템플릿으로 폴백합니다.")
    return compose_conversation_fallback(query, response_mode)


def compose_conversation_fallback(query: str, response_mode: str) -> str:
    """Return the deterministic endpoint for a failed conversation draft."""

    if response_mode == "general":
        social_kind = brief_social_message_kind(query)
        if social_kind == "greeting":
            return POLICY_GREETING_REPLY
        if social_kind == "capability":
            return POLICY_CAPABILITY_REPLY
        if social_kind == "thanks":
            return POLICY_THANKS_REPLY
    if response_mode == "out_of_scope":
        return POLICY_SCOPE_REPLY
    return fallback_general_reply(query)


def compose_scored_template(scored: list[dict]) -> str:
    """세부 내용은 프론트 카드로 표시되므로, 여기서는 짧은 안내 멘트만 반환한다."""

    nearby_only = bool(scored) and all(item.get("recommendation_scope") == "nearby_reference" for item in scored)
    if nearby_only:
        return (
            "요청 지역에 정확히 일치하거나 전국 대상인 지원사업은 찾지 못했어요. "
            "아래 카드는 가까운 지역 참고 결과이며, 거주 요건 때문에 신청하지 못할 수 있어요."
        )
    return (
        f"현재 조건에 맞는 지원사업 {len(scored)}건을 아래 카드로 정리했어요. "
        "최종 신청 가능 여부는 카드의 원문 링크에서 확인해주세요."
    )


async def compose_candidate_followup(
    llm: SolarLLMClient,
    *,
    query: str,
    candidates: list[dict[str, Any]],
    history: list[dict[str, str]],
    validation_errors: list[str] | None = None,
    previous_response: str | None = None,
) -> str:
    if llm.is_configured:
        payload = {
            "user_input": query,
            "candidates": _compact_candidates(candidates),
            "recent_history": history[-6:],
            "validation_errors": validation_errors or [],
            "previous_response": previous_response if validation_errors else None,
        }
        try:
            return clean_response_text(
                await llm.complete(
                    [
                        {"role": "system", "content": CANDIDATE_FOLLOWUP_SYSTEM_PROMPT},
                        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                    ],
                    temperature=0.2,
                    operation_name="candidate-followup",
                )
            )
        except LLMUnavailableError:
            logger.info("LLM 미설정으로 직전 후보 후속 답변 템플릿을 사용합니다.")
        except Exception:  # noqa: BLE001
            logger.exception("직전 후보 후속 LLM 답변 생성 실패, 템플릿으로 폴백합니다.")
    return compose_recent_candidate_followup(query, candidates)


def references_recent_candidates(query: str) -> bool:
    """Return whether a follow-up explicitly points at prior displayed items."""

    return bool(_RECENT_REFERENCE.search(query or ""))


def compose_recent_candidate_followup(query: str, candidates: list[dict[str, Any]]) -> str:
    """Answer candidate follow-ups from an allowlisted snapshot without an LLM."""

    selected_index = _referenced_candidate_index(query)
    if selected_index >= len(candidates):
        return f"직전 안내에는 {len(candidates)}개 항목만 있어 요청하신 번호를 확인할 수 없어요."

    item = candidates[selected_index]
    title = item.get("title") or "제목 미확인 항목"
    lines = [f"직전 안내의 {selected_index + 1}번 항목은 '{title}'이에요."]
    requested_fields = _requested_candidate_fields(query)
    facts = _candidate_facts(item, requested_fields=requested_fields)
    if facts:
        lines.extend(f"- {label}: {value}" for label, value in facts)
    elif requested_fields:
        lines.append("저장된 공식 조회 결과에는 질문하신 세부 정보가 없어 추측해서 답하지 않을게요.")
    else:
        lines.append("직전 조회에서 저장된 핵심 정보만 다시 보여드릴게요.")
        lines.extend(f"- {label}: {value}" for label, value in _candidate_facts(item, requested_fields=set()))

    if detail_url := item.get("detail_url"):
        lines.append(f"- 공식 원문: {detail_url}")
    if requested_fields and not facts:
        lines.append("원문 상세 화면이나 담당 기관에서 해당 항목을 확인해 주세요.")
    return "\n".join(lines)


def _referenced_candidate_index(query: str) -> int:
    if match := re.search(r"([1-3])\s*번", query):
        return int(match.group(1)) - 1
    for marker, index in (("첫 번째", 0), ("첫번째", 0), ("두 번째", 1), ("두번째", 1), ("세 번째", 2), ("세번째", 2)):
        if marker in query:
            return index
    return 0


def compose_youth_policy_response(items: list[dict]) -> str:
    nearby_only = bool(items) and all(item.get("match_scope") == "nearby" for item in items)
    if nearby_only:
        return (
            "요청 지역에 정확히 일치하거나 전국 대상인 청년정책은 찾지 못했어요. "
            "아래 카드는 가까운 지역 참고 결과이며, 해당 지역 거주 요건 때문에 신청하지 못할 수 있어요."
        )
    shown = items[:3]
    return (
        f"현재 조건에 맞는 청년지원사업 {len(shown)}건을 아래 카드로 정리했어요. "
        "최종 자격과 신청 가능 여부는 카드의 상세 링크에서 확인해주세요."
    )


def compose_training_response(items: list[dict]) -> str:
    guide_items = [item for item in items if item.get("course_id") == "work24-training-guide"]
    if guide_items:
        guide = guide_items[0]
        return (
            "고용24 훈련과정 API에서 조건에 맞는 과정을 바로 찾지 못했어요.\n"
            "대신 아래 링크와 검색어로 고용24에서 직접 확인해보세요.\n\n"
            f"- 검색 링크: {guide.get('detail_url') or 'https://www.work24.go.kr/cm/main.do'}\n"
            f"- 추천 검색어: {guide.get('raw', {}).get('search_keyword') or guide.get('title')}\n"
            f"- 지역 조건: {guide.get('region') or '전체 또는 희망 지역'}\n"
            "- 확인 위치: 고용24 > 직업 능력 개발 > 훈련 찾기·신청\n"
            f"- 데이터 안내: {guide.get('fallback_reason') or '검색 결과 없음'}"
        )

    shown = items[:3]
    return (
        f"고용24 국민내일배움카드 훈련과정 {len(shown)}건을 아래 카드로 정리했어요. "
        "수강 가능 여부와 자비부담액은 카드의 상세 링크에서 다시 확인해주세요."
    )


def compose_recruitment_response(items: list[dict]) -> str:
    guide_items = [item for item in items if item.get("item_type") == "guide"]
    if guide_items:
        guide = guide_items[0]
        return (
            f"{guide['title']}\n"
            f"- 안내: {guide.get('summary') or '고용24에서 관심 직무와 지역 기준으로 다시 검색해주세요.'}\n"
            f"- 확인 링크: {guide.get('detail_url') or 'https://www.work24.go.kr/'}\n"
            f"- 제한 사유: {guide.get('fallback_reason') or '개인회원 API 권한 제한 또는 결과 없음'}\n\n"
            "제가 없는 채용공고를 만들어 안내하지는 않을게요. 관심 직무와 희망 지역을 알려주시면 "
            "검색 키워드와 확인해야 할 공고 조건을 더 구체적으로 정리해드릴 수 있어요."
        )

    shown = items[:3]
    return f"고용24에서 확인된 채용 관련 보조 정보 {len(shown)}건을 아래 카드로 정리했어요."


def _requested_candidate_fields(query: str) -> set[str]:
    requested: set[str] = set()
    keyword_groups = {
        "cost": ("비용", "자비부담", "훈련비", "금액"),
        "allowance": ("장려금", "수당"),
        "period": ("기간", "언제", "시작", "마감"),
        "eligibility": ("자격", "대상", "누가"),
        "application": ("신청", "접수"),
        "region": ("지역", "어디"),
    }
    for field, keywords in keyword_groups.items():
        if any(keyword in query for keyword in keywords):
            requested.add(field)
    return requested


def _candidate_facts(item: dict[str, Any], *, requested_fields: set[str]) -> list[tuple[str, Any]]:
    fact_groups: dict[str, tuple[tuple[str, str], ...]] = {
        "cost": (("cost", "비용"), ("actual_cost", "실부담액")),
        # The supported APIs do not currently expose a reliable allowance field.
        "allowance": (),
        "period": (
            ("application_period", "신청 기간"),
            ("start_date", "시작일"),
            ("end_date", "종료·마감일"),
        ),
        "eligibility": (("target_summary", "지원 대상"),),
        "application": (
            ("application_period", "신청 기간"),
            ("application_method", "신청 방법"),
        ),
        "region": (("region", "지역"), ("address", "주소")),
    }
    if requested_fields:
        pairs = [pair for field in requested_fields for pair in fact_groups[field]]
    else:
        pairs = [
            ("organization", "운영 기관"),
            ("institution", "훈련 기관"),
            ("company", "기업"),
            ("region", "지역"),
            ("target_summary", "지원 대상"),
            ("support_summary", "지원 내용"),
            ("summary", "요약"),
            ("start_date", "시작일"),
            ("end_date", "종료·마감일"),
        ]

    facts: list[tuple[str, Any]] = []
    seen_keys: set[str] = set()
    for key, label in pairs:
        if key in seen_keys:
            continue
        seen_keys.add(key)
        value = item.get(key)
        if value not in (None, "", [], {}):
            facts.append((label, value))
    return facts


async def compose_grounded_response(
    llm: SolarLLMClient,
    *,
    user_input: str,
    response_mode: str,
    request_kind: str,
    source_status: str,
    profile: dict[str, Any],
    candidates: list[dict[str, Any]],
    history: list[dict[str, str]],
    applied_filters: dict[str, Any] | None = None,
    companion_sources: list[str] | None = None,
    validation_errors: list[str] | None = None,
    previous_response: str | None = None,
) -> str | None:
    """Use Solar as the primary grounded answer writer after deterministic gates."""

    if not llm.is_configured:
        return None
    displayed_candidates = _display_card_candidates(candidates)
    scope_counts: dict[str, int] = {}
    for candidate in displayed_candidates:
        scope = str(candidate.get("match_scope") or "unknown")
        scope_counts[scope] = scope_counts.get(scope, 0) + 1
    payload = {
        "user_input": user_input,
        "response_mode": response_mode,
        "request_kind": request_kind,
        "source_status": source_status,
        "public_search_conditions": _public_search_conditions(
            search_query=None,
            applied_filters=applied_filters,
        ),
        "card_count": len(displayed_candidates),
        "card_source": _CARD_SOURCE_NAMES.get(request_kind, "공식 검색 결과"),
        "match_scope_counts": scope_counts,
        "companion_actions": _companion_actions(companion_sources),
        "validation_errors": validation_errors or [],
        "previous_response": previous_response if validation_errors else None,
    }
    try:
        generated = clean_response_text(
            await llm.complete(
                [
                    {"role": "system", "content": GROUNDED_RESPONSE_SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                temperature=0.2,
                operation_name=f"grounded-answer-{request_kind}",
            )
        )
        return _with_companion_cta(generated, companion_sources)
    except LLMUnavailableError:
        logger.info("LLM 미설정으로 %s 검색 결과 템플릿을 사용합니다.", request_kind)
    except Exception:  # noqa: BLE001
        logger.exception("%s 검색 결과 LLM 생성 실패, 템플릿으로 폴백합니다.", request_kind)
    return None


def compose_card_summary_reply(
    *,
    request_kind: str,
    source_status: str,
    candidates: list[dict[str, Any]],
    companion_sources: list[str] | None = None,
) -> str:
    """Deterministic fallback for a successful search rendered as UI cards."""

    displayed = _display_card_candidates(candidates)
    count = len(displayed)
    source_name = _CARD_SOURCE_NAMES.get(request_kind, "공식 검색 결과")
    unknown_count = sum(
        item.get("match_scope") == "unknown" or item.get("evidence_status") == "unverified" for item in displayed
    )
    nearby_only = bool(displayed) and all(item.get("match_scope") == "nearby" for item in displayed)
    if source_status == SearchStatus.PARTIAL:
        detail = (
            " 그중 조건 근거가 부족한 결과는 공식 원문을 확인해 주세요."
            if unknown_count
            else " 자세한 내용은 아래 카드에서 확인해 주세요."
        )
        return _with_companion_cta(
            f"일부 조회가 완료되지 않았지만 현재 확인된 {source_name} 카드 {count}건을 준비했어요.{detail}",
            companion_sources,
        )
    if unknown_count == count and count:
        return _with_companion_cta(
            f"일부 조건의 확인 근거가 부족한 {source_name} 참고 카드 {count}건을 찾았어요. "
            "신청·지원 조건은 공식 원문에서 확인해 주세요.",
            companion_sources,
        )
    if unknown_count:
        return _with_companion_cta(
            f"{source_name} 카드 {count}건을 찾았어요. "
            f"그중 {unknown_count}건은 조건 근거가 부족한 참고 결과이므로 공식 원문을 확인해 주세요.",
            companion_sources,
        )
    if nearby_only:
        return _with_companion_cta(
            f"요청 지역의 직접 결과 대신 가까운 지역의 {source_name} 참고 카드 {count}건을 찾았어요. "
            "실제 거주 요건을 확인하며 아래 카드를 살펴봐 주세요.",
            companion_sources,
        )
    return _with_companion_cta(
        f"조건에 맞는 {source_name} 카드 {count}건을 찾았어요. 자세한 내용은 아래 카드에서 확인해 주세요.",
        companion_sources,
    )

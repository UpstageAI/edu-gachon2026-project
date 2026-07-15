import math
import re
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, Optional, TypedDict, Union

from loguru import logger

from app.agents.domain_guardrail import classify_domain
from app.core.observability import (
    DEFAULT_TOP_K,
    mask_sensitive_text,
    start_observation,
    summarize_documents,
)
from app.core.llm import LLM_FAILURE_MESSAGE, LLMError, generate_text
from app.core.routing import (
    EXACT_DISTANCE_THRESHOLD,
    RELATED_DISTANCE_THRESHOLD,
    AnswerRoute,
    DomainGuardrailResult,
)
from app.schemas.document import RetrievedDocument


BLOCKED_ANSWER = (
    "이 서비스는 법제처 생활법령 백문백답을 바탕으로 일반 정보를 안내하는 서비스입니다.\n"
    "개별 사건의 승소 가능성 판단, 법률문서 작성, 구체적 법률 자문은 제공하지 않습니다.\n"
    "필요한 경우 대한법률구조공단 등 전문기관 상담을 이용해 주세요."
)

FALLBACK_ANSWER = "관련 정보를 충분히 찾지 못했습니다. 질문을 조금 더 구체적으로 입력해 주세요."
LEGAL_NOTICE = "이 답변은 일반 정보 제공이며 법률 자문이 아닙니다."
OUT_OF_SCOPE_ANSWER = (
    "현재 서비스는 부동산/임대차와 복지 분야의 생활법률 정보만 안내합니다.\n"
    "질문하신 내용은 현재 지원 범위 밖으로 판단되어 답변을 생성하지 않았습니다.\n"
    "지원 분야에 해당하는 질문이라면 부동산/임대차 또는 복지 제도와 관련된 내용을 함께 입력해 주세요."
)
GENERAL_KNOWLEDGE_WARNING = (
    "현재 보유한 생활법령 데이터에서 질문에 직접 대응하는 근거를 찾지 못해, "
    "아래 안내는 Solar Pro 모델의 일반지식을 바탕으로 작성되었습니다. "
    "정확하지 않거나 최신 제도와 다를 수 있으므로 공식 기관에서 다시 확인해 주세요."
)
GENERATION_SYSTEM_PROMPT = (
    "너는 법제처 생활법령 백문백답 기반 생활법률 안내 챗봇이다.\n"
    "규칙:\n"
    "- 제공된 검색 근거 안에서 확인되는 내용만 사용한다.\n"
    "- 답변 첫 1~2문장에 사용자 질문에 대한 핵심 결론을 먼저 제시한다.\n"
    "- 사용자가 이미 말한 조건을 길게 반복하지 않는다.\n"
    "- 현재 [사용자 질문]에 명시된 내용만 사용자의 개인 조건으로 취급한다.\n"
    "- 사용자 질문에 개인 조건이 없으면 검색 근거의 특정 예시 하나를 답변의 기준으로 선택하지 않는다.\n"
    "- 검색 근거에 등장하는 예시 인물, 출생연도, 나이, 금액은 사용자 질문에 같은 조건이 명시되지 않았다면 사용자에게 직접 적용하지 않는다.\n"
    "- 검색 근거의 예시는 필요할 때만 '예를 들어'라고 명시해 보조 설명으로 사용한다.\n"
    "- 필요한 개인 조건이 질문에 없으면 임의로 추정하지 말고, 해당 조건에 따라 결과가 달라진다고 설명한다.\n"
    "- 추가 조건이 필요하면 해당 조건을 포함해 질문 전체를 다시 입력하도록 안내한다.\n"
    "- 현재 서비스가 이전 대화 맥락을 기억한다고 가정하지 않는다.\n"
    "- '알려주시면', '말씀해 주세요', '추가로 문의해 주세요'처럼 후속 대화가 이어지는 표현은 쓰지 않는다.\n"
    "- 자격·수급 여부에 추가 조건이 있으면 첫 문장부터 조건부로 표현한다.\n"
    "- 단순 질문에는 고정된 4단계 형식을 강제하지 않고 자연스러운 단락이나 목록으로 답한다.\n"
    "- 복합 질문은 필요한 항목만 나눠 빠짐없이 답한다.\n"
    "- 검색 근거의 주변 내용 중 질문 해결에 필요하지 않은 예시와 제도는 생략하되, 핵심 답을 이해하는 데 필요한 조건과 예외는 간단히 설명한다.\n"
    "- 사용자가 전체 비교를 요청하지 않으면 긴 표나 모든 구간을 나열하지 않는다.\n"
    "- 질문 해결에 직접 필요하지 않은 주변 제도, 예외, 감액 세부사항은 생략한다.\n"
    "- 단순 질문은 2~3개의 짧은 문단으로 답하고, 목록은 필요한 경우 최대 3개 항목을 우선한다.\n"
    "- 같은 내용을 문장과 목록으로 반복하지 않는다.\n"
    "- 근거에 없는 날짜, 금액, 법 조문, 기관 절차는 만들지 않는다.\n"
    "- 개인의 정확한 수급 여부나 법적 결론은 단정하지 않는다.\n"
    "- 법률·행정 용어는 필요한 경우 짧게 풀이한다.\n"
    "- source URL, 관련 질문, 공식 기관 안내, 법률 자문 고지는 직접 생성하지 않는다."
)
RELATED_HYBRID_SYSTEM_PROMPT = (
    "너는 생활법률 안내 챗봇이다.\n"
    "규칙:\n"
    "- 현재 데이터셋에 직접 근거가 부족하다는 전제를 유지한다.\n"
    "- 답변은 일반지식 기반의 제한적 안내로 작성한다.\n"
    "- 첫 문단에서 사용자가 확인해야 할 방향을 짧게 제시한다.\n"
    "- 사용자가 이미 말한 조건을 길게 반복하거나 질문형으로 되묻지 않는다.\n"
    "- 다음 행동은 중요한 1~3개만 안내한다.\n"
    "- 실제 웹 검색을 한 것처럼 표현하지 않는다.\n"
    "- URL, 출처 링크, 존재 여부를 확인하지 않은 기관명은 만들지 않는다.\n"
    "- 관련 질문 목록과 공식 기관 안내는 애플리케이션 코드가 붙이므로 직접 생성하지 않는다.\n"
    "- 최신 금액, 소득기준, 신청기한, 법 조문은 단정하지 않는다.\n"
    "- 확정적 법률 자문처럼 단정하지 않는다."
)
LLM_ONLY_SYSTEM_PROMPT = (
    "너는 생활법률 안내 챗봇이다.\n"
    "규칙:\n"
    "- 답변은 일반지식 기반임을 전제로 한다.\n"
    "- 첫 문단에서 사용자가 확인해야 할 방향을 짧게 제시한다.\n"
    "- 사용자가 이미 말한 조건을 길게 반복하거나 질문형으로 되묻지 않는다.\n"
    "- 다음 행동은 중요한 1~3개만 안내한다.\n"
    "- 구체 URL을 만들지 않는다.\n"
    "- 최신 금액, 소득기준, 연령, 신청기한, 법 조문은 단정하지 않는다.\n"
    "- 존재 여부가 불확실한 기관이나 제도는 만들지 않는다.\n"
    "- warning, 공식 기관 안내, 법률 자문 고지는 애플리케이션 코드가 붙이므로 직접 반복하지 않는다.\n"
    "- 확정적 법률 자문처럼 표현하지 않는다."
)
# 고지문은 LLM에게 시키지 않고 코드가 부착한다 —
# sync는 output_guardrail, stream은 chat.py의 tail 전송이 담당한다.
# (본문 → 원문 링크 → 고지문 순서를 두 경로에서 동일하게 보장하기 위함)

SOURCE_LINK_TEMPLATE = "더 도움이 필요하시면 {url} 에서 추가 정보를 확인할 수 있습니다."
RELATED_SUGGESTION_INTRO = (
    "현재 데이터에서 질문에 직접 답할 수 있는 자료는 찾지 못했지만, "
    "아래 관련 주제는 생활법령 자료를 기반으로 안내할 수 있습니다."
)

DANGEROUS_PHRASES = (
    "승소",
    "이길 수",
    "소장 좀 써",
    "소장 작성",
    "고소장 써",
    "고소장 작성",
    "계약서 써줘",
    "계약서 작성해줘",
    "주민등록번호",
    "계좌번호",
    "시스템 프롬프트",
    "이전 지시 무시",
    "개발자 지시",
)


class AgentState(TypedDict, total=False):
    message: str
    thread_id: Optional[str]
    category: str
    documents: list[RetrievedDocument]
    exact_documents: list[RetrievedDocument]
    related_documents: list[RetrievedDocument]
    out_of_range_documents: list[RetrievedDocument]
    answer: str
    guardrail_blocked: bool
    is_fallback: bool
    retrieved_count: int
    response_type: str
    warning: Optional[str]
    suggested_questions: list[dict[str, str]]
    sources: list[dict[str, str]]
    is_grounded: bool
    domain_guardrail_result: str
    domain_category: str
    guardrail_reason: str
    domain_keyword_hits: list[str]
    extended_domain_hits: list[str]
    context_keyword_hits: list[str]
    out_of_scope_hits: list[str]
    best_distance: Optional[float]
    top1_distance: Optional[float]
    top2_distance: Optional[float]
    top3_distance: Optional[float]
    top1_document_id: Optional[str]
    top2_document_id: Optional[str]
    top3_document_id: Optional[str]
    exact_document_count: int
    related_document_count: int
    use_raw_search: bool


def scope_check(state: AgentState) -> AgentState:
    message = state.get("message", "")
    started_at = perf_counter()
    normalized_message = message.casefold()
    is_blocked = any(phrase.casefold() in normalized_message for phrase in DANGEROUS_PHRASES)
    _record_guardrail_trace(message, is_blocked, _duration_ms(started_at))

    return {
        **state,
        "guardrail_blocked": is_blocked,
        "category": "차단" if is_blocked else state.get("category", "기타"),
    }


def guardrail_exit(state: AgentState) -> AgentState:
    return {
        **state,
        "answer": BLOCKED_ANSWER,
        "category": "차단",
        "documents": [],
        "guardrail_blocked": True,
        "is_fallback": False,
        "retrieved_count": 0,
        "response_type": AnswerRoute.OUT_OF_SCOPE.value,
        "is_grounded": False,
    }


def domain_guardrail(state: AgentState) -> AgentState:
    message = state.get("message", "")
    started_at = perf_counter()
    decision = classify_domain(message)
    _record_domain_guardrail_trace(message, decision, _duration_ms(started_at))

    return {
        **state,
        "domain_guardrail_result": decision.result.value,
        "domain_category": decision.domain_category,
        "guardrail_reason": decision.reason,
        "domain_keyword_hits": list(decision.domain_keyword_hits),
        "extended_domain_hits": list(decision.extended_domain_hits),
        "context_keyword_hits": list(decision.context_keyword_hits),
        "out_of_scope_hits": list(decision.out_of_scope_hits),
    }


def out_of_scope_response(state: AgentState) -> AgentState:
    return {
        **state,
        "answer": OUT_OF_SCOPE_ANSWER,
        "category": "지원범위밖",
        "documents": state.get("documents", []),
        "guardrail_blocked": True,
        "is_fallback": False,
        "retrieved_count": state.get("retrieved_count", 0),
        "response_type": AnswerRoute.OUT_OF_SCOPE.value,
        "warning": None,
        "suggested_questions": [],
        "sources": [],
        "is_grounded": False,
    }


def retrieve(state: AgentState) -> AgentState:
    message = state.get("message", "")
    started_at = perf_counter()
    search = _search_law_qa_raw if state.get("use_raw_search") else _search_law_qa
    documents = search(message)
    _record_retrieval_trace(message, documents, _duration_ms(started_at))
    category = documents[0].category if documents else "기타"

    return {
        **state,
        "documents": documents,
        "category": category,
        "retrieved_count": len(documents),
    }


def decide_route(state: AgentState) -> AgentState:
    documents = state.get("documents", [])
    exact_documents, related_documents, out_of_range_documents = _split_documents_by_distance(
        documents
    )
    best_distance = _best_distance(documents)
    top_k_summary = _top_k_summary(documents)
    guardrail_result = state.get("domain_guardrail_result", DomainGuardrailResult.UNCERTAIN.value)
    guardrail_reason = state.get("guardrail_reason", "uncertain")

    if guardrail_result == DomainGuardrailResult.UNCERTAIN.value:
        if best_distance is not None and best_distance <= RELATED_DISTANCE_THRESHOLD:
            guardrail_result = DomainGuardrailResult.IN_SCOPE.value
            guardrail_reason = "uncertain_vector_pass"
        else:
            guardrail_result = DomainGuardrailResult.OUT_OF_SCOPE.value
            guardrail_reason = "uncertain_vector_fail"

    if guardrail_result == DomainGuardrailResult.OUT_OF_SCOPE.value:
        route = AnswerRoute.OUT_OF_SCOPE
        routed_documents: list[RetrievedDocument] = []
    elif exact_documents:
        route = AnswerRoute.GROUNDED_RAG
        routed_documents = exact_documents
    elif related_documents:
        route = AnswerRoute.RELATED_HYBRID
        routed_documents = related_documents
    else:
        route = AnswerRoute.LLM_ONLY
        routed_documents = []

    suggested_questions = _build_suggested_questions(related_documents, state.get("message", ""))
    _record_route_decision_trace(
        route=route,
        state=state,
        guardrail_result=guardrail_result,
        guardrail_reason=guardrail_reason,
        best_distance=best_distance,
        exact_count=len(exact_documents),
        related_count=len(related_documents),
        suggestion_count=len(suggested_questions),
        top_k_summary=top_k_summary,
    )

    return {
        **state,
        "documents": routed_documents,
        "exact_documents": exact_documents,
        "related_documents": related_documents,
        "out_of_range_documents": out_of_range_documents,
        "domain_guardrail_result": guardrail_result,
        "guardrail_reason": guardrail_reason,
        "best_distance": best_distance,
        **top_k_summary,
        "exact_document_count": len(exact_documents),
        "related_document_count": len(related_documents),
        "response_type": route.value,
        "is_grounded": route == AnswerRoute.GROUNDED_RAG,
        "suggested_questions": suggested_questions,
        "warning": GENERAL_KNOWLEDGE_WARNING
        if route in {AnswerRoute.RELATED_HYBRID, AnswerRoute.LLM_ONLY}
        else None,
        "sources": _build_sources(exact_documents) if route == AnswerRoute.GROUNDED_RAG else [],
    }


def generate(state: AgentState) -> AgentState:
    route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
    documents = state.get("documents", [])
    if route == AnswerRoute.OUT_OF_SCOPE.value:
        return out_of_scope_response(state)
    if route == AnswerRoute.GROUNDED_RAG.value and not documents:
        return fallback_response(state)

    try:
        answer = _generate_by_route(state, route, documents)
    except LLMError:
        # 재시도·대체 모델 체인까지 전부 실패한 경우. 고정 문구는 LLM output이
        # 아니므로 generation observation이 아닌 이 상위 계층에서 응답으로
        # 변환한다 (Langfuse 유지 조건 7 — llm.py에서 반환하면 위반).
        return _llm_failure_response(state)

    return {
        **state,
        "answer": answer,
        "category": documents[0].category if documents else _category_from_domain(state),
        "guardrail_blocked": False,
        "is_fallback": False,
        "retrieved_count": len(documents),
    }


def _llm_failure_response(state: AgentState) -> AgentState:
    """LLM 최종 실패 fallback — 공통_작업지시 6절의 'LLM 실패' 응답 계약."""
    return {
        **state,
        "answer": LLM_FAILURE_MESSAGE,
        "category": "기타",
        "documents": [],
        "guardrail_blocked": False,
        "is_fallback": True,
        "retrieved_count": 0,
        "response_type": AnswerRoute.ERROR.value,
        "is_grounded": False,
    }


def build_source_link_line(documents: list[RetrievedDocument]) -> Optional[str]:
    """검색 top-1 문서의 원문 링크 문구를 만든다. sync/stream 공용 (문구 단일 정의).

    링크를 얻지 못하는 모든 경우(문서 없음, source_url 없음, 저장소 예외)에
    None을 반환해 답변 반환을 막지 않는다. 예외는 warning 로그만 남긴다.
    """
    if not documents:
        return None
    if documents[0].source_url:
        return SOURCE_LINK_TEMPLATE.format(url=documents[0].source_url)
    try:
        from app.repositories.chroma_law_repository import get_source_url

        url = get_source_url(documents[0].id)
    except Exception as exc:
        logger.warning("원문 링크 조회 실패 — 링크 없이 답변을 반환한다: {}", exc)
        return None
    if not url:
        return None
    return SOURCE_LINK_TEMPLATE.format(url=url)


def output_guardrail(state: AgentState) -> AgentState:
    if state.get("guardrail_blocked") or state.get("is_fallback"):
        return state

    route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
    answer = state.get("answer", "").strip()
    # 본문 → 링크 → 고지문 순서를 보장하기 위해, LLM이 임의로 넣은 고지문은
    # 떼어낸 뒤 마지막에 다시 부착한다.
    if LEGAL_NOTICE in answer:
        answer = answer.replace(LEGAL_NOTICE, "").strip()

    if route in {AnswerRoute.RELATED_HYBRID.value, AnswerRoute.LLM_ONLY.value}:
        answer = _strip_unverified_urls(answer)
        parts = []
        warning = state.get("warning") or GENERAL_KNOWLEDGE_WARNING
        parts.append(warning)
        if answer:
            parts.append(answer)
        parts.append(_official_institution_line(state.get("domain_category", "unknown")))
        suggestion_text = _format_suggested_questions(state.get("suggested_questions", []))
        if suggestion_text:
            parts.append(suggestion_text)
    else:
        parts = [answer]
        link_line = build_source_link_line(state.get("documents", []))
        if link_line:
            parts.append(link_line)
    parts.append(LEGAL_NOTICE)

    return {
        **state,
        "answer": "\n\n".join(parts),
        "guardrail_blocked": False,
        "is_fallback": False,
        "warning": state.get("warning"),
        "sources": _build_sources(state.get("documents", [])) if route == AnswerRoute.GROUNDED_RAG.value else [],
    }


def fallback_response(state: AgentState) -> AgentState:
    return {
        **state,
        "answer": FALLBACK_ANSWER,
        "category": "기타",
        "documents": [],
        "guardrail_blocked": False,
        "is_fallback": True,
        "retrieved_count": 0,
        "response_type": AnswerRoute.ERROR.value,
        "is_grounded": False,
    }


def _generate_by_route(
    state: AgentState,
    route: str,
    documents: list[RetrievedDocument],
) -> str:
    message = state.get("message", "")
    if route == AnswerRoute.RELATED_HYBRID.value:
        return generate_text(
            prompt=_build_related_hybrid_prompt(message, documents),
            system=RELATED_HYBRID_SYSTEM_PROMPT,
        )
    if route == AnswerRoute.LLM_ONLY.value:
        return generate_text(
            prompt=_build_llm_only_prompt(message, state.get("domain_category", "unknown")),
            system=LLM_ONLY_SYSTEM_PROMPT,
        )
    return generate_text(
        prompt=_build_generation_prompt(message, documents),
        system=GENERATION_SYSTEM_PROMPT,
    )


def _split_documents_by_distance(
    documents: list[RetrievedDocument],
) -> tuple[list[RetrievedDocument], list[RetrievedDocument], list[RetrievedDocument]]:
    exact_documents = []
    related_documents = []
    out_of_range_documents = []

    for document in documents:
        distance = _valid_distance(document)
        if distance is None:
            out_of_range_documents.append(document)
        elif distance <= EXACT_DISTANCE_THRESHOLD:
            exact_documents.append(document)
        elif distance <= RELATED_DISTANCE_THRESHOLD:
            related_documents.append(document)
        else:
            out_of_range_documents.append(document)

    return exact_documents, related_documents, out_of_range_documents


def _best_distance(documents: list[RetrievedDocument]) -> Optional[float]:
    distances = [
        distance for document in documents if (distance := _valid_distance(document)) is not None
    ]
    if not distances:
        return None
    return min(distances)


def _top_k_summary(documents: list[RetrievedDocument]) -> dict[str, Optional[float] | Optional[str]]:
    summary: dict[str, Optional[float] | Optional[str]] = {
        "top1_distance": None,
        "top2_distance": None,
        "top3_distance": None,
        "top1_document_id": None,
        "top2_document_id": None,
        "top3_document_id": None,
    }
    for index, document in enumerate(documents[:DEFAULT_TOP_K], start=1):
        summary[f"top{index}_distance"] = _valid_distance(document)
        summary[f"top{index}_document_id"] = document.id
    return summary


def _valid_distance(document: RetrievedDocument) -> Optional[float]:
    distance = document.distance
    if distance is None or not isinstance(distance, (int, float)):
        return None
    if math.isnan(float(distance)):
        return None
    return float(distance)


def _build_suggested_questions(
    documents: list[RetrievedDocument],
    original_question: str,
    limit: int = 3,
) -> list[dict[str, str]]:
    normalized_original = _normalize_for_compare(original_question)
    suggestions = []
    seen = set()
    for document in documents:
        question = document.question.strip()
        normalized_question = _normalize_for_compare(question)
        if not question or normalized_question == normalized_original or normalized_question in seen:
            continue
        seen.add(normalized_question)
        suggestions.append(
            {
                "source_document_id": document.id,
                "source_question": question,
                "suggested_question": question,
            }
        )
        if len(suggestions) >= limit:
            break
    return suggestions


def _normalize_for_compare(text: str) -> str:
    return re.sub(r"\s+", "", text.casefold())


def _format_suggested_questions(suggested_questions: list[dict[str, str]]) -> Optional[str]:
    if not suggested_questions:
        return None
    lines = [RELATED_SUGGESTION_INTRO]
    lines.extend(f"- {item['suggested_question']}" for item in suggested_questions)
    return "\n".join(lines)


def _official_institution_line(domain_category: str) -> str:
    institutions = _official_institutions(domain_category)
    if not institutions:
        return "정확한 적용 여부는 거주지 주민센터 또는 해당 제도의 담당 공공기관에 확인해 주세요."
    return f"정확한 적용 여부는 {' 또는 '.join(institutions)}에 확인해 주세요."


def _official_institutions(domain_category: str) -> list[str]:
    if domain_category == "real_estate_rental":
        return ["법제처 찾기 쉬운 생활법령정보", "국토교통부"]
    if domain_category == "welfare":
        return ["보건복지부", "복지로"]
    if domain_category == "mixed":
        return ["법제처 찾기 쉬운 생활법령정보", "거주지 읍·면·동 주민센터"]
    return []


def _strip_unverified_urls(text: str) -> str:
    return re.sub(r"https?://\S+", "[검증되지 않은 URL 제거]", text)


def _build_sources(documents: list[RetrievedDocument]) -> list[dict[str, str]]:
    sources = []
    for document in documents:
        source = {
            "id": document.id,
            "question": document.question,
            "category": document.category,
        }
        if document.source_url:
            source["source_url"] = document.source_url
        sources.append(source)
    return sources


def _category_from_domain(state: AgentState) -> str:
    domain_category = state.get("domain_category")
    if domain_category == "real_estate_rental":
        return "부동산/임대차"
    if domain_category == "welfare":
        return "복지"
    if domain_category == "mixed":
        return "혼합"
    return "기타"


def _record_guardrail_trace(message: str, is_blocked: bool, duration_ms: float) -> None:
    with start_observation(
        name="guardrail",
        as_type="span",
        input={"question": mask_sensitive_text(message)},
        metadata={"rule_count": len(DANGEROUS_PHRASES), "duration_ms": duration_ms},
    ) as observation:
        observation.update(
            output={"result": "blocked" if is_blocked else "allow"},
            metadata={"reason": "dangerous_phrase" if is_blocked else "none"},
        )


def _record_domain_guardrail_trace(message: str, decision, duration_ms: float) -> None:
    with start_observation(
        name="domain_guardrail",
        as_type="guardrail",
        input={"question": mask_sensitive_text(message)},
        metadata={
            "duration_ms": duration_ms,
            "domain_category": decision.domain_category,
            "guardrail_reason": decision.reason,
            "domain_keyword_hits": list(decision.domain_keyword_hits),
            "extended_domain_hits": list(decision.extended_domain_hits),
            "context_keyword_hits": list(decision.context_keyword_hits),
            "out_of_scope_hits": list(decision.out_of_scope_hits),
        },
    ) as observation:
        observation.update(output={"result": decision.result.value})


def _record_retrieval_trace(
    message: str,
    documents: list[RetrievedDocument],
    duration_ms: float,
) -> None:
    with start_observation(
        name="retrieval",
        as_type="span",
        input={"query": mask_sensitive_text(message), "top_k": DEFAULT_TOP_K},
        metadata={
            "repository": "app.agents.nodes._search_law_qa",
            "duration_ms": duration_ms,
        },
    ) as observation:
        observation.update(
            output={
                "retrieved_count": len(documents),
                "documents": summarize_documents(documents),
            },
            metadata={"no_result": len(documents) == 0},
        )


def _record_route_decision_trace(
    *,
    route: AnswerRoute,
    state: AgentState,
    guardrail_result: str,
    guardrail_reason: str,
    best_distance: Optional[float],
    exact_count: int,
    related_count: int,
    suggestion_count: int,
    top_k_summary: dict[str, Optional[float] | Optional[str]],
) -> None:
    with start_observation(
        name="route_decision",
        as_type="span",
        input={
            "guardrail_result": guardrail_result,
            "retrieved_count": state.get("retrieved_count", 0),
        },
        metadata={
            "response_type": route.value,
            "domain_category": state.get("domain_category", "unknown"),
            "guardrail_reason": guardrail_reason,
            "domain_keyword_hits": state.get("domain_keyword_hits", []),
            "context_keyword_hits": state.get("context_keyword_hits", []),
            "best_distance": best_distance,
            "top1_distance": top_k_summary["top1_distance"],
            "top2_distance": top_k_summary["top2_distance"],
            "top3_distance": top_k_summary["top3_distance"],
            "top1_document_id": top_k_summary["top1_document_id"],
            "top2_document_id": top_k_summary["top2_document_id"],
            "top3_document_id": top_k_summary["top3_document_id"],
            "exact_threshold": EXACT_DISTANCE_THRESHOLD,
            "related_threshold": RELATED_DISTANCE_THRESHOLD,
            "retrieved_count": state.get("retrieved_count", 0),
            "exact_document_count": exact_count,
            "related_document_count": related_count,
            "grounded": route == AnswerRoute.GROUNDED_RAG,
            "llm_general_knowledge_used": route
            in {AnswerRoute.RELATED_HYBRID, AnswerRoute.LLM_ONLY},
            "suggestion_count": suggestion_count,
        },
    ) as observation:
        observation.update(output={"route": route.value})


def _duration_ms(started_at: float) -> float:
    return round((perf_counter() - started_at) * 1000, 2)


def _search_law_qa(query: str) -> list[RetrievedDocument]:
    repositories_dir = Path(__file__).resolve().parents[1] / "repositories"

    chroma_repository_path = repositories_dir / "chroma_law_repository.py"
    if chroma_repository_path.exists():
        from app.repositories.chroma_law_repository import search_law_qa

        return [_coerce_document(document) for document in search_law_qa(query)]

    mock_repository_path = repositories_dir / "mock_law_repository.py"
    if not mock_repository_path.exists():
        return _temporary_search_law_qa(query)

    from app.repositories.mock_law_repository import search_law_qa

    return [_coerce_document(document, default_distance=0.0) for document in search_law_qa(query)]


def _search_law_qa_raw(query: str) -> list[RetrievedDocument]:
    repositories_dir = Path(__file__).resolve().parents[1] / "repositories"

    chroma_repository_path = repositories_dir / "chroma_law_repository.py"
    if chroma_repository_path.exists():
        from app.repositories.chroma_law_repository import search_law_qa_raw

        return [_coerce_document(document) for document in search_law_qa_raw(query)]

    mock_repository_path = repositories_dir / "mock_law_repository.py"
    if not mock_repository_path.exists():
        return _temporary_search_law_qa(query)

    from app.repositories.mock_law_repository import search_law_qa

    return [_coerce_document(document, default_distance=0.0) for document in search_law_qa(query)]


def _coerce_document(
    document: Union[RetrievedDocument, Dict[str, Any]],
    default_distance: Optional[float] = None,
) -> RetrievedDocument:
    if isinstance(document, RetrievedDocument):
        if document.distance is None and default_distance is not None:
            return document.model_copy(update={"distance": default_distance})
        return document
    if "distance" not in document and default_distance is not None:
        document = {**document, "distance": default_distance}
    return RetrievedDocument(**document)


def _temporary_search_law_qa(query: str) -> list[RetrievedDocument]:
    # TODO: 역할 B의 app.repositories.mock_law_repository.search_law_qa 병합 후 제거한다.
    mock_documents = [
        RetrievedDocument(
            id="rent_001",
            category="임대차",
            question="전월세 계약 전 확인할 사항은 무엇인가요?",
            answer="등기부등본 확인, 계약 당사자 확인, 전입신고와 확정일자 확인이 필요합니다.",
        ),
        RetrievedDocument(
            id="rent_002",
            category="임대차",
            question="전세 계약서에서 확인할 사항은 무엇인가요?",
            answer="임대인과 임차인 정보, 보증금과 월세, 계약 기간, 특약 사항을 확인할 수 있습니다.",
        ),
        RetrievedDocument(
            id="labor_001",
            category="근로",
            question="임금이 밀리면 어떻게 해야 하나요?",
            answer="임금체불이 발생한 경우 사업주에게 지급을 요청하고, 해결되지 않으면 고용노동부 진정 절차를 확인할 수 있습니다.",
        ),
        RetrievedDocument(
            id="welfare_001",
            category="복지",
            question="기초생활보장 급여는 어디서 확인하나요?",
            answer="주소지 관할 읍면동 주민센터 또는 복지로에서 신청 자격과 급여 종류를 확인할 수 있습니다.",
        ),
    ]

    query_keywords = _extract_query_keywords(query)
    if not query_keywords:
        return []

    scored_documents = [
        (document, _score_document(document, query_keywords)) for document in mock_documents
    ]
    return [document for document, score in scored_documents if score > 0]


def _extract_query_keywords(query: str) -> set[str]:
    normalized_query = query.casefold()
    keyword_groups = {
        "월세": "임대차",
        "전세": "임대차",
        "전월세": "임대차",
        "임대차": "임대차",
        "보증금": "임대차",
        "확정일자": "임대차",
        "계약 전": "임대차",
        "계약서": "임대차",
        "임금": "근로",
        "월급": "근로",
        "체불": "근로",
        "노동청": "근로",
        "근로": "근로",
        "해고": "근로",
        "기초생활": "복지",
        "복지": "복지",
        "급여": "복지",
    }

    return {category for keyword, category in keyword_groups.items() if keyword in normalized_query}


def _score_document(document: RetrievedDocument, query_keywords: set[str]) -> int:
    score = 0
    if document.category in query_keywords:
        score += 2

    text = f"{document.question} {document.answer}".casefold()
    score += sum(1 for keyword in query_keywords if keyword in text)
    return score


def _build_generation_prompt(message: str, documents: list[RetrievedDocument]) -> str:
    evidence = "\n\n".join(
        (
            f"{index}. 분야: {document.category}\n"
            f"   질문: {document.question}\n"
            f"   답변: {document.answer}"
        )
        for index, document in enumerate(documents, start=1)
    )

    return (
        "[사용자 질문]\n"
        f"{message}\n\n"
        "[검색된 근거]\n"
        f"{evidence}\n\n"
        "[중요한 구분]\n"
        "- 검색 근거는 법률 정보를 설명하는 자료이며, 그 안에 등장하는 예시 조건은 현재 사용자의 개인정보가 아니다.\n"
        "- 검색 근거에 등장하는 예시 인물, 출생연도, 나이, 금액은 현재 사용자 질문에 같은 조건이 명시되지 않았다면 사용자 정보가 아니다.\n"
        "- 현재 사용자 질문에 없는 개인 조건을 검색 근거의 예시에서 가져오지 않는다.\n"
        "- 사용자가 질문한 범위에 필요한 내용만 선택한다.\n\n"
        "[답변 지시]\n"
        "1. 사용자가 실제로 물은 각 항목에 답한다.\n"
        "2. 검색된 근거에서 확인되는 내용만 사용한다.\n"
        "3. 첫 1~2문장에 핵심 답을 먼저 쓴다.\n"
        "4. 필요한 개인 조건이 없으면 조건부로 설명한다.\n"
        "5. 추가 조건이 필요하면 질문 전체를 다시 입력하도록 안내한다.\n"
        "6. 질문하지 않은 주변 제도·예외·감액 세부사항은 생략한다.\n"
        "7. 자격이나 수급 여부는 조건을 포함해 표현한다.\n"
        "8. 단순 질문은 짧은 2~3개 문단으로 작성한다.\n"
        "9. source URL, 공식 기관 안내, 관련 질문, 법률 고지는 직접 쓰지 않는다."
    )


def _build_related_hybrid_prompt(message: str, documents: list[RetrievedDocument]) -> str:
    return (
        "[사용자 질문]\n"
        f"{message}\n\n"
        "[상황]\n"
        "현재 데이터셋에서 사용자 질문에 직접 답할 수 있는 근거 문서를 찾지 못했다.\n\n"
        "[답변 지시]\n"
        "1. 일반적인 확인 방향만 2~3개 안내한다.\n"
        "2. 특정 증명서, 신청 절차, 기관, 법적 효과를 새로 단정하지 않는다.\n"
        "3. 최신 금액, 소득기준, 신청기한, 법 조문은 단정하지 않는다.\n"
        "4. URL을 만들지 않는다.\n"
        "5. 관련 질문 목록은 애플리케이션이 별도로 표시하므로 참고하거나 언급하지 않는다."
    )


def _build_llm_only_prompt(message: str, domain_category: str) -> str:
    return (
        "[사용자 질문]\n"
        f"{message}\n\n"
        "[지원 분야]\n"
        f"{domain_category}\n\n"
        "[상황]\n"
        "현재 데이터셋에서 질문에 대응하는 근거 문서를 찾지 못했다.\n\n"
        "[답변 지시]\n"
        "1. 일반지식 기반의 제한적 안내로 작성한다.\n"
        "2. 구체 URL을 만들지 않는다.\n"
        "3. 최신 금액, 소득기준, 신청기한, 법 조문은 단정하지 않는다.\n"
        "4. 다음 확인 행동은 중요한 1~3개만 안내한다.\n"
        "5. warning, 공식 기관 안내, 법률 자문 고지는 직접 쓰지 않는다.\n"
        "6. 확정적 법률 자문처럼 단정하지 않는다."
    )

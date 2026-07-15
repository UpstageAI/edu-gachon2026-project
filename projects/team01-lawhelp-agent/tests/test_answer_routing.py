import math

import pytest

from app.agents.nodes import decide_route, output_guardrail
from app.core import observability
from app.core.routing import (
    EXACT_DISTANCE_THRESHOLD,
    RELATED_DISTANCE_THRESHOLD,
    AnswerRoute,
)
from app.schemas.document import RetrievedDocument


def _document(
    document_id: str,
    distance: float | None,
    question: str = "관련 질문",
) -> RetrievedDocument:
    return RetrievedDocument(
        id=document_id,
        category="부동산/임대차",
        question=question,
        answer="답변",
        distance=distance,
        source_url=f"https://example.test/{document_id}",
    )


def _decide(
    *,
    distance: float | None,
    guardrail_result: str = "in_scope",
) -> dict:
    documents = [] if distance is None else [_document("law_1", distance)]
    return decide_route(
        {
            "message": "전세 계약 질문",
            "documents": documents,
            "retrieved_count": len(documents),
            "domain_guardrail_result": guardrail_result,
            "domain_category": "real_estate_rental",
            "guardrail_reason": "test",
        }
    )


@pytest.mark.parametrize(
    ("distance", "expected_route"),
    [
        # 임계값 상수 기준 경계 검증 — 상수가 조정되어도 경계 의미는 유지된다
        (EXACT_DISTANCE_THRESHOLD, AnswerRoute.GROUNDED_RAG.value),
        (EXACT_DISTANCE_THRESHOLD + 0.0001, AnswerRoute.RELATED_HYBRID.value),
        (RELATED_DISTANCE_THRESHOLD, AnswerRoute.RELATED_HYBRID.value),
        (RELATED_DISTANCE_THRESHOLD + 0.000001, AnswerRoute.LLM_ONLY.value),
    ],
)
def test_route_decision_distance_boundaries(monkeypatch, distance, expected_route):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = _decide(distance=distance, guardrail_result="in_scope")

    assert state["response_type"] == expected_route


@pytest.mark.parametrize(
    ("distance", "expected_route", "expected_reason"),
    [
        (0.55, AnswerRoute.RELATED_HYBRID.value, "uncertain_vector_pass"),
        (0.70, AnswerRoute.OUT_OF_SCOPE.value, "uncertain_vector_fail"),
    ],
)
def test_uncertain_guardrail_uses_vector_distance(
    monkeypatch,
    distance,
    expected_route,
    expected_reason,
):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = _decide(distance=distance, guardrail_result="uncertain")

    assert state["response_type"] == expected_route
    assert state["guardrail_reason"] == expected_reason


def test_uncertain_guardrail_without_documents_routes_out_of_scope(monkeypatch):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = decide_route(
        {
            "message": "이건 지원 분야인지 애매해요",
            "documents": [],
            "retrieved_count": 0,
            "domain_guardrail_result": "uncertain",
            "domain_category": "unknown",
            "guardrail_reason": "uncertain",
        }
    )

    assert state["response_type"] == AnswerRoute.OUT_OF_SCOPE.value
    assert state["guardrail_reason"] == "uncertain_vector_fail"


@pytest.mark.parametrize("distance", [None, math.nan])
def test_invalid_distance_is_ignored_without_breaking_route(monkeypatch, distance):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)
    documents = [] if distance is None else [_document("law_nan", distance)]

    state = decide_route(
        {
            "message": "전세 계약 질문",
            "documents": documents,
            "retrieved_count": len(documents),
            "domain_guardrail_result": "in_scope",
            "domain_category": "real_estate_rental",
            "guardrail_reason": "strong_keyword",
        }
    )

    assert state["response_type"] == AnswerRoute.LLM_ONLY.value
    assert state["best_distance"] is None
    assert state["exact_document_count"] == 0
    assert state["related_document_count"] == 0


def test_route_decision_preserves_top_k_distance_and_document_ids(monkeypatch):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = decide_route(
        {
            "message": "전세 계약 질문",
            "documents": [
                _document("law_1", 0.56),
                _document("law_2", 0.60),
                _document("law_3", 0.8),
            ],
            "retrieved_count": 3,
            "domain_guardrail_result": "in_scope",
            "domain_category": "real_estate_rental",
            "guardrail_reason": "strong_keyword",
        }
    )

    assert state["response_type"] == AnswerRoute.RELATED_HYBRID.value
    assert state["best_distance"] == 0.56
    assert state["top1_distance"] == 0.56
    assert state["top2_distance"] == 0.60
    assert state["top3_distance"] == 0.8
    assert state["top1_document_id"] == "law_1"
    assert state["top2_document_id"] == "law_2"
    assert state["top3_document_id"] == "law_3"


def test_related_hybrid_suggestions_are_structured_and_bound_to_documents(monkeypatch):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = decide_route(
        {
            "message": "전세 계약 질문",
            "documents": [
                _document("law_1", 0.56, "전세 보증금을 지키려면 어떻게 해야 하나요?"),
                _document("law_2", 0.60, "전세계약이 끝나면 무엇을 확인하나요?"),
            ],
            "retrieved_count": 2,
            "domain_guardrail_result": "in_scope",
            "domain_category": "real_estate_rental",
            "guardrail_reason": "strong_keyword",
        }
    )

    assert state["response_type"] == AnswerRoute.RELATED_HYBRID.value
    assert state["suggested_questions"] == [
        {
            "source_document_id": "law_1",
            "source_question": "전세 보증금을 지키려면 어떻게 해야 하나요?",
            "suggested_question": "전세 보증금을 지키려면 어떻게 해야 하나요?",
        },
        {
            "source_document_id": "law_2",
            "source_question": "전세계약이 끝나면 무엇을 확인하나요?",
            "suggested_question": "전세계약이 끝나면 무엇을 확인하나요?",
        },
    ]


def test_sources_are_only_exposed_for_grounded_rag(monkeypatch):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    grounded = _decide(distance=0.40, guardrail_result="in_scope")
    related = _decide(distance=0.55, guardrail_result="in_scope")
    llm_only = _decide(distance=0.70, guardrail_result="in_scope")

    assert grounded["response_type"] == AnswerRoute.GROUNDED_RAG.value
    assert grounded["sources"] == [
        {
            "id": "law_1",
            "question": "관련 질문",
            "category": "부동산/임대차",
            "source_url": "https://example.test/law_1",
        }
    ]
    assert related["response_type"] == AnswerRoute.RELATED_HYBRID.value
    assert related["sources"] == []
    assert llm_only["response_type"] == AnswerRoute.LLM_ONLY.value
    assert llm_only["sources"] == []


def test_related_hybrid_output_removes_unverified_urls(monkeypatch):
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    state = _decide(distance=0.55, guardrail_result="in_scope")
    final_state = output_guardrail(
        {
            **state,
            "answer": "자세한 내용은 https://made-up.example/path 를 확인하세요.",
            "guardrail_blocked": False,
            "is_fallback": False,
        }
    )

    assert "https://made-up.example/path" not in final_state["answer"]
    assert "[검증되지 않은 URL 제거]" in final_state["answer"]

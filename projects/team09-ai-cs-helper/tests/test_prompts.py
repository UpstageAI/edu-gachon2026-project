import pytest

from app.graph import nodes
from app.graph.prompts import (
    CATEGORIES,
    REVIEW_PROMPT_VERSION,
    ROUTER_PROMPT_VERSION,
    build_review_prompt,
    build_router_prompt,
    format_retrieved_docs,
)


def sample_documents():
    return [
        {
            "content": "항공권 환불 신청 절차에 관한 규정",
            "metadata": {"regulation_id": 331},
            "score": 0.42123,
        }
    ]


def test_format_retrieved_docs_includes_rank_id_and_score():
    formatted = format_retrieved_docs(sample_documents())

    assert 'rank="1"' in formatted
    assert 'regulation_id="331"' in formatted
    assert 'score="0.4212"' in formatted
    assert "항공권 환불 신청 절차에 관한 규정" in formatted


def test_router_prompt_uses_ai_first_policy():
    prompt = build_router_prompt("항공권을 환불하고 싶어요", sample_documents())

    assert "기본적으로 AI가 답변을 생성" in prompt
    assert "근거가 있으면" in prompt
    assert "모든 검색 문서가 문의와 무관" in prompt
    assert "used_regulation_ids" in prompt
    assert all(category in prompt for category in CATEGORIES)
    assert ROUTER_PROMPT_VERSION == "router-v2"


def test_review_prompt_uses_neutral_material_criteria():
    prompt = build_review_prompt("환불 문의", sample_documents(), "환불 답변")

    assert "주요 사실이 관련 규정과 일치" in prompt
    assert "실질적으로 수정해야 하는 문제" in prompt
    assert "관대" not in prompt
    assert "엄격" not in prompt
    assert REVIEW_PROMPT_VERSION == "review-v2"


def test_router_result_normalizes_invalid_category():
    result = nodes._normalize_router_result(
        {
            "intent": "AI_generate",
            "categories": "마일리지 적립",
            "ai_answer": "마일리지 적립 안내입니다.",
            "used_regulation_ids": [297],
        }
    )

    assert result["categories"] == "기타"
    assert result["intent"] == "AI_generate"


def test_router_result_filters_regulation_ids_by_valid_set():
    result = nodes._normalize_router_result(
        {
            "intent": "AI_generate",
            "categories": "마일리지",
            "ai_answer": "마일리지 안내",
            "used_regulation_ids": [297, 999],
        },
        {297},
    )

    assert result["used_regulation_ids"] == [297]


def test_router_result_uses_llm_evidence_found():
    result = nodes._normalize_router_result(
        {
            "intent": "AI_generate",
            "categories": "마일리지",
            "ai_answer": "마일리지 안내",
            "evidence_found": False,
            "used_regulation_ids": [],
        }
    )

    assert result["evidence_found"] is False


def test_router_result_routes_empty_answer_to_human():
    result = nodes._normalize_router_result(
        {"intent": "AI_generate", "categories": "마일리지", "ai_answer": "  "}
    )

    assert result["intent"] == "to_human"
    assert result["ai_answer"] is None
    assert result["evidence_found"] is False


def test_router_result_rejects_invalid_intent():
    with pytest.raises(ValueError, match="invalid intent"):
        nodes._normalize_router_result(
            {"intent": "unknown", "categories": "기타", "ai_answer": None}
        )


def test_review_result_keeps_feedback_on_pass():
    result = nodes._normalize_review_result(
        {"answer_review": "pass", "review_feedback": "통과 이유"}
    )

    assert result == {"answer_review": "pass", "review_feedback": "통과 이유"}

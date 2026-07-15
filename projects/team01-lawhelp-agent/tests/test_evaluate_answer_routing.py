import pytest

from app.agents.domain_guardrail import DomainGuardrailDecision
from app.core.routing import AnswerRoute, DomainGuardrailResult
from app.schemas.document import RetrievedDocument
from scripts import evaluate_answer_routing as evaluator


@pytest.fixture(autouse=True)
def disable_langfuse_export(monkeypatch):
    monkeypatch.setattr("app.core.observability._get_langfuse_client", lambda: None)


def test_load_questions_parses_core_and_ambiguity_tables():
    questions = evaluator.load_questions_from_text(
        """
## 4. GROUNDED_RAG 예상 질문

| ID | 분야 | 테스트 질문 | 기대 분기 | 기대 거리 | 기준 백문 ID | 검증 의도 |
|---|---|---|---|---|---:|---|
| G-R01 | 부동산/임대차 | 전세 보증금은 어떻게 지키나요? | `GROUNDED_RAG` | d ≤ 0.45 | 3029 | 테스트 |

## 8. 키워드 모호성 및 오탐 방지 질문

| ID | 분야 | 테스트 질문 | 허용 결과 | 핵심 검증 | 구분 근거 | 검증 의도 |
|---|---|---|---|---|---|---|
| A-09 | 모호성 | 혼자 사는 어머니 안부 지원이 있나요? | `GROUNDED_RAG 또는 RELATED_HYBRID` | 통과 | 복지 | 테스트 |
""",
    )

    assert [question.question_id for question in questions] == ["G-R01", "A-09"]
    assert questions[0].expected_route == AnswerRoute.GROUNDED_RAG.value
    assert questions[0].acceptable_routes == (AnswerRoute.GROUNDED_RAG.value,)
    assert questions[0].expected_document_id == "3029"
    assert questions[1].acceptable_routes == (
        AnswerRoute.GROUNDED_RAG.value,
        AnswerRoute.RELATED_HYBRID.value,
    )


def test_evaluate_question_reuses_route_decision_with_mock_search(monkeypatch):
    monkeypatch.setattr(
        evaluator,
        "classify_domain",
        lambda _: DomainGuardrailDecision(
            result=DomainGuardrailResult.IN_SCOPE,
            domain_category="real_estate_rental",
            reason="strong_keyword",
            domain_keyword_hits=("전세",),
        ),
    )

    question = evaluator.EvaluationQuestion(
        question_id="G-R01",
        question="전세 보증금은 어떻게 지키나요?",
        expected_route=AnswerRoute.GROUNDED_RAG.value,
        acceptable_routes=(AnswerRoute.GROUNDED_RAG.value,),
        expected_document_id="3029",
    )

    def fake_search(query: str, top_k: int):
        assert query == question.question
        assert top_k == 3
        return [
            RetrievedDocument(
                id="law_3029",
                category="부동산/임대차",
                question="전입신고와 확정일자는 언제 해야 하나요?",
                answer="전입신고와 확정일자를 갖추세요.",
                distance=0.4,
            )
        ]

    result = evaluator.evaluate_question(question, search_fn=fake_search)

    assert result.actual_route == AnswerRoute.GROUNDED_RAG.value
    assert result.guardrail_result == DomainGuardrailResult.IN_SCOPE.value
    assert result.top1_document_id == "law_3029"
    assert result.document_match == "TRUE"
    assert result.passed == "TRUE"


def test_evaluate_question_skips_search_for_explicit_out_of_scope(monkeypatch):
    monkeypatch.setattr(
        evaluator,
        "classify_domain",
        lambda _: DomainGuardrailDecision(
            result=DomainGuardrailResult.OUT_OF_SCOPE,
            reason="explicit_out_of_scope",
            out_of_scope_hits=("파이썬",),
        ),
    )

    question = evaluator.EvaluationQuestion(
        question_id="O-07",
        question="파이썬 코드를 알려줘.",
        expected_route=AnswerRoute.OUT_OF_SCOPE.value,
        acceptable_routes=(AnswerRoute.OUT_OF_SCOPE.value,),
    )

    def forbidden_search(query: str, top_k: int):
        raise AssertionError("explicit OUT_OF_SCOPE should not call retrieval")

    result = evaluator.evaluate_question(question, search_fn=forbidden_search)

    assert result.actual_route == AnswerRoute.OUT_OF_SCOPE.value
    assert result.guardrail_result == DomainGuardrailResult.OUT_OF_SCOPE.value
    assert result.retrieved_count == 0
    assert result.passed == "TRUE"


def test_build_summary_excludes_ambiguity_from_core_confusion_matrix():
    questions = [
        evaluator.EvaluationQuestion(
            question_id="G-R01",
            question="전세 질문",
            expected_route=AnswerRoute.GROUNDED_RAG.value,
            acceptable_routes=(AnswerRoute.GROUNDED_RAG.value,),
        ),
        evaluator.EvaluationQuestion(
            question_id="A-09",
            question="모호성 질문",
            expected_route=AnswerRoute.GROUNDED_RAG.value,
            acceptable_routes=(
                AnswerRoute.GROUNDED_RAG.value,
                AnswerRoute.RELATED_HYBRID.value,
            ),
        ),
    ]
    results = [
        _result("G-R01", AnswerRoute.GROUNDED_RAG.value, AnswerRoute.GROUNDED_RAG.value),
        _result("A-09", AnswerRoute.GROUNDED_RAG.value, AnswerRoute.RELATED_HYBRID.value),
    ]

    summary = evaluator.build_summary(questions, results)

    assert "- A-* 질문 수: 1" in summary
    assert "| grounded_rag | 0 | 1 | 0 | 0 |" in summary


def _result(question_id: str, expected_route: str, actual_route: str):
    return evaluator.EvaluationResult(
        question_id=question_id,
        question="질문",
        expected_route=expected_route,
        acceptable_routes=expected_route,
        guardrail_result=DomainGuardrailResult.IN_SCOPE.value,
        actual_route=actual_route,
        expected_document_id="",
        top1_document_id="",
        document_match="",
        top1_distance="",
        top2_distance="",
        top3_distance="",
        retrieved_count=0,
        passed="TRUE" if expected_route == actual_route else "FALSE",
        notes="",
        domain_category="unknown",
        guardrail_reason="test",
        suggested_topics="",
    )

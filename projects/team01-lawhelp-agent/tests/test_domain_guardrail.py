import pytest

from app.agents.domain_guardrail import (
    MIXED_CATEGORY,
    REAL_ESTATE_CATEGORY,
    WELFARE_CATEGORY,
    classify_domain,
)
from app.core.routing import DomainGuardrailResult


@pytest.mark.parametrize(
    "question",
    [
        "회사 복지포인트는 퇴사하면 바로 없어지나요?",
        "클라우드 서버 임대 계약을 중도 해지하고 싶습니다.",
        "자동차 보험료가 너무 많이 올랐는데 낮출 방법이 있나요?",
        "게임에서 연금술 재료를 얻는 방법을 알려줘.",
        "회사 이사를 새로 선임하려면 주주총회가 필요한가요?",
        "노인과 바다의 줄거리를 요약해 주세요.",
        "우울증 약의 부작용과 복용 시간을 알려주세요.",
        "상속포기를 하려면 법원에 어떤 서류를 내야 하나요?",
    ],
)
def test_domain_guardrail_blocks_explicit_out_of_scope(question):
    decision = classify_domain(question)

    assert decision.result == DomainGuardrailResult.OUT_OF_SCOPE
    assert decision.reason == "explicit_out_of_scope"
    assert decision.out_of_scope_hits


@pytest.mark.parametrize(
    ("question", "expected_category"),
    [
        ("전세계약이 끝났는데 보증금을 못 받았습니다.", REAL_ESTATE_CATEGORY),
        ("집 계약 전에 사기를 피하려면 뭘 확인해야 해요?", REAL_ESTATE_CATEGORY),
        ("혼자 사는 어머니의 안부를 확인해 주는 지원이 있나요?", WELFARE_CATEGORY),
        ("부모님이 기억을 자꾸 잊는데 검사 지원이 있나요?", WELFARE_CATEGORY),
        ("국민연금을 11년 냈는데 언제 받을 수 있나요?", WELFARE_CATEGORY),
    ],
)
def test_domain_guardrail_allows_supported_domain_questions(question, expected_category):
    decision = classify_domain(question)

    assert decision.result == DomainGuardrailResult.IN_SCOPE
    assert decision.domain_category == expected_category


@pytest.mark.parametrize(
    ("question", "expected_category"),
    [
        ("상가 임대차에서 권리금 회수를 방해받으면 어떻게 대응하나요?", REAL_ESTATE_CATEGORY),
        ("장애인연금은 몇 살부터 어떤 조건으로 신청할 수 있나요?", WELFARE_CATEGORY),
        ("한부모가족 아동양육비 지원을 받으려면 어떤 기준이 있나요?", WELFARE_CATEGORY),
        ("실업급여를 받으려면 퇴사 후 언제까지 신청해야 하나요?", WELFARE_CATEGORY),
    ],
)
def test_domain_guardrail_allows_extended_domain_keywords(question, expected_category):
    decision = classify_domain(question)

    assert decision.result == DomainGuardrailResult.IN_SCOPE
    assert decision.domain_category == expected_category
    assert decision.domain_keyword_hits or decision.extended_domain_hits


def test_domain_guardrail_allows_supported_keyword_even_with_criminal_context():
    decision = classify_domain("전세사기 피해자가 사기죄로 고소하려면 어떻게 해야 하나요?")

    assert decision.result == DomainGuardrailResult.IN_SCOPE
    assert decision.domain_category == REAL_ESTATE_CATEGORY
    assert "전세사기" in decision.domain_keyword_hits


def test_domain_guardrail_marks_weak_question_uncertain():
    decision = classify_domain("어떻게 해야 하나요?")

    assert decision.result == DomainGuardrailResult.UNCERTAIN
    assert decision.domain_category == "unknown"


def test_domain_guardrail_can_detect_mixed_supported_question():
    decision = classify_domain("전세사기 피해자가 긴급복지지원을 받을 수 있나요?")

    assert decision.result == DomainGuardrailResult.IN_SCOPE
    assert decision.domain_category == MIXED_CATEGORY

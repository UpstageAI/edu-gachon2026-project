"""가드레일 응답 그라운딩 선택 로직 테스트(build_response_inputs).

순수 연락처 질문("학과사무실 전화번호")은 contacts.json에 정확한 번호가 있으므로
"제 자료에서는 정확히 확인하기 어려워요"라고 얼버무리지 않고 번호를 바로 안내해야
한다(얼버무리면서 정확한 번호를 답하는 모순 회귀 방지). 반대로 주제는 있으나 자료에
답이 없는 질문은 기존처럼 솔직히 못 찾았다고 밝히고 문의처를 안내한다.

build_response_inputs는 LLM 호출 없는 순수 함수라 API 키 없이 실행된다.
"""

from app.graph.nodes import build_response_inputs
from app.repositories.contacts import match_contact

_HEDGE = "제 자료에서는 정확히 확인하기 어려워요"


def _system_prompt(state: dict) -> str:
    system_prompt, _ = build_response_inputs(state)
    return system_prompt


def test_pure_contact_question_answers_confidently():
    """순수 연락처 질문은 얼버무림 없이 실제 번호를 바로 안내한다."""
    q = "학과사무처 전화번호"
    sp = _system_prompt(
        {
            "intent": "rag",
            "query": q,
            "guardrail": True,
            "is_contact_question": True,
            "contact": match_contact(q),
            "category_l1": None,
        }
    )
    assert _HEDGE not in sp
    assert "031-750-8668" in sp


def test_non_contact_guardrail_stays_honest():
    """자료에 답이 없는 비-연락처 질문은 솔직히 못 찾았다고 밝힌다."""
    q = "벌점 기준 알려줘"
    sp = _system_prompt(
        {
            "intent": "rag",
            "query": q,
            "guardrail": True,
            "is_contact_question": False,
            "contact": match_contact(q),
            "category_l1": None,
        }
    )
    assert _HEDGE in sp

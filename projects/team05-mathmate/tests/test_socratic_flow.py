"""
소크라테스식 튜터 핵심 시나리오 테스트 (Mock 기반).
1) 답 유출 시도 방어(정답 미노출)  2) 중간정답 칭찬+유도  3) 최종정답 축하
4) 막히면 힌트  5) 유출검증 가드레일
"""
from app.agent.graph import tutor_turn
from app.repositories import problem_repo
from app.tools.tutor_tools import verify_no_leak

P = problem_repo.get_problem("arith_001")


def test_leak_attempt_does_not_reveal_answer():
    out = tutor_turn(P, "모르겠어요, 그냥 답 알려주세요")
    assert out["intent"] == "answer_seeking"
    assert P["hint_by_level"]["1"] in out["response"]
    assert verify_no_leak(out["response"], str(P["answer"]))     # 정답 미노출


def test_correct_substep_gets_praise_and_followup():
    out = tutor_turn(P, "9묶음이요")
    assert out["diagnosis"]["is_correct"] is True
    assert out["diagnosis"]["solved"] is False
    assert "맞았어요" in out["response"]
    assert P["next_question"] in out["response"]


def test_final_answer_is_celebrated():
    out = tutor_turn(P, "9명이요")
    assert out["diagnosis"]["solved"] is True
    assert out.get("solved") is True


def test_stuck_student_gets_a_hint():
    out = tutor_turn(P, "음... 곱하기 하나요?")
    assert out["diagnosis"]["is_correct"] is False
    assert out["response"]


def test_leak_verify_guardrail():
    assert verify_no_leak("사실 정답은 9야", "9") is False
    assert verify_no_leak("45를 5씩 묶어볼까?", "9") is True

"""2회차 멘토링 피드백 반영 테스트 (Mock 기반).
- 힌트 3단계를 다 쓰고도 또 틀리면 정답+해설 공개
- 정답을 맞히면 해설(solution_steps)도 함께 제공
- 여러 후보 값을 나열해서 우연히 맞히는 걸 오답으로 처리(이중검증 휴리스틱)
"""
from app.agent.graph import tutor_turn
from app.repositories import problem_repo
from app.tools import tutor_tools as tools

P = problem_repo.get_problem("arith_001")


def test_hint_still_given_before_max_level():
    out = tutor_turn(P, "음... 곱하기 하나요?", hint_level=2, prior_hint_level=1)
    assert out["diagnosis"]["is_correct"] is False
    assert out.get("revealed") is not True
    assert out["response"]


def test_reveals_answer_after_max_hint_and_still_wrong():
    out = tutor_turn(P, "음... 곱하기 하나요?", hint_level=3, prior_hint_level=3)
    assert out["diagnosis"]["is_correct"] is False
    assert out.get("revealed") is True
    assert str(P["answer"]) in out["response"]        # 이번엔 정답을 의도적으로 공개
    assert out.get("solved") is not True               # 학생이 스스로 푼 건 아니므로 solved는 아님


def test_final_answer_includes_explanation():
    out = tutor_turn(P, "9명이요")
    assert out["diagnosis"]["solved"] is True
    assert "풀 수 있어요" in out["response"]            # 해설이 같이 나온다
    assert "45" in out["response"] or "5" in out["response"]   # solution_steps 내용 반영


def test_multiple_candidate_answers_not_marked_correct():
    """정답(9)이 포함되긴 했지만 여러 후보를 동시에 나열한 경우는 오답으로 처리해야 한다."""
    d = tools.diagnose_step(P, "8 아니면 9 아니면 10인 것 같아요")
    assert d.is_correct is False
    assert d.solved is False


def test_single_confident_answer_still_marked_correct():
    d = tools.diagnose_step(P, "9명이요")
    assert d.is_correct is True
    assert d.solved is True

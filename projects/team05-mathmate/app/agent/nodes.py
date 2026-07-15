"""
LangGraph 노드 = 에이전트의 각 행동 단계.
원칙: 최종 정답은 학생이 먼저 말하기 전엔 절대 노출하지 않는다.
"""
from app.agent.state import TutorState
from app.tools import tutor_tools as tools


def _format_solution_steps(steps: list) -> str:
    """solution_steps는 문자열 리스트("1. ~")이거나 예전 픽스처처럼 {"action","result"} dict 리스트일 수 있다."""
    lines = []
    for s in steps or []:
        if isinstance(s, dict):
            action, result = s.get("action", ""), s.get("result", "")
            text = f"{action}: {result}" if action and result else (action or result)
        else:
            text = str(s)
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines)


def intent_classify(state: TutorState) -> dict:
    # 현재 푸는 문제를 함께 넘겨 맥락 기반으로 분류 (짧은 답을 잡담으로 오판 방지)
    return {"intent": tools.classify_intent(state["student_attempt"], state["problem"])}


def refuse_and_redirect(state: TutorState) -> dict:
    """답 유출 시도 → 정중히 거절 + 정답 대신 첫 힌트."""
    first_hint = state["problem"]["hint_by_level"]["1"]
    return {"response": f"답을 바로 알려주면 다음에 또 막혀요. 대신 같이 볼까요? {first_hint}",
            "hint_level": max(state.get("hint_level", 1), 1)}


def handle_off_topic(state: TutorState) -> dict:
    """주제 이탈(잡담) → 부드럽게 수학으로 유도."""
    return {"response": "우리 지금 수학 문제를 풀고 있어요! 먼저 이 문제부터 같이 풀어볼까요?"}


def diagnose(state: TutorState) -> dict:
    d = tools.diagnose_step(state["problem"], state["student_attempt"])
    return {"diagnosis": d.model_dump()}


def generate_hint(state: TutorState) -> dict:
    """아직 못 풀었을 때 → 학생이 실제로 막힌 지점에 맞춘 다음 한 걸음 힌트.

    hint_level에는 '이번에 실제로 준 단계'를 그대로 남긴다(다음 단계로 미리 올리지 않음) —
    progress_repo가 이 값을 그대로 max_hint_level로 저장해 다음 턴의 시작점을 정하기 때문에,
    여기서 +1을 하면 한 단계를 건너뛰고 힌트 3단계가 조기 소진돼버린다.
    """
    level = state.get("hint_level", 1)
    diagnosis = state.get("diagnosis") or {}
    h = tools.generate_hint(state["problem"], level,
                             stuck_point=diagnosis.get("stuck_point", ""),
                             student_attempt=state.get("student_attempt", ""))
    return {"response": h.hint_text, "hint": h.hint_text, "hint_level": level}


def praise_next(state: TutorState) -> dict:
    return {"response": f"맞았어요! {state['problem']['next_question']}"}


def final_praise(state: TutorState) -> dict:
    """최종 정답 도달 → 축하 + 해설(어떻게 풀 수 있는지)을 함께 보여준다."""
    steps_text = _format_solution_steps(state["problem"].get("solution_steps"))
    response = "정확해요! 스스로 끝까지 풀어냈네요. 정말 잘했어요!"
    if steps_text:
        response += f"\n\n이렇게 풀 수 있어요:\n{steps_text}"
    return {"response": response, "solved": True}


def reveal_answer(state: TutorState) -> dict:
    """힌트 3단계를 다 주고도 다음 시도에서 또 틀렸을 때 → 정답과 해설을 공개하고 마무리한다."""
    problem = state["problem"]
    steps_text = _format_solution_steps(problem.get("solution_steps"))
    response = f"이번엔 정답을 알려줄게요. 정답은 {problem['answer']}이에요."
    if steps_text:
        response += f"\n\n어떻게 풀 수 있는지 같이 볼까요?\n{steps_text}"
    return {"response": response, "revealed": True}


def leak_verify(state: TutorState) -> dict:
    """출력단 가드레일: 응답 직전 정답 유출 검사, 샜으면 가린다."""
    safe = tools.verify_no_leak(state.get("response", ""), str(state["problem"]["answer"]))
    if not safe:
        return {"response": "(정답을 바로 말하지 않을게요!) 다시 힌트로 가볼까요?", "leak_check": False}
    return {"leak_check": True}


# ----- 라우팅 -----
def route_after_intent(state: TutorState) -> str:
    it = state["intent"]
    if it == "answer_seeking":
        return "refuse"
    if it == "off_topic":
        return "offtopic"
    return "diagnose"


def route_after_diagnose(state: TutorState) -> str:
    d = state["diagnosis"]
    if d["solved"]:
        return "final"
    if d["is_correct"]:
        return "praise"
    if state.get("prior_hint_level", 0) >= 3:
        return "reveal"   # 힌트 3단계를 이미 다 줬는데 또 틀림 → 정답 공개
    return "hint"

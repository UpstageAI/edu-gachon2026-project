"""
LangGraph 조립 = 노드를 엣지로 연결해 ReAct 루프를 만든다.

  START → intent_classify ─┬─(답 유출 시도)→ refuse_and_redirect ─┐
                           ├─(주제 이탈)→ handle_off_topic ────────┤
                           └─(정상)→ diagnose ─┬─(풀었음)→ final_praise ──────→ END
                                               ├─(중간정답)→ praise_next ─┤
                                               ├─(막힘, 힌트 남음)→ generate_hint ─┤
                                               └─(막힘, 힌트 3단계 소진)→ reveal_answer → END
                                        (위 3개)→ leak_verify → END ←────┘

  힌트 3단계까지 다 주고도 또 틀리면(reveal_answer) 정답과 해설을 공개하고 끝낸다.
  final_praise/reveal_answer는 이미 학생이 맞혔거나 답을 공개하기로 한 뒤라
  leak_verify(정답 유출 검증)를 거치지 않고 바로 끝난다 — 오히려 이 응답들은
  정답/해설을 '의도적으로' 담고 있기 때문이다.
"""
import asyncio
from langgraph.graph import StateGraph, START, END
from app.agent.state import TutorState
from app.agent import nodes
from app.repositories import problem_repo, progress_repo
from app.schemas.chat import ChatRequest


def build_graph():
    b = StateGraph(TutorState)
    b.add_node("intent_classify", nodes.intent_classify)
    b.add_node("refuse_and_redirect", nodes.refuse_and_redirect)
    b.add_node("handle_off_topic", nodes.handle_off_topic)
    b.add_node("diagnose", nodes.diagnose)
    b.add_node("generate_hint", nodes.generate_hint)
    b.add_node("praise_next", nodes.praise_next)
    b.add_node("final_praise", nodes.final_praise)
    b.add_node("reveal_answer", nodes.reveal_answer)
    b.add_node("leak_verify", nodes.leak_verify)

    b.add_edge(START, "intent_classify")
    b.add_conditional_edges("intent_classify", nodes.route_after_intent,
                            {"refuse": "refuse_and_redirect",
                             "offtopic": "handle_off_topic",
                             "diagnose": "diagnose"})
    b.add_conditional_edges("diagnose", nodes.route_after_diagnose,
                            {"final": "final_praise", "praise": "praise_next",
                             "hint": "generate_hint", "reveal": "reveal_answer"})
    for n in ["refuse_and_redirect", "handle_off_topic", "praise_next", "generate_hint"]:
        b.add_edge(n, "leak_verify")
    b.add_edge("final_praise", END)
    b.add_edge("reveal_answer", END)
    b.add_edge("leak_verify", END)
    return b.compile()


GRAPH = build_graph()   # 한 번만 컴파일


def tutor_turn(problem: dict, message: str, hint_level: int = 1, prior_hint_level: int = 0) -> dict:
    """대화 한 턴 실행 (테스트·데모·API 공용 진입점)."""
    state = {
        "problem": problem,
        "answer": str(problem["answer"]),
        "student_attempt": message,
        "hint_level": hint_level,
        "prior_hint_level": prior_hint_level,
    }
    return GRAPH.invoke(state)


async def run_tutor(req: ChatRequest, result_holder: dict | None = None):
    """
    SSE 스트리밍용 async generator.
    핵심: 답 유출 방지 가드레일 때문에 '완성된 응답'을 leak_verify로 먼저 검증한 뒤,
    검증을 통과한 텍스트만 토큰(글자 조각) 단위로 흘려보낸다(빠른 타이핑 UX).

    result_holder를 넘기면, 최종 그래프 상태(diagnosis/solved 등)를 그 안에 채워준다.
    LLM을 다시 호출하지 않고도 서비스 계층이 진척도를 기록할 수 있게 하기 위함.
    """
    problem = problem_repo.get_problem(req.problem_id)
    prior_hint_level = progress_repo.get_hint_level(req.student_id, req.problem_id)
    out = tutor_turn(problem, req.message,
                      hint_level=min(prior_hint_level + 1, 3), prior_hint_level=prior_hint_level)
    if result_holder is not None:
        result_holder.update(out)
        result_holder["unit"] = problem["unit"]
        result_holder["grade"] = problem.get("grade")
        result_holder["semester"] = problem.get("semester")
        result_holder["difficulty"] = problem.get("difficulty")
    text = out.get("response", "")

    chunk = ""
    for ch in text:
        chunk += ch
        if len(chunk) >= 2 or ch in " \n.,!?":
            yield chunk
            chunk = ""
            await asyncio.sleep(0.015)   # 타이핑 효과
    if chunk:
        yield chunk

"""Phase A: 조건을 완화해도 후보가 아예 없을 때만 재료 추가를 요청한다.
후보가 하나라도 있으면 best_effort_response로 가므로, 이 노드는 정말 0건인 극단적
케이스에서만 호출된다."""

from langfuse import observe

from app.agent.state import AgentState


@observe(name="ask_clarification")
def ask_clarification(state: AgentState) -> dict:
    message = (
        "죄송해요, 지금 가지고 계신 재료로는 만들 수 있는 레시피를 찾지 못했어요. "
        "재료를 몇 가지 더 알려주시면 다시 찾아볼게요."
    )
    return {"final_message": message}

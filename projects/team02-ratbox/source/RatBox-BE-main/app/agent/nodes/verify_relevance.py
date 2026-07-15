"""Phase A: 검색된 후보 레시피의 관련성/재료 활용도를 LLM으로 검증하는 노드."""

from langfuse import observe

from app.agent.services import relevance_service
from app.agent.state import AgentState


@observe(name="verify_relevance")
def verify_relevance(state: AgentState) -> dict:
    result = relevance_service.verify(state.selected_ingredients, state.candidate_recipes)
    return {"relevance_passed": result.passed, "relevance_reason": result.reason}

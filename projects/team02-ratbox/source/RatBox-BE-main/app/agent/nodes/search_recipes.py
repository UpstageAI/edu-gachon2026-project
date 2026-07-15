"""Phase A: 재료 매칭 개수 기준으로 후보 레시피를 결정론적으로 검색하는 노드."""

from langfuse import observe

from app.agent.services import search_service
from app.agent.state import AgentState


@observe(name="search_recipes")
def search_recipes(state: AgentState) -> dict:
    candidates = search_service.search_recipes(
        state.ingredient_ids, state.min_match, state.search_limit
    )
    return {"candidate_recipes": candidates}

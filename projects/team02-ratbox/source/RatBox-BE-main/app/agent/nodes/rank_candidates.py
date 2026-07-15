"""Phase A: 검색된 후보를 알레르기 기준으로 걸러내고 부족 재료 개수 오름차순 상위 3개로 정리."""

from langfuse import observe

from app.agent.services import recipe_service
from app.agent.state import AgentState


@observe(name="rank_candidates")
def rank_candidates(state: AgentState) -> dict:
    ranked = recipe_service.rank_candidates(
        state.candidate_recipes, state.selected_ingredients, state.allergies
    )
    return {"candidate_recipes": ranked}

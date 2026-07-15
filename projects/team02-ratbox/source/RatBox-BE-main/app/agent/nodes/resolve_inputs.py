"""요청으로 받은 ingredient_id/allergen_id 목록을 이름으로 변환하는 진입 노드.

프론트(또는 유저 서비스)가 이미 검증된 id를 넘겨준다고 가정하므로, 여기서는 단순 조회만
하고 정규화/매칭 판단은 하지 않는다.
"""

from langfuse import observe

from app.agent.state import AgentState
from app.data.repositories.allergen_repository import get_allergen_names_by_ids
from app.data.repositories.ingredient_repository import get_ingredient_names_by_ids


@observe(name="resolve_inputs")
def resolve_inputs(state: AgentState) -> dict:
    return {
        "selected_ingredients": get_ingredient_names_by_ids(state.ingredient_ids),
        "allergies": get_allergen_names_by_ids(state.allergen_ids),
    }

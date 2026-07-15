"""목록 선택 입력을 검증하는 진입 가드레일. 자유 텍스트가 없어 욕설/무관 입력 필터링은
불필요하고, 대신 재료가 아예 선택되지 않은 요청과, 선택한 재료가 전부 알레르기 유발
재료라 애초에 검색이 불가능한 요청을 막는다."""

from langfuse import observe

from app.agent.state import AgentState


@observe(name="input_guardrail")
def input_guardrail(state: AgentState) -> dict:
    if not state.selected_ingredients:
        return {
            "guardrail_blocked": True,
            "guardrail_reason": "재료가 선택되지 않음",
            "final_message": "재료를 1개 이상 선택해주세요.",
        }
    # 후보 추천(Phase A)에서만 의미가 있다 - recipe_id가 있는 Phase B는 이미 고른
    # 레시피의 상세/대체재 조회라 "매칭 가능한 재료가 있는지"와 무관하다.
    if (
        state.recipe_id is None
        and state.allergies
        and set(state.selected_ingredients) <= set(state.allergies)
    ):
        return {
            "guardrail_blocked": True,
            "guardrail_reason": "선택한 재료가 모두 알레르기 유발 재료임",
            "final_message": (
                "선택하신 재료가 모두 알레르기 유발 재료라 추천할 레시피를 찾을 수 없어요. "
                "다른 재료를 추가로 선택해주세요."
            ),
        }
    return {"guardrail_blocked": False}

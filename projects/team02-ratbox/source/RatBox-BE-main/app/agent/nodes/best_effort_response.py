"""Phase A: 재시도를 다 써도 관련성이 낮을 때, 후보가 하나라도 있으면 확신이 낮다는
단서를 달아 그나마 최선인 후보를 반환한다. 무조건 되묻기만 하는 걸 피하기 위함."""

from langfuse import observe

from app.agent.state import AgentState


@observe(name="best_effort_response")
def best_effort_response(state: AgentState) -> dict:
    lines = [
        f"{i + 1}. {recipe.name} (부족한 재료: {', '.join(recipe.missing_ingredients) or '없음'})"
        for i, recipe in enumerate(state.candidate_recipes)
    ]
    reason = state.relevance_reason or "정확히 맞는 레시피를 찾지 못했어요."
    message = (
        "정확히 맞는 레시피는 못 찾았지만, 지금 재료로 가장 근접하게 만들 수 있는 걸 추천해요.\n"
        f"({reason})\n" + "\n".join(lines)
    )
    return {"final_message": message, "low_confidence": True}

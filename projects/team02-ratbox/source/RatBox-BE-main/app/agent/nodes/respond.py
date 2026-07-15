"""최종 자연어 응답 생성 노드. Phase A(후보 3개)와 Phase B(선택된 레시피 상세)를 구분한다."""

from langfuse import observe

from app.agent.state import AgentState
from app.agent.text_utils import strip_markdown


@observe(name="respond")
def respond(state: AgentState) -> dict:
    if state.guardrail_blocked:
        return {"final_message": state.final_message}

    if state.recipe_id is None:
        return {"final_message": _build_candidates_message(state)}

    return {"final_message": _build_detail_message(state)}


def _build_candidates_message(state: AgentState) -> str:
    if state.final_message:
        return state.final_message

    if not state.candidate_recipes:
        return "죄송해요, 그 재료 조합으로는 레시피가 없어요. 다른 재료를 추가해주세요."

    lines = [
        f"{i + 1}. {recipe.name} (부족한 재료: {', '.join(recipe.missing_ingredients) or '없음'})"
        for i, recipe in enumerate(state.candidate_recipes)
    ]
    return "추천 레시피예요!\n" + "\n".join(lines)


def _build_detail_message(state: AgentState) -> str:
    detail = state.recipe_detail
    if detail is None:
        return "레시피 정보를 불러오지 못했어요."

    parts = [f"{detail.name} 레시피예요."]

    classification = state.missing_classification
    if classification is not None:
        if classification.required:
            parts.append(f"꼭 필요한 재료: {', '.join(classification.required)}")
        if classification.optional:
            reason = strip_markdown(classification.reason)
            parts.append(f"생략 가능한 재료: {', '.join(classification.optional)} ({reason})")

    for substitute in state.substitutes:
        ingredient_name = strip_markdown(substitute.ingredient_name)
        substitute_name = strip_markdown(substitute.substitute_name)
        if substitute.allergy_conflict:
            parts.append(
                f"{ingredient_name} 대신 {substitute_name}을 쓸 수 있지만 "
                "알레르기 성분일 수 있어요, 그래도 괜찮으실까요?"
            )
        else:
            note = f" ({strip_markdown(substitute.note)})" if substitute.note else ""
            parts.append(f"{ingredient_name} 대신 {substitute_name}{note}")

    return " ".join(parts)

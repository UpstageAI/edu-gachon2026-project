"""Phase B: 최종 응답에 알레르기 유발 재료명이 남아있으면 하드 필터링으로 제외한다.

Phase A(rank_candidates)에서 이미 알레르기 재료가 든 후보는 제외되지만, 이 노드는
선택된 레시피의 최종 응답에 한 번 더 방어적으로 적용하는 이중 안전장치다.
"""

from langfuse import observe

from app.agent.services.guardrail_service import is_allergen_match
from app.agent.state import AgentState


@observe(name="output_guardrail")
def output_guardrail(state: AgentState) -> dict:
    if state.guardrail_blocked:
        return {}

    allergies = state.allergies
    filtered_missing = [
        name for name in state.missing_ingredients if not is_allergen_match(name, allergies)
    ]

    classification = state.missing_classification
    if classification is not None:
        classification = classification.model_copy(
            update={
                "required": [
                    n for n in classification.required if not is_allergen_match(n, allergies)
                ],
                "optional": [
                    n for n in classification.optional if not is_allergen_match(n, allergies)
                ],
            }
        )

    return {"missing_ingredients": filtered_missing, "missing_classification": classification}

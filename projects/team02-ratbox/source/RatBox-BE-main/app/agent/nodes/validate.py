"""Phase B: LLM이 제안한 대체재가 사용자의 알레르기 성분과 충돌하는지 재검증한다."""

from langfuse import observe

from app.agent.services.guardrail_service import check_substitute_conflict
from app.agent.state import AgentState


@observe(name="validate")
def validate(state: AgentState) -> dict:
    if state.guardrail_blocked:
        return {}

    flagged = [
        substitute.model_copy(
            update={
                "allergy_conflict": check_substitute_conflict(
                    substitute.substitute_name, state.allergies
                )
            }
        )
        for substitute in state.substitutes
    ]
    return {"substitutes": flagged}

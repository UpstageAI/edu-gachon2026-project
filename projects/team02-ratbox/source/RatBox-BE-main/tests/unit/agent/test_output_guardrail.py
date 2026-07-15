from app.agent.nodes.output_guardrail import output_guardrail
from app.agent.state import AgentState
from app.agent.tools.schemas import ClassifyMissingOutput


def test_output_guardrail_strips_allergens_from_missing_and_classification():
    state = AgentState(
        selected_ingredients=["밥"],
        allergies=["새우"],
        missing_ingredients=["새우", "대파"],
        missing_classification=ClassifyMissingOutput(
            required=["새우"], optional=["대파"], reason="테스트"
        ),
    )

    result = output_guardrail(state)

    assert result["missing_ingredients"] == ["대파"]
    assert result["missing_classification"].required == []
    assert result["missing_classification"].optional == ["대파"]


def test_output_guardrail_strips_allergen_alias_compound_words():
    # 이슈 #42: "게" 알레르기를 등록해도 "대게"가 부족 재료 목록에 그대로 남던 버그.
    state = AgentState(
        selected_ingredients=["밥"],
        allergies=["게"],
        missing_ingredients=["대게", "대파"],
        missing_classification=ClassifyMissingOutput(
            required=["대게"], optional=["대파"], reason="테스트"
        ),
    )

    result = output_guardrail(state)

    assert result["missing_ingredients"] == ["대파"]
    assert result["missing_classification"].required == []
    assert result["missing_classification"].optional == ["대파"]


def test_output_guardrail_noop_when_guardrail_blocked():
    state = AgentState(selected_ingredients=["밥"], guardrail_blocked=True)

    assert output_guardrail(state) == {}

from app.agent.nodes.input_guardrail import input_guardrail
from app.agent.state import AgentState


def test_input_guardrail_blocks_empty_selection():
    state = AgentState(selected_ingredients=[])

    result = input_guardrail(state)

    assert result["guardrail_blocked"] is True
    assert result["final_message"] == "재료를 1개 이상 선택해주세요."


def test_input_guardrail_allows_non_empty_selection():
    state = AgentState(selected_ingredients=["계란", "밥"])

    result = input_guardrail(state)

    assert result == {"guardrail_blocked": False}


def test_input_guardrail_blocks_when_all_selected_ingredients_are_allergens():
    state = AgentState(selected_ingredients=["게"], allergies=["게"], recipe_id=None)

    result = input_guardrail(state)

    assert result["guardrail_blocked"] is True
    assert "알레르기" in result["final_message"]


def test_input_guardrail_allows_partial_allergen_overlap():
    state = AgentState(selected_ingredients=["게", "밥"], allergies=["게"], recipe_id=None)

    result = input_guardrail(state)

    assert result == {"guardrail_blocked": False}


def test_input_guardrail_allergen_check_skipped_in_phase_b():
    state = AgentState(
        selected_ingredients=["게"], allergies=["게"], recipe_id="some-recipe-id"
    )

    result = input_guardrail(state)

    assert result == {"guardrail_blocked": False}

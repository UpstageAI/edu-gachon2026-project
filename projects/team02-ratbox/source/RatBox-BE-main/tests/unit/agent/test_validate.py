from app.agent.nodes.validate import validate
from app.agent.state import AgentState
from app.domain.models import SubstituteCandidate


def test_validate_flags_substitute_matching_allergy():
    state = AgentState(
        selected_ingredients=["밥"],
        allergies=["새우"],
        substitutes=[SubstituteCandidate(ingredient_name="간장", substitute_name="새우")],
    )

    result = validate(state)

    assert result["substitutes"][0].allergy_conflict is True


def test_validate_leaves_safe_substitute_unflagged():
    state = AgentState(
        selected_ingredients=["밥"],
        allergies=["새우"],
        substitutes=[SubstituteCandidate(ingredient_name="간장", substitute_name="소금")],
    )

    result = validate(state)

    assert result["substitutes"][0].allergy_conflict is False


def test_validate_noop_when_guardrail_blocked():
    state = AgentState(selected_ingredients=["밥"], guardrail_blocked=True)

    assert validate(state) == {}

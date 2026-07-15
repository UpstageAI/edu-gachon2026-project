from app.agent.nodes import resolve_inputs as resolve_inputs_module
from app.agent.state import AgentState


def test_resolve_inputs_converts_ids_to_names(monkeypatch):
    monkeypatch.setattr(
        resolve_inputs_module, "get_ingredient_names_by_ids", lambda ids: ["계란", "밥"]
    )
    monkeypatch.setattr(resolve_inputs_module, "get_allergen_names_by_ids", lambda ids: ["새우"])

    result = resolve_inputs_module.resolve_inputs(
        AgentState(ingredient_ids=["id-1", "id-2"], allergen_ids=["allergen-1"])
    )

    assert result == {"selected_ingredients": ["계란", "밥"], "allergies": ["새우"]}


def test_resolve_inputs_handles_no_allergies():
    result = resolve_inputs_module.resolve_inputs(
        AgentState(ingredient_ids=[], allergen_ids=[])
    )

    assert result == {"selected_ingredients": [], "allergies": []}

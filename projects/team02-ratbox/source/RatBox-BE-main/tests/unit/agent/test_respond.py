from app.agent.nodes.respond import respond
from app.agent.state import AgentState
from app.agent.tools.schemas import ClassifyMissingOutput
from app.domain.models import RecipeCandidate, RecipeDetail, SubstituteCandidate


def test_respond_returns_guardrail_message_when_blocked():
    state = AgentState(
        selected_ingredients=[], guardrail_blocked=True, final_message="차단됨"
    )

    assert respond(state) == {"final_message": "차단됨"}


def test_respond_phase_a_lists_candidates_with_missing_ingredients():
    state = AgentState(
        selected_ingredients=["계란"],
        candidate_recipes=[
            RecipeCandidate(id="1", name="계란밥", missing_ingredients=[]),
            RecipeCandidate(id="2", name="대파계란찜", missing_ingredients=["대파"]),
        ],
    )

    result = respond(state)

    assert "계란밥" in result["final_message"]
    assert "대파" in result["final_message"]


def test_respond_phase_a_handles_zero_candidates():
    state = AgentState(selected_ingredients=["계란"], candidate_recipes=[])

    result = respond(state)

    assert "레시피가 없어요" in result["final_message"]


def test_respond_phase_b_includes_classification_and_substitute_warning():
    state = AgentState(
        selected_ingredients=["계란"],
        recipe_id="1",
        recipe_detail=RecipeDetail(id="1", name="계란밥"),
        missing_classification=ClassifyMissingOutput(
            required=[], optional=["대파"], reason="향만 담당"
        ),
        substitutes=[
            SubstituteCandidate(
                ingredient_name="대파", substitute_name="새우", allergy_conflict=True
            )
        ],
    )

    result = respond(state)

    assert "계란밥" in result["final_message"]
    assert "생략 가능한 재료: 대파" in result["final_message"]
    assert "알레르기 성분일 수 있어요" in result["final_message"]

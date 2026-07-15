from app.agent.nodes.ask_clarification import ask_clarification
from app.agent.nodes.best_effort_response import best_effort_response
from app.agent.nodes.broaden_search import broaden_search
from app.agent.nodes.search_recipes import search_recipes
from app.agent.nodes.verify_relevance import verify_relevance
from app.agent.services import relevance_service, search_service
from app.agent.state import AgentState
from app.domain.models import RecipeCandidate


def test_search_recipes_node_calls_service_with_state_params(monkeypatch):
    captured = {}

    def _fake_search(ingredient_ids, min_match, limit):
        captured["args"] = (ingredient_ids, min_match, limit)
        return [RecipeCandidate(id="1", name="계란밥")]

    monkeypatch.setattr(search_service, "search_recipes", _fake_search)

    state = AgentState(ingredient_ids=["계란-id"], min_match=2, search_limit=20)
    result = search_recipes(state)

    assert captured["args"] == (["계란-id"], 2, 20)
    assert [c.id for c in result["candidate_recipes"]] == ["1"]


def test_verify_relevance_node_reflects_service_result(monkeypatch):
    class _FakeResult:
        passed = True
        reason = "재료 활용도가 좋아요"

    monkeypatch.setattr(relevance_service, "verify", lambda ingredients, candidates: _FakeResult())

    state = AgentState(
        selected_ingredients=["계란"], candidate_recipes=[RecipeCandidate(id="1", name="계란밥")]
    )
    result = verify_relevance(state)

    assert result == {"relevance_passed": True, "relevance_reason": "재료 활용도가 좋아요"}


def test_broaden_search_first_stage_lowers_min_match_only():
    """1단계: min_match가 아직 floor보다 높으면 그것만 낮춘다. search_limit은 아직
    안 건드려야 2단계에서 쓸 완화 여지가 남는다."""
    state = AgentState(min_match=2, search_limit=20, retry_count=0)

    result = broaden_search(state)

    assert result == {"min_match": 1, "retry_count": 1}


def test_broaden_search_second_stage_raises_search_limit_instead():
    """2단계: min_match가 이미 floor(1)라 더 못 낮추니, 대신 search_limit을 크게
    늘려 rank_candidates가 더 넓은 후보 풀을 보게 한다."""
    state = AgentState(min_match=1, search_limit=20, retry_count=1)

    result = broaden_search(state)

    assert result == {"search_limit": 60, "retry_count": 2}


def test_broaden_search_second_stage_keeps_larger_existing_limit():
    state = AgentState(min_match=1, search_limit=80, retry_count=1)

    result = broaden_search(state)

    assert result == {"search_limit": 80, "retry_count": 2}


def test_best_effort_response_includes_reason_and_candidates():
    state = AgentState(
        candidate_recipes=[
            RecipeCandidate(id="1", name="계란밥", missing_ingredients=["대파"])
        ],
        relevance_reason="재료 활용도가 낮아 보여요",
    )

    result = best_effort_response(state)

    assert "계란밥" in result["final_message"]
    assert "재료 활용도가 낮아 보여요" in result["final_message"]
    assert result["low_confidence"] is True


def test_ask_clarification_returns_fixed_message():
    result = ask_clarification(AgentState())

    assert "재료를 몇 가지 더 알려주시면" in result["final_message"]

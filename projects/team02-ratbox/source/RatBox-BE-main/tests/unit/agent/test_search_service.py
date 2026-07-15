from app.agent.services import search_service
from app.domain.models import RecipeCandidate


def _stub_all_core(monkeypatch, ratios: dict[str, float] | None = None):
    """개별 테스트가 가중치/핵심재료 판별 로직 자체를 검증하는 게 아니라면, 모든 재료를
    희귀(코어) 재료로 취급해 기존 매칭개수 기준 동작이 그대로 보이게 한다."""
    monkeypatch.setattr(
        search_service,
        "compute_document_frequency_ratios",
        lambda ids: ratios or {i: 0.0 for i in ids},
    )


def test_search_recipes_returns_empty_when_no_recipe_ids(monkeypatch):
    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", lambda ids: {}
    )

    result = search_service.search_recipes(["없는재료-id"], min_match=1, limit=20)

    assert result == []


def test_search_recipes_filters_by_min_match_and_sorts_by_match_count(monkeypatch):
    matches = {
        "1": ["계란"],  # match_count=1 -> min_match=2 미달, 제외
        "2": ["계란", "대파"],  # match_count=2
        "3": ["계란", "대파", "양파"],  # match_count=3
    }
    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", lambda ids: matches
    )
    _stub_all_core(monkeypatch)
    monkeypatch.setattr(
        search_service,
        "get_recipes_by_ids",
        lambda ids: [
            {"id": "2", "name": "대파계란찜", "cooking_time": 15},
            {"id": "3", "name": "삼색나물", "cooking_time": 20},
        ],
    )

    result = search_service.search_recipes(
        ["계란", "대파", "양파"], min_match=2, limit=20
    )

    assert [c.id for c in result] == ["3", "2"]


def test_search_recipes_respects_limit(monkeypatch):
    monkeypatch.setattr(
        search_service,
        "find_recipe_ingredient_matches",
        lambda ids: {"1": ["계란"], "2": ["계란"], "3": ["계란"]},
    )
    _stub_all_core(monkeypatch)
    monkeypatch.setattr(
        search_service,
        "get_recipes_by_ids",
        lambda ids: [RecipeCandidate(id=i, name=f"레시피{i}").model_dump() for i in ids],
    )

    result = search_service.search_recipes(["계란"], min_match=1, limit=2)

    assert len(result) == 2


def test_search_recipes_excludes_recipes_matched_only_on_generic_ingredients(monkeypatch):
    """소금/감자/우유 버그 재현: 소금(흔함)만 겹치는 레시피는 감자/우유(드묾)가 전혀
    안 겹쳐도 매칭개수(1)만으로는 후보가 됐었다 - 이제는 핵심재료 하드필터로 제외돼야
    한다."""
    matches = {
        "salt-only": ["소금"],
        "potato-milk": ["감자", "우유"],
    }
    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", lambda ids: matches
    )
    monkeypatch.setattr(
        search_service,
        "compute_document_frequency_ratios",
        lambda ids: {"소금": 0.3, "감자": 0.05, "우유": 0.04},
    )
    monkeypatch.setattr(
        search_service,
        "get_recipes_by_ids",
        lambda ids: [{"id": i, "name": i, "cooking_time": None} for i in ids],
    )

    result = search_service.search_recipes(
        ["소금", "감자", "우유"], min_match=1, limit=20
    )

    assert [c.id for c in result] == ["potato-milk"]


def test_search_recipes_ranks_rare_ingredient_match_above_more_generic_matches(monkeypatch):
    """매칭 개수는 같아도(2개), 흔한 재료 2개보다 드문 재료 2개가 겹친 레시피가 더
    가중치가 높아야 한다."""
    matches = {
        "generic-match": ["소금", "후추"],
        "rare-match": ["감자", "우유"],
    }
    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", lambda ids: matches
    )
    monkeypatch.setattr(
        search_service,
        "compute_document_frequency_ratios",
        lambda ids: {"소금": 0.3, "후추": 0.06, "감자": 0.05, "우유": 0.04},
    )
    monkeypatch.setattr(
        search_service,
        "get_recipes_by_ids",
        lambda ids: [{"id": i, "name": i, "cooking_time": None} for i in ids],
    )

    result = search_service.search_recipes(
        ["소금", "후추", "감자", "우유"], min_match=2, limit=20
    )

    assert [c.id for c in result] == ["rare-match", "generic-match"]


def test_search_recipes_attaches_match_score_to_candidates(monkeypatch):
    """recipe_service.rank_candidates가 최종 순위에도 가중치를 반영하려면, search_service가
    계산한 점수가 후보 풀 선정 후 버려지지 않고 RecipeCandidate에 실려 나가야 한다."""
    matches = {"rare-match": ["감자", "우유"]}
    monkeypatch.setattr(
        search_service, "find_recipe_ingredient_matches", lambda ids: matches
    )
    monkeypatch.setattr(
        search_service,
        "compute_document_frequency_ratios",
        lambda ids: {"감자": 0.05, "우유": 0.04},
    )
    monkeypatch.setattr(
        search_service,
        "get_recipes_by_ids",
        lambda ids: [{"id": i, "name": i, "cooking_time": None} for i in ids],
    )

    result = search_service.search_recipes(["감자", "우유"], min_match=2, limit=20)

    assert result[0].match_score == (1 - 0.05) + (1 - 0.04)

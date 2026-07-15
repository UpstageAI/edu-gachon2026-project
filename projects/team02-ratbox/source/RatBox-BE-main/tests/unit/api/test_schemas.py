from app.api.schemas.request import RecommendRequest


def test_recommend_request_phase_a_without_recipe_id():
    request = RecommendRequest(ingredient_ids=["id-1", "id-2"])
    assert request.recipe_id is None
    assert request.ingredient_ids == ["id-1", "id-2"]
    assert request.allergen_ids == []


def test_recommend_request_phase_b_with_recipe_id():
    request = RecommendRequest(
        ingredient_ids=["id-1"], allergen_ids=["allergen-1"], recipe_id="r1"
    )
    assert request.recipe_id == "r1"
    assert request.allergen_ids == ["allergen-1"]

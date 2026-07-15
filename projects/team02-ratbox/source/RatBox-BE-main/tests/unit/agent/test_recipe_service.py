from app.agent.services import recipe_service
from app.domain.models import RecipeCandidate


def _patch_ingredients(monkeypatch, by_id: dict):
    monkeypatch.setattr(
        recipe_service, "get_recipe_ingredient_names", lambda recipe_id: by_id[recipe_id]
    )


def test_rank_candidates_excludes_allergen_recipes(monkeypatch):
    _patch_ingredients(
        monkeypatch,
        {
            "1": [{"name": "새우", "is_required": True}, {"name": "밥", "is_required": True}],
            "2": [{"name": "계란", "is_required": True}, {"name": "밥", "is_required": True}],
        },
    )
    candidates = [
        RecipeCandidate(id="1", name="새우볶음밥"),
        RecipeCandidate(id="2", name="계란밥"),
    ]

    ranked = recipe_service.rank_candidates(candidates, ["밥"], allergies=["새우"])

    assert [c.id for c in ranked] == ["2"]


def test_rank_candidates_excludes_allergen_alias_compound_words(monkeypatch):
    # 이슈 #42: "게" 알레르기를 등록했는데도 "대게"가 든 레시피가 그대로 추천되던 버그.
    _patch_ingredients(
        monkeypatch,
        {
            "1": [{"name": "대게", "is_required": True}, {"name": "밥", "is_required": True}],
            "2": [{"name": "계란", "is_required": True}, {"name": "밥", "is_required": True}],
        },
    )
    candidates = [
        RecipeCandidate(id="1", name="대게찜"),
        RecipeCandidate(id="2", name="계란밥"),
    ]

    ranked = recipe_service.rank_candidates(candidates, ["밥"], allergies=["게"])

    assert [c.id for c in ranked] == ["2"]


def test_rank_candidates_sorts_by_missing_count_ascending(monkeypatch):
    _patch_ingredients(
        monkeypatch,
        {
            "1": [{"name": "계란", "is_required": True}, {"name": "대파", "is_required": True}],
            "2": [{"name": "계란", "is_required": True}],
        },
    )
    candidates = [
        RecipeCandidate(id="1", name="대파계란찜"),
        RecipeCandidate(id="2", name="계란밥"),
    ]

    ranked = recipe_service.rank_candidates(candidates, ["계란"], allergies=[])

    assert [c.id for c in ranked] == ["2", "1"]
    assert ranked[0].missing_ingredients == []
    assert ranked[1].missing_ingredients == ["대파"]
    # verify_relevance가 "왜 매칭됐는지" 볼 수 있도록 겹치는 재료도 같이 채워야 한다.
    assert ranked[0].matched_ingredients == ["계란"]
    assert ranked[1].matched_ingredients == ["계란"]


def test_rank_candidates_limits_to_top_three(monkeypatch):
    _patch_ingredients(
        monkeypatch, {str(i): [{"name": "계란", "is_required": True}] for i in range(1, 6)}
    )
    candidates = [RecipeCandidate(id=str(i), name=f"레시피{i}") for i in range(1, 6)]

    ranked = recipe_service.rank_candidates(candidates, ["계란"], allergies=[])

    assert len(ranked) == 3


def test_rank_candidates_excludes_low_coverage_matches(monkeypatch):
    """실제 버그 재현: 재료 5개짜리 바나나피자에 오일 1개만(20%) 겹쳐도 search_service의
    핵심재료 하드필터만으로는 통과했었다 - 커버리지 비율(매칭/전체)이 너무 낮은 후보는
    여기서 걸러야 한다."""
    _patch_ingredients(
        monkeypatch,
        {
            "banana-pizza": [
                {"name": "바나나", "is_required": True},
                {"name": "계란", "is_required": True},
                {"name": "소금", "is_required": True},
                {"name": "모짜렐라 치즈", "is_required": True},
                {"name": "오일", "is_required": True},
            ],
            "oil-fried-egg": [
                {"name": "계란", "is_required": True},
                {"name": "오일", "is_required": True},
            ],
        },
    )
    candidates = [
        RecipeCandidate(id="banana-pizza", name="바나나피자"),
        RecipeCandidate(id="oil-fried-egg", name="계란후라이"),
    ]

    ranked = recipe_service.rank_candidates(candidates, ["오일"], allergies=[])

    assert [c.id for c in ranked] == ["oil-fried-egg"]


def test_rank_candidates_sorts_by_match_score_before_missing_count(monkeypatch):
    """가중치 점수가 높은 후보가, 부족 재료 수가 더 적은 후보보다 우선해야 한다 -
    search_service가 계산한 가중치가 최종 노출 순서에도 실제로 반영되는지 검증."""
    _patch_ingredients(
        monkeypatch,
        {
            "rare-core-match": [
                {"name": "감자", "is_required": True},
                {"name": "우유", "is_required": True},
                {"name": "양파", "is_required": True},
            ],
            "fewer-missing-but-weak": [
                {"name": "감자", "is_required": True},
            ],
        },
    )
    candidates = [
        RecipeCandidate(id="rare-core-match", name="감자수프", match_score=1.9),
        RecipeCandidate(id="fewer-missing-but-weak", name="감자조림", match_score=0.5),
    ]

    ranked = recipe_service.rank_candidates(
        candidates, ["감자", "우유"], allergies=[]
    )

    assert [c.id for c in ranked] == ["rare-core-match", "fewer-missing-but-weak"]

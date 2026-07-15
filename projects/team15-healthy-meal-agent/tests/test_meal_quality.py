"""
tests/test_meal_quality.py
조합 품질 개선(2026-07-14) 회귀 방지 테스트. 외부 LLM 없이 결정론적으로 검증.
  - 완성밥요리(볶음밥 등)가 '밥'이 아니라 '한그릇'으로 재분류되는지
  - 백반 조합에 완성밥요리가 밥 자리에 안 오는지
  - Judge 실패 시 규칙 1등으로 폴백하는지
"""

from app.schemas import UserConditions, UserProfile
from app.services.food_retriever import (
    effective_role,
    is_dessert,
    load_foods,
    match_wanted_foods,
    retrieve_foods,
)
from app.services.meal_composer import _with_forced, compose_meal
from app.services.nutrition_calculator import calculate_nutrition


# ── 1. 완성밥요리 역할 재분류 ────────────────
def test_complete_rice_reclassified_to_onebowl():
    assert effective_role("파인애플볶음밥", "밥") == "한그릇"
    assert effective_role("소고기리조또롤", "밥") == "한그릇"
    assert effective_role("전복죽", "밥") == "한그릇"
    assert effective_role("참치김밥", "밥") == "한그릇"


def test_pure_rice_stays_rice():
    assert effective_role("쌀밥", "밥") == "밥"
    assert effective_role("현미밥", "밥") == "밥"
    assert effective_role("잡곡밥", "밥") == "밥"


def test_dessert_detection():
    assert is_dessert("망고무스케이크와 마카롱")
    assert is_dessert("고구마 찰 빵")
    assert not is_dessert("김치찌개")
    assert not is_dessert("현미밥")


# ── 2. 밥 역할 버킷엔 순수 밥만 (완성밥요리 없음) ────────────
def test_rice_bucket_has_no_complete_rice_dishes():
    from app.services.food_retriever import _COMPLETE_RICE_KEYWORDS

    foods = load_foods()
    rice = [f for f in foods if f.meal_role == "밥"]
    for f in rice:
        assert not any(k in f.food_name for k in _COMPLETE_RICE_KEYWORDS), (
            f"완성밥요리가 밥 버킷에: {f.food_name}"
        )


# ── 3. 백반 조합엔 반드시 순수 밥이 포함 (밥 없는 백반 방지) ────────────
def test_bansang_contains_rice():
    cond = UserConditions(target_kcal=600, kcal_mode="upper", meal_style="백반")
    mp = compose_meal(retrieve_foods(cond, UserProfile(), foods=load_foods()), cond, seed=0)
    assert mp.meal_type == "백반"
    roles = {f.meal_role for f in mp.items}
    assert "밥" in roles, f"백반인데 밥이 없음: {[f.food_name for f in mp.items]}"


# ── 4. 디저트는 한 끼 후보에 안 들어감 ────────────
def test_no_dessert_in_candidates():
    cond = UserConditions(target_kcal=500, kcal_mode="upper")
    result = retrieve_foods(cond, UserProfile(), foods=load_foods())
    for foods in result.values():
        for f in foods:
            assert not is_dessert(f.food_name), f"디저트가 후보에: {f.food_name}"


# ── 5. compose는 정상 MealPlan을 낸다 (Judge 없이 규칙 폴백 경로) ────────────
def test_compose_produces_valid_plan_without_llm():
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    mp = compose_meal(retrieve_foods(cond, UserProfile(), foods=load_foods()), cond, seed=0)
    assert mp.items
    total = calculate_nutrition(mp).total_kcal
    assert total <= 400  # 예산 준수


# ── 6. 강제 포함(wanted) 메인이 있으면 조합에 메인 중복 안 됨 ────────────
def test_forced_main_no_duplicate_main():
    foods = {f.food_name: f for f in load_foods()}
    bibim = next(f for n, f in foods.items() if "비빔밥" in n)  # 한그릇(재분류됨)
    onebowl = next(
        f for f in foods.values() if f.meal_role == "한그릇" and f.food_id != bibim.food_id
    )
    combo = _with_forced([onebowl], [bibim])
    mains = [f for f in combo if f.meal_role in ("밥", "한그릇")]
    assert len(mains) == 1, f"메인이 2개 이상: {[f.food_name for f in mains]}"


# ── 7. 분류어(국/밥)는 wanted_foods 매칭에서 무시 ────────────
def test_generic_words_ignored_in_wanted():
    foods = load_foods()
    matched, missing = match_wanted_foods(["국", "밥"], foods)
    assert matched == {}  # 강제 포함 안 함
    assert missing == []  # '없다' 안내도 안 함


def test_real_dish_still_matches():
    foods = load_foods()
    matched, missing = match_wanted_foods(["김치찌개"], foods)
    assert "김치찌개" in matched  # 진짜 음식명은 매칭
    assert "김치찌개" in matched["김치찌개"].food_name


# ── 8. 되묻기 안전망: 조건 신호 있으면 추천으로 ────────────
def test_condition_signal_overrides_need_more_info():
    from app.agents.graph import _has_condition_signal

    assert _has_condition_signal("국이랑 밥 있는 한식")
    assert _has_condition_signal("운동하는데 뭐먹지")
    assert _has_condition_signal("400kcal 담백하게")
    # 진짜 조건 없는 것은 False
    assert not _has_condition_signal("뭐 먹지?")
    assert not _has_condition_signal("추천해줘")


# ── 9. 국물 요청 시 조합에 국물이 포함됨 ────────────
def test_soup_request_includes_soup():
    cond = UserConditions(preferences=["얼큰한", "국물"], meal_style="백반")
    mp = compose_meal(retrieve_foods(cond, UserProfile(), foods=load_foods()), cond, seed=0)
    roles = [f.meal_role for f in mp.items]
    assert "국물" in roles, f"국물 요청인데 국이 없음: {[f.food_name for f in mp.items]}"

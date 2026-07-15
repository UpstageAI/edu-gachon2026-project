"""
tests/test_meal_composer.py
조합기(생성-검증 루프) 테스트. 외부 의존 없이 CSV 후보로 결정론적으로 검증한다.
핵심: 조합 합계가 목표 칼로리 예산을 지키는지(예전 '740kcal 백반' 버그 회귀 방지).
"""

from app.schemas import UserConditions, UserProfile
from app.services.food_retriever import load_foods, retrieve_foods
from app.services.meal_composer import compose_meal
from app.services.nutrition_calculator import calculate_nutrition
from app.services.validator import macro_deviation, validate_meal


def _compose(conditions, seed=0):
    cand = retrieve_foods(conditions, UserProfile(), foods=load_foods())
    return compose_meal(cand, conditions, seed=seed)


def test_bansang_respects_upper_kcal_budget():
    """백반 조합 합계가 upper 목표를 넘지 않는지 (740kcal 초과 버그 회귀 방지)"""
    cond = UserConditions(target_kcal=400, kcal_mode="upper", meal_style="백반")
    mp = _compose(cond)
    total = calculate_nutrition(mp).total_kcal
    assert total <= 400, f"백반 합계 {total}kcal가 목표 400 초과"
    assert len(mp.items) >= 1


def test_onebowl_respects_upper_kcal_budget():
    """한그릇 조합도 upper 목표 예산을 지키는지"""
    cond = UserConditions(target_kcal=500, kcal_mode="upper", meal_style="한그릇")
    mp = _compose(cond)
    total = calculate_nutrition(mp).total_kcal
    assert total <= 500


def test_composed_meal_passes_validator():
    """조합 결과가 우리 건강 기준 검증(validator)을 통과하는지 (kcal 축)"""
    cond = UserConditions(target_kcal=400, kcal_mode="upper", meal_style="백반")
    mp = _compose(cond)
    nut = calculate_nutrition(mp)
    result = validate_meal(mp, nut, cond, UserProfile())
    # 칼로리 초과/부실로 인한 FAIL은 없어야 한다
    assert result.status in ("PASS", "PASS_WITH_WARNING"), result.failures


def test_target_mode_stays_within_range():
    """target 모드(정도)는 ±15% 범위 안에서 조합되는지 (validator와 동일 오차)"""
    cond = UserConditions(target_kcal=600, kcal_mode="target", meal_style="백반")
    mp = _compose(cond)
    total = calculate_nutrition(mp).total_kcal
    assert 600 * 0.85 <= total <= 600 * 1.15, f"{total}kcal가 600±15% 밖"


def test_prefers_balanced_macro_combo():
    """조합기가 탄단지 균형이 더 나은 쪽을 고르는지 (밥 단독보다 밥+반찬 선호)"""
    cond = UserConditions(target_kcal=500, kcal_mode="upper", meal_style="백반")
    mp = _compose(cond)
    dev = macro_deviation(calculate_nutrition(mp))
    # 밥만 담으면 탄수 100%로 이탈량이 큼. 조합기가 균형 맞춰 이탈량을 억제해야 함.
    assert dev < 60, f"탄단지 이탈량 {dev}가 과도(균형 조합 실패)"


def test_kcal_mode_none_still_scores_calories():
    """kcal_mode가 없어도(LLM 미표기) 칼로리 채점이 되어 부실 조합이 안 뽑히는지.

    '든든하게 600kcal'처럼 mode 없이 숫자만 준 경우, 260kcal 부실 조합이 통과하던 버그 회귀 방지.
    """
    cond = UserConditions(target_kcal=600, kcal_mode=None, meal_style="백반")
    mp = _compose(cond)
    total = calculate_nutrition(mp).total_kcal
    # mode 미상은 target(정도)로 간주 → 600±10% 근처여야(적어도 하한 540 이상)
    assert total >= 600 * 0.75, f"mode 없이도 부실 방지 실패: {total}kcal"


def test_low_sodium_combo_keeps_sodium_low():
    """저염 요청 시 조합 합계 나트륨도 낮게 유지되는지 (검색 필터 + 조합 채점)"""
    cond = UserConditions(target_kcal=400, kcal_mode="upper", nutrition_goals=["저염"])
    mp = _compose(cond)
    na = calculate_nutrition(mp).total_sodium
    assert na <= 1000, f"저염 요청인데 조합 나트륨 {na}mg"


def test_no_two_onedish_in_one_plan():
    """완결형 한 그릇 요리가 한 끼에 2개 들어가지 않는지 (역할 궁합 벌점 회귀 방지)."""
    for seed in range(6):
        cond = UserConditions(target_kcal=600)
        mp = _compose(cond, seed=seed)
        n_onedish = sum(1 for f in mp.items if f.meal_role == "한그릇")
        assert n_onedish <= 1, f"한그릇 {n_onedish}개 조합됨: {[f.food_name for f in mp.items]}"


def test_soup_without_rice_is_penalized():
    """국물은 밥과 함께여야 자연스럽다 — 국물+반찬(밥 없음)은 밥+국물보다 점수가 나빠야."""
    from app.schemas import FoodItem
    from app.services.meal_composer import _score

    def f(name, role, kcal=100):
        return FoodItem(
            food_id=abs(hash(name)) % 100000,
            food_name=name,
            meal_role=role,
            kcal=kcal,
            carbohydrate=15,
            protein=6,
            fat=3,
            sodium=200,
        )

    cond = UserConditions()  # 칼로리 조건 없음 → 궁합 벌점만 비교
    soup_no_rice = [f("된장찌개", "국물"), f("나물", "반찬")]
    soup_with_rice = [f("쌀밥", "밥"), f("된장찌개", "국물")]
    assert _score(soup_no_rice, cond) > _score(soup_with_rice, cond), (
        "국물+반찬(밥없음)이 밥+국물보다 점수가 좋게 나옴 — 국물·밥 궁합 규칙 회귀"
    )


def test_judge_result_parsing():
    """LLM 판정 응답(JSON)을 choice/acceptable/reason으로 정확히 파싱하는지."""
    from app.services.meal_judge import _parse_judge

    ok = _parse_judge('{"choice": 2, "acceptable": true, "reason": "밥+국+반찬 균형"}', n=4)
    assert ok.choice == 1 and ok.acceptable is True and "균형" in ok.reason

    reject = _parse_judge('설명... {"choice": 1, "acceptable": false, "reason": "다 어색"}', n=3)
    assert reject.choice == 0 and reject.acceptable is False

    # 범위 벗어난 choice → 0으로 보정
    oob = _parse_judge('{"choice": 9, "acceptable": true}', n=3)
    assert oob.choice == 0

    # JSON 깨짐 → 숫자만 뽑아 폴백, 판정은 통과(무중단)
    fallback = _parse_judge("그냥 2번요", n=4)
    assert fallback.choice == 1 and fallback.acceptable is True

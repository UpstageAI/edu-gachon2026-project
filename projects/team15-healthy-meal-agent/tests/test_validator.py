from app.schemas import MealPlan, FoodItem, NutritionTotal, UserConditions, UserProfile
from app.services.validator import validate_meal


def _food(name="김밥", kcal=300, sodium=500):
    return FoodItem(
        food_id=1,
        food_name=name,
        meal_role="한그릇",
        serving_size=200,
        kcal=kcal,
        carbohydrate=40,
        protein=10,
        fat=8,
        sugar=3,
        sodium=sodium,
    )


def test_calorie_over_fails():
    """칼로리 초과 → FAIL"""
    mp = MealPlan(meal_type="한그릇", items=[_food(kcal=600)])
    nt = NutritionTotal(total_kcal=600, total_sodium=300)
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    vr = validate_meal(mp, nt, cond, UserProfile())
    assert vr.status == "FAIL"


def test_sodium_over_1500_fails():
    """나트륨 1500 초과 → FAIL"""
    mp = MealPlan(meal_type="한그릇", items=[_food(sodium=1600)])
    nt = NutritionTotal(total_kcal=350, total_sodium=1600)
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    vr = validate_meal(mp, nt, cond, UserProfile())
    assert vr.status == "FAIL"


def test_sodium_warning():
    """나트륨 900 → PASS_WITH_WARNING"""
    mp = MealPlan(meal_type="한그릇", items=[_food(sodium=900)])
    nt = NutritionTotal(total_kcal=350, total_sodium=900)
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    vr = validate_meal(mp, nt, cond, UserProfile())
    assert vr.status == "PASS_WITH_WARNING"


def test_allergy_included_fails():
    """알레르기 음식 포함(이름 매칭) → FAIL"""
    mp = MealPlan(meal_type="한그릇", items=[_food(name="계란볶음밥")])
    nt = NutritionTotal(total_kcal=350, total_sodium=300)
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    prof = UserProfile(allergies=["계란"])
    vr = validate_meal(mp, nt, cond, prof)
    assert vr.status == "FAIL"


def test_allergy_in_ingredients_fails():
    """이름엔 없지만 '재료'에 알레르겐이 있으면 → FAIL (반죽 속 계란 등 숨은 알레르겐)."""
    food = _food(name="양배추감자전")
    food.ingredients = "감자 100g, 양배추 50g, 계란 1개, 밀가루 30g"
    mp = MealPlan(meal_type="한그릇", items=[food])
    nt = NutritionTotal(total_kcal=350, total_sodium=300)
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    prof = UserProfile(allergies=["계란"])
    vr = validate_meal(mp, nt, cond, prof)
    assert vr.status == "FAIL", "재료 속 계란을 못 잡음 — 숨은 알레르겐 방어 회귀"


def _bowl(name, kcal=300, role="한그릇"):
    return FoodItem(
        food_id=abs(hash(name)) % 100000,
        food_name=name,
        meal_role=role,
        kcal=kcal,
        carbohydrate=40,
        protein=10,
        fat=8,
        sodium=200,
    )


def test_implicit_high_kcal_warns_not_fails():
    """target 없는 요청이 한 끼 상식 상한(900)을 넘으면 FAIL이 아니라 경고."""
    mp = MealPlan(meal_type="한그릇", items=[_bowl("비빔밥", 500), _bowl("덮밥", 450)])
    nt = NutritionTotal(total_kcal=950, total_sodium=300)
    cond = UserConditions()  # target_kcal 없음
    vr = validate_meal(mp, nt, cond, UserProfile())
    assert vr.status == "PASS_WITH_WARNING"
    assert any("칼로리가 높은" in w for w in vr.warnings)


def test_two_mains_warns():
    """완결형 메인(한그릇/밥) 2개면 무겁다는 경고. FAIL은 아님."""
    mp = MealPlan(meal_type="한그릇", items=[_bowl("채소비빔밥", 300), _bowl("불고기덮밥", 330)])
    nt = NutritionTotal(total_kcal=630, total_sodium=300)
    vr = validate_meal(mp, nt, UserConditions(), UserProfile())
    assert vr.status == "PASS_WITH_WARNING"
    assert any("완결형 요리가 여러 개" in w for w in vr.warnings)


def test_duplicate_ingredient_warns():
    """같은 주재료(닭)가 여러 음식에 겹치면 경고."""
    mp = MealPlan(
        meal_type="한그릇",
        items=[
            _bowl("닭가슴살말이", 230, role="반찬"),
            _bowl("닭고기볶음밥", 400),
        ],
    )
    nt = NutritionTotal(total_kcal=630, total_sodium=300)
    vr = validate_meal(mp, nt, UserConditions(), UserProfile())
    assert any("'닭' 재료가 여러 음식" in w for w in vr.warnings)


def test_normal_meal_no_false_warning():
    """정상 백반(밥+국+반찬)엔 새로 넣은 경고(칼로리·메인중복·재료중복)가 안 뜬다(오탐 방지)."""
    mp = MealPlan(
        meal_type="백반",
        items=[
            _bowl("현미밥", 200, role="밥"),
            _bowl("된장국", 50, role="국물"),
            _bowl("시금치나물", 60, role="반찬"),
        ],
    )
    # 탄단지 균형 잡힌 값 → macro 경고와 무관하게, 우리가 추가한 경고만 검사
    nt = NutritionTotal(
        total_kcal=310, total_carbohydrate=45, total_protein=15, total_fat=8, total_sodium=300
    )
    vr = validate_meal(mp, nt, UserConditions(), UserProfile())
    new_warning_keys = ("칼로리가 높은", "완결형 요리가 여러 개", "재료가 여러 음식")
    assert not any(k in w for w in vr.warnings for k in new_warning_keys)

"""
app/services/validator.py
식단 검증. 칼로리·제외음식은 FAIL(엄격), 나트륨은 단계별 등급.
"""

from app.schemas import MealPlan, NutritionTotal, UserConditions, UserProfile, ValidationResult

# target("정도") 모드 칼로리 허용 오차. 검색·조합·검증이 모두 이 값을 공유해 엇박자를 막는다.
# 한 끼 조합은 개별 음식 단위가 커서 ±10%는 통과율이 빡빡 → ±15%로 완화.
TARGET_KCAL_TOLERANCE = 0.15

# 사용자가 칼로리를 안 밝힌 요청("비빔밥 덮밥", "고기 먹고싶다")의 한 끼 상식 상한.
# 성인 하루 ~2000kcal / 3끼 ≈ 667. 한 끼 900 초과는 "무거운 한 끼"로 경고(FAIL 아님).
# → 사용자가 콕 집은 조합은 존중하되, 결과가 무거우면 사실을 정직하게 알린다.
MEAL_KCAL_SOFT_MAX = 900


def validate_meal(
    meal_plan: MealPlan, nutrition: NutritionTotal, conditions: UserConditions, profile: UserProfile
) -> ValidationResult:
    failures = []
    warnings = []
    cause = None

    # ── 1. 칼로리 (FAIL 엄격) ──
    if conditions.target_kcal:
        kcal = nutrition.total_kcal
        if conditions.kcal_mode == "upper":
            if kcal > conditions.target_kcal:
                failures.append(
                    f"목표 {conditions.target_kcal:.0f}kcal 이하인데 {kcal:.0f}kcal로 초과했습니다."
                )
                cause = "compose"
            elif kcal < conditions.target_kcal * 0.75:
                failures.append(f"{kcal:.0f}kcal로 너무 낮아 한 끼로 부실합니다.")
                cause = "compose"
        elif conditions.kcal_mode == "target":
            lo = conditions.target_kcal * (1 - TARGET_KCAL_TOLERANCE)
            hi = conditions.target_kcal * (1 + TARGET_KCAL_TOLERANCE)
            if not (lo <= kcal <= hi):
                failures.append(
                    f"목표 {conditions.target_kcal:.0f}kcal "
                    f"±{TARGET_KCAL_TOLERANCE * 100:.0f}% 범위를 벗어났습니다({kcal:.0f}kcal)."
                )
                cause = "compose"
    else:
        # 칼로리를 안 밝힌 요청 — 한 끼 상식 상한만 본다. FAIL 아니라 경고(정직한 안내).
        # 사용자가 콕 집은 조합("비빔밥 덮밥")은 존중하되 무거우면 사실을 알린다.
        if nutrition.total_kcal > MEAL_KCAL_SOFT_MAX:
            warnings.append(
                f"이 조합은 한 끼로 칼로리가 높은 편입니다({nutrition.total_kcal:.0f}kcal). "
                "가볍게 드시려면 하나를 덜어내는 것을 권합니다."
            )

    # ── 1-2. 메인 중복 (경고) ──
    # 완결형 한 그릇/밥 메인이 2개 이상이면(비빔밥+덮밥 등) 한 끼로 무겁다는 사실을 알린다.
    # 사용자가 콕 집어 둘 다 넣었을 수 있으니 FAIL이 아니라 경고로 존중+안내.
    mains = [f for f in meal_plan.items if f.meal_role in ("한그릇", "밥")]
    if len(mains) >= 2:
        names = ", ".join(f.food_name for f in mains)
        warnings.append(
            f"완결형 요리가 여러 개 담겼습니다({names}). 한 끼로는 다소 무거울 수 있어요."
        )

    # ── 1-3. 주재료 중복 (경고) ──
    # 닭+닭, 생선+생선처럼 같은 주재료가 여러 음식에 겹치면 한 끼로 단조롭다는 사실을 알린다.
    dup = _duplicate_main_ingredient(meal_plan.items)
    if dup:
        warnings.append(
            f"'{dup}' 재료가 여러 음식에 겹칩니다. 다양하게 드시려면 하나를 바꿔보세요."
        )

    # ── 2. 제외음식/알레르기 (FAIL 엄격) ──
    # 이름뿐 아니라 '재료'까지 검사한다 — 이름에 안 드러난 알레르겐(반죽 속 계란 등) 차단.
    excluded = list(profile.allergies) + list(conditions.exclude_foods)
    for food in meal_plan.items:
        haystack = f"{food.food_name} {getattr(food, 'ingredients', '') or ''}"
        for x in excluded:
            if x and x in haystack:
                failures.append(f"제외 대상 '{x}'이(가) '{food.food_name}'에 포함됐습니다.")
                cause = "retrieve"  # 후보 검색이 잘못 걸러진 것 → 검색부터 다시

    # ── 3. 나트륨 (단계별 등급) ──
    na = nutrition.total_sodium
    if na <= 767:
        pass
    elif na <= 1000:
        warnings.append("나트륨이 기준보다 약간 높아요.")
    elif na <= 1300:
        warnings.append("나트륨이 다소 높습니다. 저염 대안을 고려해보세요.")
    elif na <= 1500:
        warnings.append("나트륨이 높습니다. 국물을 남기는 것을 권합니다.")
    else:  # 1500 초과 → FAIL
        failures.append(f"나트륨이 {na:.0f}mg으로 과다합니다.")
        cause = "compose"

    # ── 4. 탄단지 에너지비율 (주의만, FAIL 아님) ──
    # 문서 v4 §6: KDRI 에너지적정비율 ±5%p 완충. g이 아니라 "에너지(kcal) 비율"로 판정.
    #   탄수 g×4, 단백 g×4, 지방 g×9 → 각 비율. 이탈 개수 무관하게 warning.
    #   (탄단지는 하루 평균 개념이라 한 끼 엄격 FAIL은 정상식단 과다탈락 → 안전축은 kcal·나트륨·알레르기)
    macro_warnings = _macro_ratio_warnings(nutrition)
    warnings.extend(macro_warnings)

    # ── 판정 ──
    if failures:
        status = "FAIL"
    elif warnings:
        status = "PASS_WITH_WARNING"
    else:
        status = "PASS"

    return ValidationResult(status=status, warnings=warnings, failures=failures, cause=cause)


# 주재료 중복 감지용 대표 단백질 재료. 음식명에 같은 게 2번 이상 나오면 단조로운 한 끼.
_MAIN_INGREDIENTS = (
    "닭",
    "돼지",
    "소고기",
    "쇠고기",
    "생선",
    "연어",
    "고등어",
    "꽁치",
    "새우",
    "오리",
    "두부",
)


def _duplicate_main_ingredient(items) -> str | None:
    """한 끼에 같은 주재료(닭·생선 등)가 2개 이상 음식에 겹치면 그 재료명을 반환. 없으면 None."""
    for ing in _MAIN_INGREDIENTS:
        cnt = sum(1 for f in items if ing in f.food_name)
        if cnt >= 2:
            return ing
    return None


# ── 탄단지 에너지비율 (문서 v4 §6) ─────────────────────────────
# KDRI 적정비율 ±5%p 완충. 한 끼 검증 범위.
MACRO_RANGES = {
    "탄수화물": (45, 70),
    "단백질": (5, 25),
    "지방": (10, 35),
}


def macro_energy_ratios(nutrition: NutritionTotal) -> dict[str, float]:
    """탄단지를 에너지(kcal) 비율(%)로 환산. 탄4·단4·지9 kcal/g."""
    c_kcal = nutrition.total_carbohydrate * 4
    p_kcal = nutrition.total_protein * 4
    f_kcal = nutrition.total_fat * 9
    total = c_kcal + p_kcal + f_kcal
    if total <= 0:
        return {"탄수화물": 0.0, "단백질": 0.0, "지방": 0.0}
    return {
        "탄수화물": c_kcal / total * 100,
        "단백질": p_kcal / total * 100,
        "지방": f_kcal / total * 100,
    }


def macro_deviation(nutrition: NutritionTotal) -> float:
    """탄단지 3항목이 적정범위에서 벗어난 총량(%p). 0이면 완벽 균형.

    조합기(생성-검증 루프)가 '더 균형 잡힌 조합'을 고르는 점수로 재사용한다.
    """
    ratios = macro_energy_ratios(nutrition)
    dev = 0.0
    for name, (lo, hi) in MACRO_RANGES.items():
        v = ratios[name]
        if v < lo:
            dev += lo - v
        elif v > hi:
            dev += v - hi
    return dev


def _macro_ratio_warnings(nutrition: NutritionTotal) -> list[str]:
    """적정범위를 벗어난 탄단지 항목마다 경고 문구(FAIL 아님)."""
    ratios = macro_energy_ratios(nutrition)
    msgs: list[str] = []
    for name, (lo, hi) in MACRO_RANGES.items():
        v = ratios[name]
        if v > hi:
            msgs.append(f"{name} 비중이 다소 높아요({v:.0f}%).")
        elif v < lo:
            msgs.append(f"{name} 비중이 다소 낮아요({v:.0f}%).")
    return msgs

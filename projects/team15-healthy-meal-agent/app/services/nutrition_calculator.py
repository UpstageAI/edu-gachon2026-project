"""
app/services/nutrition_calculator.py
식단의 영양성분을 코드로 합산 (LLM 추정 금지).
"""

from app.schemas import MealPlan, NutritionTotal


def calculate_nutrition(meal_plan: MealPlan) -> NutritionTotal:
    total = NutritionTotal()
    for food in meal_plan.items:
        # NaN 방어: 값이 비정상이면 0으로 (전처리에서 걸렀지만 이중 안전)
        total.total_kcal += _safe(food.kcal)
        total.total_carbohydrate += _safe(food.carbohydrate)
        total.total_protein += _safe(food.protein)
        total.total_fat += _safe(food.fat)
        total.total_sugar += _safe(food.sugar)
        total.total_sodium += _safe(food.sodium)

    # 소수점 1자리 정리
    for field in total.model_fields:
        setattr(total, field, round(getattr(total, field), 1))
    return total


def _safe(x) -> float:
    """NaN이나 None이면 0."""
    try:
        if x is None or x != x:  # x != x는 NaN 판별
            return 0.0
        return float(x)
    except (TypeError, ValueError):
        return 0.0

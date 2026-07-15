"""Phase B: 사용자가 선택한 레시피 한 건에 대해서만 부족 재료 분류 + 대체재 판단을 수행한다.

에이전트가 도구를 자율 선택할 필요가 없는 결정론적 파이프라인이라 react_agent 루프를
쓰지 않고 Service를 직접 호출한다.
"""

from langfuse import observe

from app.agent.services import classification_service, steps_service, substitute_service
from app.agent.state import AgentState
from app.data.repositories.recipe_repository import get_recipe_by_id, get_recipe_ingredient_names
from app.domain.models import RecipeDetail


@observe(name="classify_and_substitute")
def classify_and_substitute(state: AgentState) -> dict:
    recipe = get_recipe_by_id(state.recipe_id)
    if recipe is None:
        return {
            "guardrail_blocked": True,
            "guardrail_reason": "레시피를 찾을 수 없음",
            "final_message": "선택한 레시피를 찾을 수 없어요.",
        }

    recipe_detail = RecipeDetail(**recipe)

    full_names = [row["name"] for row in get_recipe_ingredient_names(state.recipe_id)]
    missing = [name for name in full_names if name not in state.selected_ingredients]
    owned = [name for name in full_names if name in state.selected_ingredients]

    steps = steps_service.generate(
        recipe_detail.name, recipe_detail.category, recipe_detail.cooking_method, full_names
    ).steps

    if not missing:
        return {
            "recipe_detail": recipe_detail,
            "owned_ingredients": owned,
            "missing_ingredients": [],
            "cooking_steps": steps,
        }

    classification = classification_service.classify(state.recipe_id, state.selected_ingredients)

    # 생략 가능(optional)으로 분류된 재료는 없어도 조리에 지장이 없으니 대체재를 찾을
    # 필요가 없다 - missing 전체를 돌면 "물"처럼 사실상 항상 있다고 봐도 되는 재료까지
    # 억지로 대체재를 찾다가(예: 물 대신 계란) 엉뚱한 결과가 나온다.
    substitutes = []
    for name in classification.required:
        other_ingredients = [n for n in full_names if n != name]
        result = substitute_service.find(
            name,
            recipe_detail.name,
            recipe_detail.category,
            other_ingredients,
            owned_ingredients=owned,
        )
        substitutes.extend(result.substitutes)

    return {
        "recipe_detail": recipe_detail,
        "owned_ingredients": owned,
        "missing_ingredients": missing,
        "missing_classification": classification,
        "substitutes": substitutes,
        "cooking_steps": steps,
    }

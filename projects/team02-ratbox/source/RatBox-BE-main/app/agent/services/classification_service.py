from langfuse import observe

from app.agent.prompts.classify_prompt import CLASSIFY_PROMPT
from app.agent.tools.schemas import ClassifyMissingOutput
from app.core.llm import get_llm
from app.data.repositories.recipe_repository import get_recipe_ingredient_names


@observe(name="classify_missing_ingredients", as_type="generation")
def classify(recipe_id: str, available_ingredients: list[str]) -> ClassifyMissingOutput:
    recipe_ingredients = get_recipe_ingredient_names(recipe_id)
    # is_required는 프롬프트에 안 넘긴다 - ingestion(app/ingestion/cleaning.py)이 모든
    # 재료에 무조건 True를 넣고 있어 핵심/부재료 구분 신호가 전혀 없고, 오히려 LLM이
    # "is_required=True니까 필수"라고 기계적으로 판단하게 만드는 잘못된 근거가 된다.
    missing = [
        item["name"] for item in recipe_ingredients if item["name"] not in available_ingredients
    ]

    prompt = CLASSIFY_PROMPT.format(
        available_ingredients=available_ingredients,
        missing_ingredients=missing,
    )
    llm = get_llm().with_structured_output(ClassifyMissingOutput)
    return llm.invoke(prompt)

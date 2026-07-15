from langchain_core.tools import tool

from app.agent.services import substitute_service
from app.agent.tools.schemas import FindSubstitutesInput, FindSubstitutesOutput


@tool("find_substitutes", args_schema=FindSubstitutesInput)
def find_substitutes(
    ingredient_name: str,
    recipe_name: str,
    recipe_context: str | None = None,
    exclude_ingredients: list[str] | None = None,
    owned_ingredients: list[str] | None = None,
) -> FindSubstitutesOutput:
    """부족한 재료의 대체재를 레시피 맥락을 반영해 LLM으로 판단한다."""
    return substitute_service.find(
        ingredient_name,
        recipe_name,
        recipe_context,
        exclude_ingredients,
        owned_ingredients=owned_ingredients,
    )

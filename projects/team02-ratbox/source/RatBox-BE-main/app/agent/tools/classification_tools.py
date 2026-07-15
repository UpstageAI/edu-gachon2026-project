from langchain_core.tools import tool

from app.agent.services import classification_service
from app.agent.tools.schemas import ClassifyMissingInput, ClassifyMissingOutput


@tool("classify_missing_ingredients", args_schema=ClassifyMissingInput)
def classify_missing_ingredients(
    recipe_id: str, available_ingredients: list[str]
) -> ClassifyMissingOutput:
    """레시피의 부족 재료 중 필수/생략가능을 LLM으로 분류한다."""
    return classification_service.classify(recipe_id, available_ingredients)

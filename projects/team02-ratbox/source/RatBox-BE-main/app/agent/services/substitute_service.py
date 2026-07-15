from langfuse import observe

from app.agent.prompts.substitute_prompt import SUBSTITUTE_PROMPT
from app.agent.tools.schemas import FindSubstitutesOutput
from app.core.llm import get_llm


@observe(name="find_substitutes", as_type="generation")
def find(
    ingredient_name: str,
    recipe_name: str,
    recipe_context: str | None,
    exclude_ingredients: list[str] | None = None,
    owned_ingredients: list[str] | None = None,
) -> FindSubstitutesOutput:
    prompt = SUBSTITUTE_PROMPT.format(
        recipe_name=recipe_name,
        recipe_context=recipe_context or "정보 없음",
        ingredient_name=ingredient_name,
        exclude_ingredients=exclude_ingredients or [],
        owned_ingredients=owned_ingredients or [],
    )
    llm = get_llm().with_structured_output(FindSubstitutesOutput)
    return llm.invoke(prompt)

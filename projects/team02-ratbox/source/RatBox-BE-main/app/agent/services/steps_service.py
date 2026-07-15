from langfuse import observe

from app.agent.prompts.steps_prompt import STEPS_PROMPT
from app.agent.tools.schemas import GenerateCookingStepsOutput
from app.core.llm import get_llm


@observe(name="generate_cooking_steps", as_type="generation")
def generate(
    recipe_name: str,
    category: str | None,
    cooking_method: str | None,
    ingredients: list[str],
) -> GenerateCookingStepsOutput:
    prompt = STEPS_PROMPT.format(
        recipe_name=recipe_name,
        category=category or "정보 없음",
        cooking_method=cooking_method or "정보 없음",
        ingredients=ingredients,
    )
    llm = get_llm().with_structured_output(GenerateCookingStepsOutput)
    return llm.invoke(prompt)

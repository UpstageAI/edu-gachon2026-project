from langfuse import observe

from app.agent.prompts.generate_sql_prompt import build_generate_sql_prompt
from app.agent.tools.schemas import ExecuteSQLOutput, GenerateSQLInput, GenerateSQLOutput
from app.core.llm import get_llm
from app.data.sql_executor import execute_readonly_sql, validate_select_only
from app.domain.models import RecipeCandidate


@observe(name="generate_sql", as_type="generation")
def generate_sql(payload: GenerateSQLInput) -> GenerateSQLOutput:
    prompt = build_generate_sql_prompt(payload.ingredients, payload.strategy)
    llm = get_llm().with_structured_output(GenerateSQLOutput)
    return llm.invoke(prompt)


@observe(name="execute_sql", as_type="tool")
def execute_sql(sql: str) -> ExecuteSQLOutput:
    try:
        validate_select_only(sql)
        rows = execute_readonly_sql(sql)
    except ValueError as error:
        return ExecuteSQLOutput(recipes=[], error=str(error))
    except Exception as error:  # noqa: BLE001 - DB/네트워크 오류도 안전 폴백으로 처리
        return ExecuteSQLOutput(recipes=[], error=str(error))

    recipes = [
        RecipeCandidate(id=row["id"], name=row["name"], cooking_time=row.get("cooking_time"))
        for row in rows
    ]
    return ExecuteSQLOutput(recipes=recipes)

from langchain_core.tools import tool

from app.agent.services import recipe_sql_service
from app.agent.tools.schemas import (
    ExecuteSQLInput,
    ExecuteSQLOutput,
    GenerateSQLInput,
    GenerateSQLOutput,
)


@tool("generate_sql", args_schema=GenerateSQLInput)
def generate_sql(ingredients: list[str], strategy: str = "exact") -> GenerateSQLOutput:
    """보유 재료로 레시피를 찾는 SELECT SQL을 생성한다.

    0건 재시도 시 strategy="relaxed"로 조건을 완화한다.
    """
    return recipe_sql_service.generate_sql(
        GenerateSQLInput(ingredients=ingredients, strategy=strategy)
    )


@tool("execute_sql", args_schema=ExecuteSQLInput)
def execute_sql(sql: str) -> ExecuteSQLOutput:
    """generate_sql이 만든 SELECT문을 검증 후 읽기 전용으로 실행한다."""
    return recipe_sql_service.execute_sql(sql)

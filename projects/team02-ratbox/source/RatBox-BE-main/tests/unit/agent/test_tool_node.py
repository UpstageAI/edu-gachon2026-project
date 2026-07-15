from langchain_core.messages import AIMessage

from app.agent.nodes.tool_node import tool_node
from app.agent.state import AgentState
from app.agent.tools.registry import ALL_TOOLS
from app.agent.tools.schemas import ExecuteSQLOutput, GenerateSQLOutput
from app.domain.models import RecipeCandidate


def test_tool_node_extracts_recipes_from_execute_sql(monkeypatch):
    execute_sql_tool = next(t for t in ALL_TOOLS if t.name == "execute_sql")
    monkeypatch.setattr(
        execute_sql_tool,
        "func",
        lambda sql: ExecuteSQLOutput(recipes=[RecipeCandidate(id="1", name="계란밥")]),
    )

    state = AgentState(
        selected_ingredients=["계란"],
        messages=[
            AIMessage(
                content="",
                tool_calls=[{"name": "execute_sql", "args": {"sql": "SELECT 1"}, "id": "call-1"}],
            )
        ],
    )

    result = tool_node(state)

    assert [r.id for r in result["candidate_recipes"]] == ["1"]
    assert "sql_failure_count" not in result
    assert len(result["messages"]) == 1


def test_tool_node_increments_failure_count_on_error(monkeypatch):
    execute_sql_tool = next(t for t in ALL_TOOLS if t.name == "execute_sql")
    monkeypatch.setattr(
        execute_sql_tool,
        "func",
        lambda sql: ExecuteSQLOutput(recipes=[], error="허용되지 않은 테이블"),
    )

    state = AgentState(
        selected_ingredients=["계란"],
        sql_failure_count=1,
        messages=[
            AIMessage(
                content="",
                tool_calls=[{"name": "execute_sql", "args": {"sql": "SELECT 1"}, "id": "call-1"}],
            )
        ],
    )

    result = tool_node(state)

    assert result["sql_failure_count"] == 2


def test_tool_node_does_not_touch_state_for_generate_sql(monkeypatch):
    generate_sql_tool = next(t for t in ALL_TOOLS if t.name == "generate_sql")
    monkeypatch.setattr(
        generate_sql_tool,
        "func",
        lambda ingredients, strategy="exact": GenerateSQLOutput(sql="SELECT 1"),
    )

    state = AgentState(
        selected_ingredients=["계란"],
        messages=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "generate_sql", "args": {"ingredients": ["계란"]}, "id": "call-1"}
                ],
            )
        ],
    )

    result = tool_node(state)

    assert "candidate_recipes" not in result
    assert "sql_failure_count" not in result

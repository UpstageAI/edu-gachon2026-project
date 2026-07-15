from pydantic import ValidationError

from app.schemas.tools import GetNewsArgs, GetStockPriceArgs, LookupGlossaryTermArgs
from app.tools.executor import ToolExecutor
from app.tools.registry import bind_stockpilot_tools, build_stockpilot_tools


def test_tool_schema_exposes_llm_json_schema():
    schema = GetNewsArgs.model_json_schema()

    assert set(schema["properties"]) == {
        "company",
        "days",
        "direction",
        "limit",
    }
    assert schema["required"] == ["company"]
    assert schema["properties"]["direction"]["enum"] == ["down", "up", "neutral"]
    assert "회사명" in schema["properties"]["company"]["description"]


def test_tool_schema_rejects_invalid_or_extra_arguments():
    try:
        GetStockPriceArgs.model_validate(
            {
                "ticker": "삼성전자",
                "period": "2y",
                "unknown": "value",
            }
        )
    except ValidationError as exc:
        errors = exc.errors()
    else:
        raise AssertionError("잘못된 도구 인자가 검증을 통과했습니다.")

    assert {error["type"] for error in errors} == {
        "literal_error",
        "extra_forbidden",
    }


async def test_executor_validates_arguments_before_repository_call(monkeypatch):
    called = False

    async def fake_snapshot(*args, **kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(
        "app.tools.executor.price.get_stock_snapshot",
        fake_snapshot,
    )

    result = await ToolExecutor().execute(
        "get_stock_price",
        {"ticker": "삼성전자", "period": "2y"},
    )

    assert result["success"] is False
    assert result["error_type"] == "ValidationError"
    assert called is False


async def test_structured_tool_uses_pydantic_schema_and_executor():
    class StubExecutor:
        def __init__(self):
            self.call = None

        async def execute(self, tool_name, tool_args, session_id):
            self.call = (tool_name, tool_args, session_id)
            return {"success": True, "data": tool_args}

    executor = StubExecutor()
    tools = build_stockpilot_tools(executor, session_id="session-1")
    tool = next(item for item in tools if item.name == "get_news")

    result = await tool.ainvoke(
        {
            "company": "삼성전자",
            "days": 3,
            "direction": "down",
            "limit": 5,
        }
    )

    assert tool.args_schema is GetNewsArgs
    assert executor.call == (
        "get_news",
        {
            "company": "삼성전자",
            "days": 3,
            "direction": "down",
            "limit": 5,
        },
        "session-1",
    )
    assert result["success"] is True


async def test_structured_tool_exposes_glossary_lookup_schema():
    class StubExecutor:
        def __init__(self):
            self.call = None

        async def execute(self, tool_name, tool_args, session_id):
            self.call = (tool_name, tool_args, session_id)
            return {"success": True, "data": {"query": tool_args["query"], "terms": []}}

    executor = StubExecutor()
    tools = build_stockpilot_tools(executor, session_id="session-1")
    tool = next(item for item in tools if item.name == "lookup_glossary_term")

    result = await tool.ainvoke({"query": "PER", "limit": 2})

    assert tool.args_schema is LookupGlossaryTermArgs
    assert executor.call == (
        "lookup_glossary_term",
        {"query": "PER", "limit": 2},
        "session-1",
    )
    assert result["success"] is True


def test_bind_stockpilot_tools_passes_json_schemas_to_llm():
    class StubLLM:
        def __init__(self):
            self.tools = None

        def bind_tools(self, tools):
            self.tools = tools
            return "tool-enabled-llm"

    llm = StubLLM()

    result = bind_stockpilot_tools(llm)

    assert result == "tool-enabled-llm"
    assert {tool.name for tool in llm.tools} == {
        "get_stock_price",
        "get_news",
        "get_disclosure",
        "find_positive_news_stocks",
        "add_watchlist",
        "lookup_glossary_term",
    }
    news_tool = next(tool for tool in llm.tools if tool.name == "get_news")
    assert news_tool.args["direction"]["enum"] == ["down", "up", "neutral"]

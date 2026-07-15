"""Full ReAct agent routing safeguards."""

from app.agents import full_react_agent


def _fake_screener_result() -> dict:
    return {
        "success": True,
        "data": {
            "stocks": [
                {
                    "ticker": "심텍",
                    "change_pct": 12.6,
                    "top_news": "반도체 부품주 강세",
                }
            ]
        },
    }


async def test_full_react_generic_recommendation_uses_screener(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_execute(tool_name: str, args: dict):
        calls.append((tool_name, args))
        return _fake_screener_result()

    def fail_if_graph_is_used(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("generic recommendation should not enter LLM graph")

    monkeypatch.setattr(full_react_agent._EXECUTOR, "execute", fake_execute)
    monkeypatch.setattr(full_react_agent, "_get_full_react_graph", fail_if_graph_is_used)

    result = await full_react_agent.run_full_react_agent(
        message="추천해줘",
        session_id="full-react-generic-recommendation",
        model_id="solar",
    )

    assert calls == [("find_positive_news_stocks", {})]
    assert result.tool_used == "find_positive_news_stocks"
    assert "심텍" in result.answer
    assert "매수·매도 추천" in result.answer


async def test_full_react_generic_recommendation_streams_screener(monkeypatch):
    calls: list[tuple[str, dict]] = []

    async def fake_execute(tool_name: str, args: dict):
        calls.append((tool_name, args))
        return _fake_screener_result()

    def fail_if_graph_is_used(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("generic recommendation should not enter LLM graph")

    monkeypatch.setattr(full_react_agent._EXECUTOR, "execute", fake_execute)
    monkeypatch.setattr(full_react_agent, "_get_full_react_graph", fail_if_graph_is_used)

    events = [
        event
        async for event in full_react_agent.stream_full_react_agent(
            message="최근 급등 종목 알려줘",
            session_id="full-react-generic-recommendation-stream",
            model_id="solar",
        )
    ]

    assert calls == [("find_positive_news_stocks", {})]
    assert [event["type"] for event in events] == ["thinking", "tool", "response"]
    assert events[1]["tool_name"] == "find_positive_news_stocks"
    assert events[2]["tool_used"] == "find_positive_news_stocks"
    assert "심텍" in events[2]["content"]

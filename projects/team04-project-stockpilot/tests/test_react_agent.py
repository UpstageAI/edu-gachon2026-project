import json

import pytest
from langchain_core.messages import AIMessage

import app.agents.react_agent as react_agent
from app.agents.react_agent import run_react_agent, stream_react_agent
from app.core.llm import LLMFallbackResult
from tests.fixtures.tool_responses import directional_news_item, stock_snapshot


def _llm_result(content: dict) -> LLMFallbackResult:
    return LLMFallbackResult(
        message=AIMessage(content=json.dumps(content, ensure_ascii=False)),
        model_id="solar",
        model_name="solar-pro3-260323",
        attempted_models=["solar"],
        fallback_used=False,
    )


@pytest.fixture
def react_mocks(monkeypatch):
    calls = []
    plans = iter(
        [
            {
                "thought": "먼저 주가 방향과 기준 시점을 확인한다.",
                "action": "get_stock_price",
                "args": {"ticker": "삼성전자", "period": "3m"},
            },
            {
                "thought": "하락 원인 질문이므로 관련 뉴스를 확인한다.",
                "action": "get_news",
                "args": {"company": "삼성전자", "direction": "down", "days": 7, "limit": 5},
            },
            {
                "thought": "필요한 근거가 모였으므로 답변한다.",
                "action": "final",
                "args": {},
                "final": "삼성전자는 전 거래일 대비 상승 중이며, 관련 뉴스 근거를 함께 확인했습니다.",
            },
        ]
    )

    async def fake_ainvoke_with_fallback(*args, **kwargs):
        return _llm_result(next(plans))

    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        calls.append((tool_name, tool_args or {}, session_id))
        if tool_name == "get_stock_price":
            return {"success": True, "data": stock_snapshot()}
        if tool_name == "get_news":
            item = directional_news_item()
            return {
                "success": True,
                "data": {
                    "company": tool_args.get("company", "삼성전자") if tool_args else "삼성전자",
                    "direction": tool_args.get("direction", "down") if tool_args else "down",
                    "news": [
                        {
                            **item,
                            "published_at": item["published_at"].isoformat(),
                            "source": item["source_domain"],
                            "url": item["original_link"],
                            "sentiment": "부정",
                            "reason": "실적 우려",
                        }
                    ],
                },
            }
        return {"success": False, "error": f"unexpected tool: {tool_name}"}

    monkeypatch.setattr(react_agent, "ainvoke_with_fallback", fake_ainvoke_with_fallback)
    monkeypatch.setattr(react_agent._EXECUTOR, "execute", fake_execute)
    return calls


async def test_react_agent_runs_thought_action_observation_loop(react_mocks):
    result = await run_react_agent(
        message="삼성전자 왜 떨어졌어?",
        session_id="react-unit-1",
    )

    assert [call[0] for call in react_mocks] == ["get_stock_price", "get_news"]
    assert result.tool_used == "get_stock_price,get_news"
    assert result.used_model == "solar-pro3-260323"
    assert "삼성전자" in result.answer
    assert len(result.steps) == 2


async def test_react_agent_streams_tool_and_response_events(react_mocks):
    events = [
        event
        async for event in stream_react_agent(
            message="삼성전자 왜 떨어졌어?",
            session_id="react-unit-2",
        )
    ]

    event_types = [event["type"] for event in events]
    assert "thinking" in event_types
    assert "tool" in event_types
    assert event_types[-1] == "response"
    assert [call[0] for call in react_mocks] == ["get_stock_price", "get_news"]

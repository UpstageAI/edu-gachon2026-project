"""채팅 API E2E + 실패 케이스 테스트 (네트워크·API 키 불필요)."""
import json
import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk
import app.graph.nodes as nodes
from app.main import app
from tests.fixtures.tool_responses import disclosure_item, directional_news_item, stock_snapshot
client = TestClient(app)
async def _fake_execute(tool_name, tool_args=None, session_id="default"):
    if tool_name == "get_stock_price":
        return {"success": True, "data": stock_snapshot()}
    if tool_name == "get_news":
        return {"success": True, "data": {"news": [directional_news_item()]}}
    if tool_name == "get_disclosure":
        item = disclosure_item()
        return {
            "success": True,
            "data": {
                "ticker": tool_args.get("ticker") if tool_args else "005930",
                "disclosures": [
                    {
                        **item,
                        "title": item["report_name"],
                        "date": item["received_date"],
                        "url": item["source_url"],
                    }
                ],
            },
        }
    if tool_name == "find_positive_news_stocks":
        return {
            "success": True,
            "data": {
                "stocks": [
                    {
                        "ticker": "035720",
                        "name": "카카오",
                        "change_pct": 4.2,
                        "reason": "최근 상승률과 긍정 뉴스가 함께 확인되었습니다.",
                        "news": [],
                    }
                ]
            },
        }
    return {"success": False, "error": f"알 수 없는 도구: {tool_name}"}
def _parse_sse(text):
    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]
@pytest.fixture
def mock_tools(monkeypatch):
    monkeypatch.setattr(nodes._executor, "execute", _fake_execute)
def test_chat_e2e_returns_stock_answer(mock_tools):
    r = client.post(
        "/api/v1/chat/",
        json={"message": "삼성전자 요즘 어때?", "session_id": "e2e-1"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["tool_used"] == "get_stock_price,get_news,get_disclosure"
    assert "삼성전자" in body["message"]
    assert "투자 자문이 아닌" in body["message"]
def test_chat_stream_event_sequence(mock_tools):
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 어때?", "session_id": "e2e-2"},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(r.text)
    types = [e["type"] for e in events]
    assert "thinking" in types
    assert "tool" in types
    assert types[-1] == "done"
    assert any(t in ("token", "response") for t in types)


def test_chat_stream_blocks_out_of_scope_without_tool():
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "배고프다", "session_id": "out-of-scope-1"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    types = [event["type"] for event in events]
    assert "tool" not in types
    response = next(event for event in events if event["type"] == "response")
    assert "주식 리서치 전용" in response["content"]
    assert events[-1]["type"] == "done"


def test_chat_stream_disclosure_request_uses_disclosure_only(monkeypatch):
    calls = []

    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        calls.append(tool_name)
        if tool_name == "get_disclosure":
            item = disclosure_item()
            return {
                "success": True,
                "data": {
                    "ticker": "005930",
                    "disclosures": [
                        {
                            **item,
                            "title": item["report_name"],
                            "date": item["received_date"],
                            "url": item["source_url"],
                        }
                    ],
                },
            }
        return {"success": False, "error": f"unexpected tool: {tool_name}"}

    monkeypatch.setattr(nodes._executor, "execute", fake_execute)

    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 공시 알려줘", "session_id": "disclosure-1"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert calls == ["get_disclosure"]
    tool_event = next(event for event in events if event["type"] == "tool")
    assert tool_event["tool_result"]["price"] is None
    assert tool_event["tool_result"]["disclosures"][0]["title"] == "사업보고서 (2025.12)"
    response = next(event for event in events if event["type"] == "response")
    assert "삼성전자 최근 공시" in response["content"]
    assert "원인 분석" not in response["content"]
    assert events[-1]["type"] == "done"


def test_chat_stream_blocks_buy_sell_advice_request():
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 매수할까?", "session_id": "guardrail-buy-1"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert events[0]["type"] == "error"
    assert "매수·매도 여부는 추천할 수 없습니다" in events[0]["error"]
    assert all(event["type"] != "tool" for event in events)
    assert events[-1]["type"] == "done"


def test_blocked_recommendation_does_not_create_followup_ticker_context():
    session_id = "guardrail-no-context-after-block"
    blocked = client.post(
        "/api/v1/chat/stream",
        json={"message": "무조건 삼성전자 매수 추천해줘", "session_id": session_id},
    )
    assert blocked.status_code == 200
    blocked_events = _parse_sse(blocked.text)
    assert blocked_events[0]["type"] == "error"
    assert all(event["type"] != "tool" for event in blocked_events)

    followup = client.post(
        "/api/v1/chat/stream",
        json={"message": "왜 올랐어?", "session_id": session_id},
    )
    assert followup.status_code == 200
    followup_events = _parse_sse(followup.text)
    assert all(event["type"] != "tool" for event in followup_events)
    response = next(event for event in followup_events if event["type"] == "response")
    assert "어떤 종목" in response["content"]


def test_blocked_recommendation_preserves_existing_valid_ticker_context(mock_tools):
    session_id = "guardrail-preserve-context-after-block"
    initial = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 어때", "session_id": session_id},
    )
    assert initial.status_code == 200
    assert any(event["type"] == "tool" for event in _parse_sse(initial.text))

    blocked = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 매수 추천해줘", "session_id": session_id},
    )
    assert blocked.status_code == 200
    blocked_events = _parse_sse(blocked.text)
    assert blocked_events[0]["type"] == "error"
    assert all(event["type"] != "tool" for event in blocked_events)

    followup = client.post(
        "/api/v1/chat/stream",
        json={"message": "왜 올랐어?", "session_id": session_id},
    )
    assert followup.status_code == 200
    followup_events = _parse_sse(followup.text)
    tool_event = next(event for event in followup_events if event["type"] == "tool")
    assert tool_event["tool_name"] == "get_stock_price,get_news,get_disclosure"
    assert followup_events[-1]["type"] == "done"


def test_generic_recommendation_uses_screener_not_previous_ticker(mock_tools):
    session_id = "generic-recommend-screener-after-stock"
    initial = client.post(
        "/api/v1/chat/stream",
        json={"message": "카카오 요즘 어때", "session_id": session_id},
    )
    assert initial.status_code == 200
    assert any(event["type"] == "tool" for event in _parse_sse(initial.text))

    recommend = client.post(
        "/api/v1/chat/stream",
        json={"message": "추천해줘", "session_id": session_id},
    )
    assert recommend.status_code == 200
    recommend_events = _parse_sse(recommend.text)
    tool_event = next(event for event in recommend_events if event["type"] == "tool")
    assert tool_event["tool_name"] == "find_positive_news_stocks"

    followup = client.post(
        "/api/v1/chat/stream",
        json={"message": "왜 올랐어?", "session_id": session_id},
    )
    assert followup.status_code == 200
    followup_events = _parse_sse(followup.text)
    assert all(event["type"] != "tool" for event in followup_events)
    response = next(event for event in followup_events if event["type"] == "response")
    assert "어떤 종목" in response["content"]
    assert followup_events[-1]["type"] == "done"


def test_chat_stream_suppresses_raw_tokens_when_direction_notice_exists(monkeypatch):
    notice = "아닙니다. 현재 삼성전자는 상승 중입니다. 아래는 최근 상승과 관련 있어 보이는 주요 이유입니다."

    class _DirectionNoticeGraph:
        async def astream(self, *args, **kwargs):
            yield (
                "updates",
                {
                    "tool": {
                        "tool_name": "get_stock_price,get_news,get_disclosure",
                        "direction_notice": notice,
                        "tool_result": {
                            "price": {"name": "삼성전자", "change_pct": 1.2},
                            "news": [],
                            "disclosures": [],
                            "direction_notice": notice,
                        },
                    }
                },
            )
            yield (
                "messages",
                (
                    AIMessageChunk(content="삼성전자 ▼ 0.20% 하락"),
                    {"langgraph_node": "response"},
                ),
            )
            yield (
                "updates",
                {
                    "response": {
                        "messages": [
                            AIMessage(content=f"{notice}\n\n삼성전자 ▲ 1.20% 상승")
                        ],
                        "used_model": "solar",
                    }
                },
            )

    monkeypatch.setattr(
        "app.api.routes.chat.get_stockpilot_graph",
        lambda: _DirectionNoticeGraph(),
    )

    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자 왜 떨어져?", "session_id": "direction-notice-stream"},
    )

    assert r.status_code == 200
    events = _parse_sse(r.text)
    assert all(event["type"] != "token" for event in events)
    response = next(event for event in events if event["type"] == "response")
    assert response["content"].startswith(notice)
    assert "삼성전자 ▼ 0.20% 하락" not in response["content"]


def test_chat_api_blocks_buy_sell_advice_request():
    r = client.post(
        "/api/v1/chat/",
        json={"message": "삼성전자 살까?", "session_id": "guardrail-buy-2"},
    )

    assert r.status_code == 400
    assert "매수·매도 여부는 추천할 수 없습니다" in r.json()["detail"]


def test_chat_stream_handles_graph_failure(monkeypatch):
    async def _boom_astream(*args, **kwargs):
        raise RuntimeError("그래프 실행 강제 실패")
        yield
    class _BoomGraph:
        def astream(self, *args, **kwargs):
            return _boom_astream()
    monkeypatch.setattr(
        "app.api.routes.chat.get_stockpilot_graph",
        lambda: _BoomGraph(),
    )
    r = client.post(
        "/api/v1/chat/stream",
        json={"message": "삼성전자", "session_id": "fail-1"},
    )
    assert r.status_code == 200
    types = [e["type"] for e in _parse_sse(r.text)]
    assert "error" in types
    assert types[-1] == "done"
async def test_response_node_falls_back_when_llm_unavailable(monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("Solar 사용 불가")
    monkeypatch.setattr(nodes, "ainvoke_with_fallback", _raise)
    from app.graph.state import create_initial_state
    state = create_initial_state("s")
    state["ticker"] = "삼성전자"
    state["price_data"] = {**stock_snapshot(), "change_pct": -2.3}
    result = await nodes.response_node(state)
    content = result["messages"][-1].content
    assert "삼성전자" in content
    assert "원인 분석" in content

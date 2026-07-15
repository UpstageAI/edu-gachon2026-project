"""에이전트/그래프 단위 테스트 (네트워크·API 키 불필요)."""
import pytest
from langchain_core.messages import HumanMessage
from app.graph.edges import route_by_intent
from app.graph.nodes import (
    OUT_OF_SCOPE_MESSAGE,
    _SESSION_PRICE_SNAPSHOT,
    _format_change,
    response_node,
    router_node,
    tool_node,
)
from app.graph.state import create_initial_state
from app.tools.executor import _normalize_news_item
from tests.fixtures.tool_responses import directional_news_item, stock_snapshot


@pytest.fixture(autouse=True)
def disable_llm_router_by_default(monkeypatch):
    """Router tests should not hit real Solar unless a test explicitly opts in."""

    async def fake_llm_route(query: str, **kwargs):
        return None

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)


def test_create_initial_state():
    state = create_initial_state("sess-1", "user-1")
    assert state["session_id"] == "sess-1"
    assert state["user_id"] == "user-1"
    assert state["messages"] == []
    assert state["intent"] is None
def test_route_by_intent():
    assert route_by_intent({"intent": "rag"}) == "rag"
    assert route_by_intent({"intent": "tool"}) == "tool"
    assert route_by_intent({"intent": "chat"}) == "response"
    assert route_by_intent({}) == "response"
def test_format_change():
    assert _format_change(1.5) == ("▲", "상승")
    assert _format_change(-2.3) == ("▼", "하락")
    assert _format_change(0.0) == ("―", "보합")
    assert _format_change(None) == ("", "")
async def test_router_node_rag():
    state = create_initial_state("s")
    state["messages"] = [HumanMessage(content="PER이 뭐야?")]
    result = await router_node(state)
    assert result["intent"] == "rag"


async def test_router_node_listing_definition_is_rag():
    state = create_initial_state("listing-term")
    state["messages"] = [HumanMessage(content="상장이 뭐야")]

    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["ticker"] is None


async def test_router_node_buy_sell_educational_definition_is_rag():
    for question in ("매수 뜻이 뭐야?", "매도 뜻이 뭐야?", "손절이 뭐야?"):
        state = create_initial_state(f"definition-{question}")
        state["messages"] = [HumanMessage(content=question)]

        result = await router_node(state)

        assert result["intent"] == "rag"
        assert result["tool_mode"] is None


async def test_router_node_tool():
    state = create_initial_state("s")
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]
    result = await router_node(state)
    assert result["intent"] == "tool"
    assert result["ticker"] == "삼성전자"


async def test_router_node_positive_news_screener_variants(monkeypatch):
    routed_queries = []

    async def fake_llm_route(query: str, **kwargs):
        routed_queries.append(query)
        return {
            "intent": "tool",
            "screen": True,
            "tool_mode": "market",
            "ticker": None,
            "answer_mode": "market_overview",
        }

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

    for question in (
        "최근 급등한 종목 알려줘",
        "호재 있는 종목 알려줘",
        "좋은 뉴스 나온 종목 알려줘",
    ):
        state = create_initial_state(f"screener-{question}")
        state["messages"] = [HumanMessage(content=question)]

        result = await router_node(state)

        assert result["intent"] == "tool"
        assert result["screen"] is True
        assert result["ticker"] is None

    assert routed_queries == [
        "최근 급등한 종목 알려줘",
        "호재 있는 종목 알려줘",
        "좋은 뉴스 나온 종목 알려줘",
    ]


async def test_router_node_screener_rule_fallback_when_llm_router_fails(monkeypatch):
    async def fake_llm_route(query: str, **kwargs):
        return None

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

    state = create_initial_state("screener-rule-fallback")
    state["messages"] = [HumanMessage(content="호재 있는 종목 알려줘")]

    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["screen"] is True
    assert result["ticker"] is None


async def test_router_node_positive_news_definition_is_rag_not_screener():
    state = create_initial_state("positive-news-definition")
    state["messages"] = [HumanMessage(content="호재가 뭐야?")]

    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["screen"] is False


async def test_router_node_disclosure_tool_mode():
    state = create_initial_state("disclosure-router")
    state["messages"] = [HumanMessage(content="삼성전자 공시 알려줘")]

    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "disclosure"


async def test_router_node_llm_routes_company_disclosure_risk(monkeypatch):
    async def fake_llm_route(query: str, **kwargs):
        assert query == "삼성전자 공시 리스크"
        assert kwargs["matched_stock"] == "삼성전자"
        return {
            "intent": "tool",
            "screen": False,
            "tool_mode": "disclosure",
            "ticker": "삼성전자",
            "answer_mode": "disclosure_risk",
        }

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

    state = create_initial_state("disclosure-risk-router")
    state["messages"] = [HumanMessage(content="삼성전자 공시 리스크")]

    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "disclosure"
    assert result["response_mode"] == "disclosure_risk"


async def test_router_node_ignores_llm_screener_when_stock_is_explicit(monkeypatch):
    async def fake_llm_route(query: str, **kwargs):
        assert query == "삼성전자 어때"
        assert kwargs["matched_stock"] == "삼성전자"
        return {
            "intent": "tool",
            "screen": True,
            "tool_mode": "market",
            "ticker": "SK하이닉스",
            "answer_mode": "market_overview",
        }

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

    state = create_initial_state("explicit-stock-over-screener")
    state["messages"] = [HumanMessage(content="삼성전자 어때")]

    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["screen"] is False
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "market"


async def test_router_node_ignores_llm_chat_when_stock_is_explicit(monkeypatch):
    async def fake_llm_route(query: str, **kwargs):
        assert query == "삼성전자 어때"
        assert kwargs["matched_stock"] == "삼성전자"
        return {
            "intent": "chat",
            "screen": False,
            "tool_mode": None,
            "ticker": None,
            "answer_mode": None,
        }

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

    state = create_initial_state("explicit-stock-over-chat")
    state["messages"] = [HumanMessage(content="삼성전자 어때")]

    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["screen"] is False
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "market"


async def test_router_node_disclosure_risk_concept_is_rag():
    state = create_initial_state("disclosure-risk-concept")
    state["messages"] = [HumanMessage(content="공시 리스크 뭐야")]

    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["screen"] is False
    assert result["ticker"] is None
    assert result.get("tool_mode") is None


async def test_router_node_followup_disclosure_uses_previous_ticker():
    state = create_initial_state("disclosure-followup")
    state["messages"] = [HumanMessage(content="삼성전자 어때?")]
    await router_node(state)

    state = create_initial_state("disclosure-followup")
    state["messages"] = [HumanMessage(content="공시 알려줘")]
    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "disclosure"


async def test_router_node_followup_disclosure_definition_is_rag():
    state = create_initial_state("disclosure-definition-followup")
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]
    await router_node(state)

    state = create_initial_state("disclosure-definition-followup")
    state["messages"] = [HumanMessage(content="공시가 뭔데?")]
    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["screen"] is False
    assert result["ticker"] is None
    assert result.get("tool_mode") is None


async def test_router_node_disclosure_word_meaning_is_rag():
    state = create_initial_state("disclosure-word-meaning")
    state["messages"] = [HumanMessage(content="공시라는 단어가 뭔 의미냐고")]

    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["screen"] is False
    assert result["ticker"] is None
    assert result.get("tool_mode") is None


async def test_router_node_followup_cause_reuses_previous_ticker():
    state = create_initial_state("cause-followup")
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]
    await router_node(state)

    state = create_initial_state("cause-followup")
    state["messages"] = [HumanMessage(content="원인이 뭐야?")]
    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] == "market"
    assert result["is_followup"] is True


async def test_router_node_kakao_status_then_why_up_reuses_kakao_context():
    state = create_initial_state("kakao-cause-followup")
    state["messages"] = [HumanMessage(content="카카오 어때")]
    await router_node(state)

    state = create_initial_state("kakao-cause-followup")
    state["messages"] = [HumanMessage(content="왜 올랐어?")]
    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["ticker"] == "카카오"
    assert result["tool_mode"] == "market"
    assert result["is_followup"] is True


async def test_router_node_generic_recommendation_uses_screener_even_after_previous_ticker():
    state = create_initial_state("generic-recommend-followup")
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]
    await router_node(state)

    state = create_initial_state("generic-recommend-followup")
    state["messages"] = [HumanMessage(content="추천해줘")]
    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["screen"] is True
    assert result["ticker"] is None
    assert result["tool_mode"] == "market"
    assert result["response_mode"] == "market_overview"
    assert result["is_followup"] is False

    state = create_initial_state("generic-recommend-followup")
    state["messages"] = [HumanMessage(content="왜 올랐어?")]
    result = await router_node(state)

    assert result["intent"] == "chat"
    assert result["response_mode"] == "missing_ticker"


async def test_router_node_generic_recommendation_without_context_uses_screener():
    state = create_initial_state("generic-recommend-screener")
    state["messages"] = [HumanMessage(content="추천해줘")]
    result = await router_node(state)

    assert result["intent"] == "tool"
    assert result["screen"] is True
    assert result["ticker"] is None
    assert result["tool_mode"] == "market"
    assert result["response_mode"] == "market_overview"
    assert result["is_followup"] is False


async def test_router_node_missing_ticker_followup_asks_for_ticker():
    state = create_initial_state("missing-ticker-followup")
    state["messages"] = [HumanMessage(content="왜 올랐어?")]
    result = await router_node(state)

    assert result["intent"] == "chat"
    assert result["ticker"] is None
    assert result["response_mode"] == "missing_ticker"


async def test_router_node_business_report_risk_uses_rag_not_disclosure():
    state = create_initial_state("report-risk")
    state["messages"] = [HumanMessage(content="삼성전자 사업보고서에서 리스크 요인 알려줘")]

    result = await router_node(state)

    assert result["intent"] == "rag"
    assert result["ticker"] == "삼성전자"
    assert result["tool_mode"] is None


async def test_router_node_blocks_out_of_scope_chat():
    state = create_initial_state("s")
    state["messages"] = [HumanMessage(content="배고프다")]

    result = await router_node(state)

    assert result["intent"] == "chat"
    assert result["ticker"] is None


async def test_response_node_returns_domain_guard_message():
    state = create_initial_state("s")
    state["intent"] = "chat"
    state["messages"] = [HumanMessage(content="배고프다")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert content == OUT_OF_SCOPE_MESSAGE
    assert "주식 리서치 전용" in content


async def test_response_node_formats_disclosures_without_price_analysis():
    state = create_initial_state("s")
    state["intent"] = "tool"
    state["tool_mode"] = "disclosure"
    state["ticker"] = "삼성전자"
    state["disclosures"] = [
        {
            "corp_name": "삼성전자",
            "report_name": "사업보고서 (2025.12)",
            "received_date": "20260317",
            "source_url": "https://dart.fss.or.kr/example",
        }
    ]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert "삼성전자 최근 공시" in content
    assert "사업보고서" in content
    assert "원인 분석" not in content
    assert "현재가" not in content


async def test_response_node_generates_disclosure_risk_with_llm(monkeypatch):
    prompts = []

    class FakeResult:
        message = type(
            "Message",
            (),
            {
                "content": (
                    "삼성전자 최근 공시 중 자기주식 처분 관련 공시는 규모와 목적을 "
                    "추가 확인할 필요가 있는 리스크 후보입니다."
                )
            },
        )()
        model_name = "solar-pro3-260323"
        model_id = "solar"
        fallback_used = False

    async def fake_ainvoke(messages, **kwargs):
        prompts.append(messages[0].content)
        return FakeResult()

    monkeypatch.setattr("app.graph.nodes.ainvoke_with_fallback", fake_ainvoke)

    state = create_initial_state("disclosure-risk-response")
    state["intent"] = "tool"
    state["tool_mode"] = "disclosure"
    state["response_mode"] = "disclosure_risk"
    state["ticker"] = "삼성전자"
    state["messages"] = [HumanMessage(content="삼성전자 공시 리스크")]
    state["disclosures"] = [
        {
            "corp_name": "삼성전자",
            "report_name": "주요사항보고서(자기주식처분결정)",
            "received_date": "20260713",
            "source_url": "https://dart.fss.or.kr/example",
        }
    ]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert "자기주식 처분" in content
    assert "리스크 후보" in content
    assert "### 삼성전자 최근 공시" not in content
    assert "공시 리스크" in prompts[0]
    assert result["used_model"] == "solar-pro3-260323"


async def test_response_node_uses_external_glossary_fallback(monkeypatch):
    async def fake_search_or_research_terms(query: str, *, limit: int):
        assert query == "상장이 뭐야"
        assert limit == 1
        return [
            {
                "term": "상장",
                "definition": "기업의 주식이 증권시장에 등록되어 거래될 수 있게 되는 것입니다.",
                "aliases": ["Listing"],
                "example": "코스닥에 상장하면 일반 투자자가 주식을 사고팔 수 있습니다.",
                "source_url": "https://example.com/listing",
            }
        ]

    monkeypatch.setattr(
        "app.graph.nodes.search_or_research_terms",
        fake_search_or_research_terms,
    )
    state = create_initial_state("listing-response")
    state["intent"] = "rag"
    state["messages"] = [HumanMessage(content="상장이 뭐야")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert "**상장**" in content
    assert "증권시장" in content
    assert "원인 분석" not in content
    assert "주식 리서치 전용 도우미" not in content


async def test_response_node_format():
    state = create_initial_state("s")
    state["ticker"] = "삼성전자"
    state["price_data"] = {
        **stock_snapshot(),
        "change_pct": -2.3,
        "current_price": 71000,
    }
    state["news_items"] = [_normalize_news_item(directional_news_item(), "down")]
    result = await response_node(state)
    content = result["messages"][-1].content
    assert "삼성전자" in content
    assert "▼" in content and "하락" in content
    assert "원인 분석" in content
    assert "투자 자문이 아닌" in content


async def test_response_node_overview_keeps_header_but_avoids_reason_analysis():
    state = create_initial_state("overview")
    state["intent"] = "tool"
    state["ticker"] = "삼성전자"
    state["price_data"] = {
        **stock_snapshot(),
        "snapshot_at": "2026-07-09T01:30:00+00:00",
    }
    state["news_items"] = [_normalize_news_item(directional_news_item(), "down")]
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert result["used_model"] == "template-market-overview"
    assert "삼성전자" in content
    assert "일봉 기준" in content
    assert "기준일" in content
    assert "조회시각" in content
    assert "전 거래일 대비" in content
    assert "왜 올랐어?" in content
    assert "왜 떨어졌어?" not in content
    assert "원인 분석" not in content


async def test_response_node_overview_is_default_for_stock_status_question():
    state = create_initial_state("overview-any-wording")
    state["intent"] = "tool"
    state["ticker"] = "한화오션"
    state["price_data"] = {
        **stock_snapshot(),
        "name": "한화오션",
        "change_pct": -2.54,
        "current_price": 76800,
        "snapshot_at": "2026-07-14T07:25:00+00:00",
    }
    state["messages"] = [HumanMessage(content="한화오션 어떠냐")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert result["used_model"] == "template-market-overview"
    assert "한화오션" in content
    assert "전 거래일 대비" in content
    assert "왜 떨어졌어?" in content
    assert "원인 분석" not in content


async def test_response_node_market_overview_mode_overrides_recommendation_wording():
    state = create_initial_state("overview-recommendation")
    state["intent"] = "tool"
    state["ticker"] = "삼성전자"
    state["response_mode"] = "market_overview"
    state["price_data"] = {
        **stock_snapshot(),
        "change_pct": 1.77,
        "snapshot_at": "2026-07-14T06:30:00+00:00",
    }
    state["messages"] = [HumanMessage(content="추천해줘")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert result["used_model"] == "template-market-overview"
    assert "전 거래일 대비" in content
    assert "왜 올랐어?" in content
    assert "원인 분석" not in content


async def test_response_node_overview_separates_trend_from_daily_move():
    rows = []
    closes = [
        100000,
        98000,
        96000,
        94000,
        92000,
        90000,
        88000,
        86000,
        84000,
        82000,
        80000,
        80500,
    ]
    for idx, close in enumerate(closes, start=1):
        rows.append(
            {
                "date": f"2026-07-{idx:02d}",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000,
                "change_pct": 0.0,
            }
        )

    state = create_initial_state("overview-mixed")
    state["intent"] = "tool"
    state["ticker"] = "삼성전자"
    state["price_data"] = {
        **stock_snapshot(),
        "ohlcv": rows,
        "current_price": 80500,
        "change_pct": 0.63,
        "snapshot_at": "2026-07-12T01:30:00+00:00",
    }
    state["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert "최근 12거래일 흐름은 하락 추세지만" in content
    assert "기준일 하루 움직임은 전 거래일 대비 상승" in content
    assert "왜 올랐어?" in content


async def test_tool_node_reuses_session_price_for_followup(monkeypatch):
    _SESSION_PRICE_SNAPSHOT.clear()
    calls = {"price": 0}

    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        if tool_name == "get_stock_price":
            calls["price"] += 1
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "name": "삼성전자",
                    "current_price": 263500,
                    "change_pct": 3.54,
                    "snapshot_at": "2026-07-14T06:07:00+00:00",
                },
            }
        if tool_name == "get_news":
            assert tool_args["direction"] == "up"
            return {"success": True, "data": {"news": [directional_news_item()]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    first = create_initial_state("price-pin")
    first["ticker"] = "삼성전자"
    first["messages"] = [HumanMessage(content="삼성전자 요즘 어때?")]
    first_result = await tool_node(first)

    followup = create_initial_state("price-pin")
    followup["ticker"] = "삼성전자"
    followup["is_followup"] = True
    followup["messages"] = [HumanMessage(content="왜 내렸어?")]
    second_result = await tool_node(followup)

    assert calls["price"] == 1
    assert first_result["price_data"]["current_price"] == 263500
    assert second_result["price_data"]["current_price"] == 263500
    assert second_result["price_data"]["change_pct"] == 3.54
    assert second_result["panel_update"] is False
    assert second_result["tool_result"]["panel_update"] is False
    assert "현재 삼성전자는 상승 중입니다" in second_result["direction_notice"]
    _SESSION_PRICE_SNAPSHOT.clear()


async def test_tool_node_corrects_requested_down_when_actual_price_is_up(monkeypatch):
    calls = []

    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        calls.append((tool_name, tool_args or {}))
        if tool_name == "get_stock_price":
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "name": "삼성전자",
                    "change_pct": 1.77,
                },
            }
        if tool_name == "get_news":
            assert tool_args["direction"] == "up"
            item = directional_news_item()
            item.update(
                {
                    "direction": "up",
                    "direction_keywords": ["상승", "호재"],
                    "has_direction_evidence": True,
                }
            )
            return {"success": True, "data": {"news": [item]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    state = create_initial_state("direction-correction")
    state["ticker"] = "삼성전자"
    state["messages"] = [HumanMessage(content="왜 떨어졌어?")]

    result = await tool_node(state)

    news_call = next(args for name, args in calls if name == "get_news")
    assert news_call["direction"] == "up"
    assert "현재 삼성전자는 상승 중입니다" in result["direction_notice"]
    assert result["tool_result"]["direction_notice"] == result["direction_notice"]


async def test_tool_node_uses_resolved_company_name_for_news(monkeypatch):
    calls = []

    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        calls.append((tool_name, tool_args or {}))
        if tool_name == "get_stock_price":
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "ticker": "064350",
                    "name": "현대로템",
                    "change_pct": -2.71,
                },
            }
        if tool_name == "get_news":
            return {"success": True, "data": {"news": [directional_news_item()]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    state = create_initial_state("resolved-company-name")
    state["ticker"] = "064350"
    state["messages"] = [HumanMessage(content="현대로템 왜 떨어져?")]

    await tool_node(state)

    news_call = next(args for name, args in calls if name == "get_news")
    disclosure_call = next(args for name, args in calls if name == "get_disclosure")
    assert news_call["company"] == "현대로템"
    assert disclosure_call["ticker"] == "064350"


async def test_tool_node_corrects_requested_up_when_actual_price_is_down(monkeypatch):
    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        if tool_name == "get_stock_price":
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "name": "삼성전자",
                    "change_pct": -0.69,
                },
            }
        if tool_name == "get_news":
            assert tool_args["direction"] == "down"
            return {"success": True, "data": {"news": [directional_news_item()]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    state = create_initial_state("direction-correction-up")
    state["ticker"] = "삼성전자"
    state["messages"] = [HumanMessage(content="왜 올랐어?")]

    result = await tool_node(state)

    assert "현재 삼성전자는 하락 중입니다" in result["direction_notice"]


async def test_tool_node_uses_direction_after_why_for_conflicting_user_wording(monkeypatch):
    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        if tool_name == "get_stock_price":
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "name": "삼성전자",
                    "change_pct": -0.69,
                },
            }
        if tool_name == "get_news":
            assert tool_args["direction"] == "down"
            return {"success": True, "data": {"news": [directional_news_item()]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    state = create_initial_state("direction-conflicting-wording")
    state["ticker"] = "삼성전자"
    state["messages"] = [HumanMessage(content="내려가고 있는데 왜 올라가?")]

    result = await tool_node(state)

    assert "현재 삼성전자는 하락 중입니다" in result["direction_notice"]


async def test_tool_node_corrects_falling_premise_when_actual_price_is_up(monkeypatch):
    async def fake_execute(tool_name, tool_args=None, session_id="default"):
        if tool_name == "get_stock_price":
            return {
                "success": True,
                "data": {
                    **stock_snapshot(),
                    "name": "삼성전자",
                    "change_pct": 1.18,
                },
            }
        if tool_name == "get_news":
            assert tool_args["direction"] == "up"
            item = directional_news_item()
            item.update(
                {
                    "direction": "up",
                    "direction_keywords": ["상승", "호재"],
                    "has_direction_evidence": True,
                }
            )
            return {"success": True, "data": {"news": [item]}}
        if tool_name == "get_disclosure":
            return {"success": True, "data": {"disclosures": []}}
        raise AssertionError(f"unexpected tool: {tool_name}")

    monkeypatch.setattr("app.graph.nodes._executor.execute", fake_execute)

    state = create_initial_state("direction-rising-actual")
    state["ticker"] = "삼성전자"
    state["messages"] = [HumanMessage(content="오르고 있는데 왜 떨어져?")]

    result = await tool_node(state)

    assert "현재 삼성전자는 상승 중입니다" in result["direction_notice"]


async def test_response_node_prepends_direction_notice_when_llm_omits_it(monkeypatch):
    class FakeResult:
        message = type("Message", (), {"content": "삼성전자 ▲ 1.77% 상승\n\n원인 분석"})()
        model_name = "fake-router-model"
        model_id = "solar"
        fallback_used = False

    async def fake_ainvoke(*args, **kwargs):
        return FakeResult()

    monkeypatch.setattr("app.graph.nodes.ainvoke_with_fallback", fake_ainvoke)

    notice = "아닙니다. 현재 삼성전자는 상승 중입니다. 아래는 최근 상승과 관련 있어 보이는 주요 이유입니다."
    state = create_initial_state("direction-notice-response")
    state["ticker"] = "삼성전자"
    state["price_data"] = {**stock_snapshot(), "change_pct": 1.77}
    state["news_items"] = [_normalize_news_item(directional_news_item(), "up")]
    state["direction_notice"] = notice
    state["messages"] = [HumanMessage(content="왜 떨어졌어?")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert content.startswith(notice)
    assert "투자 자문이 아닌" in content


async def test_response_node_moves_direction_notice_before_stale_prefix(monkeypatch):
    notice = "아닙니다. 현재 삼성전자는 상승 중입니다. 아래는 최근 상승과 관련 있어 보이는 주요 이유입니다."

    class FakeResult:
        message = type(
            "Message",
            (),
            {
                "content": (
                    "삼성전자 ▼ 2.30% 하락\n\n"
                    f"방향 보정 안내: {notice}\n\n"
                    "삼성전자 ▲ 1.77% 상승\n\n원인 분석"
                )
            },
        )()
        model_name = "fake-router-model"
        model_id = "solar"
        fallback_used = False

    async def fake_ainvoke(*args, **kwargs):
        return FakeResult()

    monkeypatch.setattr("app.graph.nodes.ainvoke_with_fallback", fake_ainvoke)

    state = create_initial_state("direction-notice-stale-prefix")
    state["ticker"] = "삼성전자"
    state["price_data"] = {**stock_snapshot(), "change_pct": 1.77}
    state["news_items"] = [_normalize_news_item(directional_news_item(), "up")]
    state["direction_notice"] = notice
    state["messages"] = [HumanMessage(content="오르고 있는데 왜 떨어져?")]

    result = await response_node(state)
    content = result["messages"][-1].content

    assert content.startswith(notice)
    assert "삼성전자 ▼ 2.30% 하락" not in content
    assert "삼성전자 ▲ 1.77% 상승" in content


from app.graph.router import _keyword_router, router_node


class TestKeywordRouter:
    """LLM 없이 keyword fallback 로직만 검증."""

    def test_price_query_single_item(self):
        result = _keyword_router("상추 지금 비싸?")
        assert result.intent == "price"
        assert "상추" in result.items

    def test_price_query_multiple_items(self):
        result = _keyword_router("오이랑 당근 요즘 어때?")
        assert result.intent == "price"
        assert "오이" in result.items
        assert "당근" in result.items

    def test_offtopic_greeting(self):
        result = _keyword_router("안녕하세요")
        assert result.intent == "off-topic"
        assert result.items == []

    def test_offtopic_unrelated(self):
        result = _keyword_router("파이썬 공부 어떻게 해?")
        assert result.intent == "off-topic"

    def test_price_keyword_only(self):
        result = _keyword_router("요즘 시세가 많이 올랐나요?")
        assert result.intent == "price"


class TestRouterNode:
    """router_node async 실행 검증 — LLM 오류 시 keyword fallback 사용."""

    async def test_price_path(self):
        state = {"user_query": "상추 지금 비싸?"}
        result = await router_node(state)
        assert result["route"] in ("price", "off-topic")

    async def test_offtopic_path(self):
        state = {"user_query": "안녕하세요"}
        result = await router_node(state)
        assert "route" in result
        assert "items" in result

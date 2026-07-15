from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.tools.judge import judge_price_node
from app.tools.kamis import get_raw_price_node
from app.tools.user_input import user_input_node

from .nodes import (
    compare_items_node,
    generate_answer_node,
    generate_offtopic_node,
    resolve_processed_items_node,
    search_knowledge_node,
    search_processed_price_node,
    search_substitute_node,
)
from .router import router_node, validate_request_node
from .state import AgentState

_EXPENSIVE_STATUS = "비쌈"

def _route_decision(state: AgentState) -> str:
    return state.get("route", "off-topic")

def _post_router_decision(state: AgentState) -> str:
    """[2차 방어] router가 이미 off-topic으로 판단했으면 검증 LLM 호출을 아껴 바로
    거절 응답으로 보내고, price/knowledge/hybrid일 때만 validate_request로 한 번 더
    검증한다."""
    return "off-topic" if state.get("route") == "off-topic" else "validate"


def _post_resolve_decision(state: AgentState) -> str:
    """[시나리오 1] 원물(kamis) + 가공식품(price_gokr) 2개 품목이 모두 조회됐으면
    비교 플로우로, [가공식품 단독 조회] 품목 전부가 KAMIS에 없으면 가공식품 검색
    플로우로, 그 외엔 기존 judge_price 플로우로 분기.

    [2026-07-14 추가] "참치캔 얼마야?" 같은 가공식품 단독 조회 지원 — 단, KAMIS
    품목과 가공식품이 섞인 질문(예: "상추랑 참치캔")은 이번 스코프 밖이라 기존
    judge_price로 그대로 감(참치캔은 기존과 동일하게 "미지원" 처리, 회귀 없음).
    """
    price_data = state.get("price_data", [])
    if len(price_data) == 2:
        sources = {item.get("source") for item in price_data}
        if sources == {"kamis", "price_gokr"} and all(item.get("found") for item in price_data):
            return "compare"
    if price_data and all(not item.get("found") for item in price_data):
        return "processed_price"
    return "judge"


def _post_judge_decision(state: AgentState) -> str:
    """hybrid 경로에서만 비쌈 판정 시 대체품 검색으로 분기, 그 외엔 바로 답변 생성."""
    #if state.get("route") != "hybrid":
    #    return "answer"
    judgments = state.get("judgment", [])
    if any(j.get("status") == _EXPENSIVE_STATUS for j in judgments):
        return "substitute"
    return "answer"


def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)
    graph.add_node("router", router_node)
    graph.add_node("validate_request", validate_request_node)
    graph.add_node("user_input", user_input_node)
    graph.add_node("get_raw_price", get_raw_price_node)
    graph.add_node("resolve_processed_items", resolve_processed_items_node)
    graph.add_node("compare_items", compare_items_node)
    graph.add_node("search_processed_price", search_processed_price_node)
    graph.add_node("judge_price", judge_price_node)
    graph.add_node("search_knowledge", search_knowledge_node)
    graph.add_node("search_substitute", search_substitute_node)
    graph.add_node("generate_answer", generate_answer_node)
    graph.add_node("generate_offtopic", generate_offtopic_node)

    
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "router",
        _post_router_decision,
        {
            "off-topic": "generate_offtopic",
            "validate": "validate_request",
        },
    )
    graph.add_conditional_edges(
        "validate_request",
        _route_decision,
        {
            # [2026-07-15 추가] region/unit이 필요한 price/hybrid 경로만 user_input을
            # 거침 — knowledge는 가격과 무관해 이 LLM 호출을 아낌. 프론트에서 이미
            # selectbox로 region/unit을 넘겼으면 user_input_node가 LLM 호출 없이
            # 그대로 통과시킴(텍스트만 온 경우에만 LLM으로 추출 시도).
            "price": "user_input",
            "hybrid": "user_input",
            "knowledge": "search_knowledge",
            "off-topic": "generate_offtopic",
        },
    )
    graph.add_edge("user_input", "get_raw_price")
    # [시나리오 1] get_raw_price(KAMIS) 이후 항상 resolve_processed_items를 거침 —
    # 일반적인 단일/다중 원물 조회는 이 노드가 그대로 통과시켜(price_data 변경 없음)
    # 기존 judge_price 흐름과 동일하게 동작하고, "원물 1개 + 가공식품 1개" 조합일 때만
    # compare_items로 분기됨.
    graph.add_edge("get_raw_price", "resolve_processed_items")
    graph.add_conditional_edges(
        "resolve_processed_items",
        _post_resolve_decision,
        {
            "compare": "compare_items",
            "processed_price": "search_processed_price",
            "judge": "judge_price",
        },
    )
    graph.add_edge("compare_items", "generate_answer")
    graph.add_edge("search_processed_price", "generate_answer")
    graph.add_conditional_edges(
        "judge_price",
        _post_judge_decision,
        {
            "substitute": "search_substitute",
            "answer": "generate_answer",
        },
    )
    graph.add_edge("search_substitute", "generate_answer")
    graph.add_edge("search_knowledge", "generate_answer")
    graph.add_edge("generate_answer", END)
    graph.add_edge("generate_offtopic", END)

    return graph


compiled_graph = build_graph().compile()

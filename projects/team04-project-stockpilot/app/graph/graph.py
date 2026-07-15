"""그래프 조립 + 싱글톤 컴파일."""
from langgraph.graph import END, StateGraph
from loguru import logger

from app.graph.edges import route_by_intent
from app.graph.nodes import rag_node, response_node, router_node, tool_node
from app.graph.state import StockPilotState

_graph = None


def _build_graph():
    """노드·엣지를 등록하고 컴파일한다."""
    builder = StateGraph(StockPilotState)
    builder.add_node("router", router_node)
    builder.add_node("rag", rag_node)
    builder.add_node("tool", tool_node)
    builder.add_node("response", response_node)

    builder.set_entry_point("router")
    builder.add_conditional_edges(
        "router",
        route_by_intent,
        {"rag": "rag", "tool": "tool", "response": "response"},
    )
    builder.add_edge("rag", "response")
    builder.add_edge("tool", "response")
    builder.add_edge("response", END)
    return builder.compile()


def get_stockpilot_graph():
    """컴파일된 그래프를 싱글톤으로 반환한다."""
    global _graph
    if _graph is None:
        _graph = _build_graph()
        logger.info("✅ StockPilot 그래프 컴파일 완료")
    return _graph

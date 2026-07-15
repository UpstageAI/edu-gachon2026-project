"""LangGraph 그래프 구성: START -> router -> (rag|tool|response) -> response -> END."""

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_by_intent
from app.graph.nodes import (
    ask_admission_year_node,
    out_of_scope_node,
    rag_node,
    reminder_node,
    response_node,
    router_node,
    tool_node,
)
from app.graph.state import AgentState

_compiled = None
_checkpointer: BaseCheckpointSaver | None = None


def set_checkpointer(checkpointer: BaseCheckpointSaver | None) -> None:
    """앱 시작 시(lifespan) 체크포인터를 주입한다. 이후 첫 get_graph() 호출에서 반영."""
    global _checkpointer, _compiled
    _checkpointer = checkpointer
    _compiled = None


def create_graph():
    builder = StateGraph(AgentState)
    builder.add_node("router", router_node)
    builder.add_node("rag", rag_node)
    builder.add_node("tool", tool_node)
    builder.add_node("reminder", reminder_node)
    builder.add_node("ask_year", ask_admission_year_node)
    builder.add_node("out_of_scope", out_of_scope_node)
    builder.add_node("response", response_node)

    builder.add_edge(START, "router")
    builder.add_conditional_edges(
        source="router",
        path=route_by_intent,
        path_map={
            "rag": "rag",
            "tool": "tool",
            "reminder": "reminder",
            "ask_year": "ask_year",
            "out_of_scope": "out_of_scope",
            "response": "response",
        },
    )
    builder.add_edge("rag", "response")
    builder.add_edge("tool", "response")
    # reminder 노드는 결정적 템플릿으로 답을 직접 만들어 response(LLM)를 거치지 않는다.
    builder.add_edge("reminder", END)
    # ask_year(학번 되묻기)도 결정적 템플릿으로 질문만 던지고 END로 간다.
    builder.add_edge("ask_year", END)
    # out_of_scope(타 학과 안내)도 결정적 템플릿으로 안내만 하고 END로 간다.
    builder.add_edge("out_of_scope", END)
    builder.add_edge("response", END)
    return builder.compile(checkpointer=_checkpointer)


def get_graph():
    global _compiled
    if _compiled is None:
        _compiled = create_graph()
    return _compiled

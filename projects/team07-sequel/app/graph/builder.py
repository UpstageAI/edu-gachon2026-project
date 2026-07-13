"""Sequel 에이전트 LangGraph 워크플로우 빌더.

흐름: schema_link → route → generate → validate → execute → format
- route 에서 안전성 실패(injection/위험) → 곧바로 format(거절)
- validate 실패 & 재시도 여력 → generate 로 되돌림(재생성 루프, 최대 settings.agent_max_retries)
- validate 실패 & 여력 소진 → format(오류 안내)
- execute 런타임 오류 & 여력 → generate(실행 피드백 수리, MapleRepair 식) / 소진 → format

출력: 컴파일된 그래프 (invoke / ainvoke / astream_events 지원)
"""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from app.core.settings import settings
from app.graph.nodes.executor import execute
from app.graph.nodes.formatter import format_answer
from app.graph.nodes.generator import generate
from app.graph.nodes.query_normalizer import normalize
from app.graph.nodes.router import route
from app.graph.nodes.schema_linker import schema_link
from app.graph.nodes.validator import validate
from app.graph.state import AgentState

# SSE 에서 진행 상황을 흘려보낼 노드 이름들
NODE_NAMES = ("normalize", "schema_link", "route", "generate", "validate", "execute", "format")


def _after_route(state: AgentState) -> str:
    """안전성 판정: ok 가 명시적 True 일 때만 generate, 그 외(누락 포함) → format(거절, fail-closed)."""
    return "generate" if state.get("safety", {}).get("ok") is True else "format"


def _after_validate(state: AgentState) -> str:
    """검증 통과 → execute. 실패 & 재시도 여력 → generate. 실패 & 소진 → format."""
    if state.get("validation", {}).get("ok", False):
        return "execute"
    if state.get("iteration", 0) < settings.agent_max_retries:
        return "generate"
    return "format"


def _after_execute(state: AgentState) -> str:
    """실행 런타임 오류 & 여력 → generate(수리 재생성). 정상(빈 결과 포함) → format."""
    if state.get("exec_error") and state.get("iteration", 0) < settings.agent_max_retries:
        return "generate"
    return "format"


def build_graph():
    """상태 그래프를 구성·컴파일해 반환한다."""
    g = StateGraph(AgentState)
    g.add_node("normalize", normalize)
    g.add_node("schema_link", schema_link)
    g.add_node("route", route)
    g.add_node("generate", generate)
    g.add_node("validate", validate)
    g.add_node("execute", execute)
    g.add_node("format", format_answer)

    g.add_edge(START, "normalize")
    g.add_edge("normalize", "schema_link")
    g.add_edge("schema_link", "route")
    g.add_conditional_edges("route", _after_route, {"generate": "generate", "format": "format"})
    g.add_edge("generate", "validate")
    g.add_conditional_edges(
        "validate", _after_validate,
        {"execute": "execute", "generate": "generate", "format": "format"},
    )
    g.add_conditional_edges("execute", _after_execute, {"generate": "generate", "format": "format"})
    g.add_edge("format", END)
    return g.compile()

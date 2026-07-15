"""stateless LangGraph 조립 — B흐름(조리 중 음성질의).

recommend 그래프와 마찬가지로 Checkpointer 없이 요청마다 새 VoiceQueryState로
1회 invoke한다.
"""

from functools import lru_cache

from langfuse import observe
from langgraph.graph import END, START, StateGraph

from app.agent.nodes.voice_query_nodes import (
    MAX_VOICE_TURNS,
    voice_input_guardrail,
    voice_react_agent,
    voice_resolve_inputs,
    voice_respond,
    voice_tool_node,
    voice_validate,
)
from app.agent.voice_state import VoiceQueryState


def _route_after_voice_guardrail(state: VoiceQueryState) -> str:
    return "voice_respond" if state.guardrail_blocked else "voice_react_agent"


def _route_after_voice_react_agent(state: VoiceQueryState) -> str:
    tool_calls = getattr(state.messages[-1], "tool_calls", None)
    if tool_calls and state.turns < MAX_VOICE_TURNS:
        return "voice_tool_node"
    return "voice_validate"


def build_voice_query_graph():
    graph = StateGraph(VoiceQueryState)
    graph.add_node("voice_resolve_inputs", voice_resolve_inputs)
    graph.add_node("voice_input_guardrail", voice_input_guardrail)
    graph.add_node("voice_react_agent", voice_react_agent)
    graph.add_node("voice_tool_node", voice_tool_node)
    graph.add_node("voice_validate", voice_validate)
    graph.add_node("voice_respond", voice_respond)

    graph.add_edge(START, "voice_resolve_inputs")
    graph.add_edge("voice_resolve_inputs", "voice_input_guardrail")
    graph.add_conditional_edges(
        "voice_input_guardrail",
        _route_after_voice_guardrail,
        {"voice_respond": "voice_respond", "voice_react_agent": "voice_react_agent"},
    )
    graph.add_conditional_edges(
        "voice_react_agent",
        _route_after_voice_react_agent,
        {"voice_tool_node": "voice_tool_node", "voice_validate": "voice_validate"},
    )
    graph.add_edge("voice_tool_node", "voice_react_agent")
    graph.add_edge("voice_validate", "voice_respond")
    graph.add_edge("voice_respond", END)

    return graph.compile()


@lru_cache
def get_voice_graph():
    return build_voice_query_graph()


@observe(name="voice_query_graph")
def run_voice_query(
    recipe_id: str,
    allergen_ids: list[str],
    question: str,
    current_step_text: str | None = None,
) -> VoiceQueryState:
    initial_state = VoiceQueryState(
        recipe_id=recipe_id,
        allergen_ids=allergen_ids,
        question=question,
        current_step_text=current_step_text,
    )
    result = get_voice_graph().invoke(initial_state, config={"recursion_limit": 15})
    return VoiceQueryState(**result)

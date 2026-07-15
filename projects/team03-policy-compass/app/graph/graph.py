"""Build the bounded, recovery-capable policy-agent LangGraph.

The graph exposes only meaningful orchestration steps.  Contract validation,
profile extraction, and missing-slot calculation are part of one request-plan
node; deterministic direct responses share one path.  Search and answer loops
have explicit counters in turn state and therefore cannot run indefinitely.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.graph import edges as E
from app.graph import nodes as N
from app.graph.state import AgentState


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("prepare_request", N.prepare_request_node)
    graph.add_node("direct_response", N.direct_response_node)
    graph.add_node("retrieve", N.policy_search_node)
    graph.add_node("assess_evidence", N.evidence_assessment_node)
    graph.add_node("rewrite_query", N.rewrite_query_node)
    graph.add_node("build_answer", N.response_node)
    graph.add_node("verify_answer", N.response_validator_node)
    graph.add_node("finalize", N.finalize_response_node)

    graph.set_entry_point("prepare_request")
    graph.add_conditional_edges(
        "prepare_request",
        E.route_after_prepare,
        {
            "direct_response": "direct_response",
            "retrieve": "retrieve",
        },
    )

    graph.add_edge("retrieve", "assess_evidence")
    graph.add_conditional_edges(
        "assess_evidence",
        E.route_after_evidence,
        {
            "retrieve": "retrieve",
            "rewrite_query": "rewrite_query",
            "build_answer": "build_answer",
            "direct_response": "direct_response",
        },
    )
    graph.add_edge("rewrite_query", "retrieve")

    graph.add_edge("build_answer", "verify_answer")
    graph.add_conditional_edges(
        "verify_answer",
        E.route_after_verification,
        {
            "build_answer": "build_answer",
            "direct_response": "direct_response",
            "finalize": "finalize",
        },
    )

    # Fixed/direct replies are verified too; this makes the general-scope and
    # startup-template checks real graph defenses instead of dead functions.
    graph.add_edge("direct_response", "verify_answer")
    graph.add_edge("finalize", END)

    return graph.compile()


_agent_graph = None


def get_agent_graph():
    global _agent_graph  # noqa: PLW0603
    if _agent_graph is None:
        _agent_graph = build_agent_graph()
    return _agent_graph

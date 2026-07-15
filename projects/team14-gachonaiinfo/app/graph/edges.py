"""조건부 라우팅: router 이후 intent에 따라 분기."""

from typing import Literal

from app.graph.state import AgentState


def route_by_intent(
    state: AgentState,
) -> Literal["rag", "tool", "reminder", "ask_year", "out_of_scope", "response"]:
    intent = state.get("intent") or "chat"
    if intent == "rag":
        return "rag"
    if intent == "tool":
        return "tool"
    if intent == "reminder":
        return "reminder"
    if intent == "ask_year":
        return "ask_year"
    if intent == "out_of_scope":
        return "out_of_scope"
    return "response"

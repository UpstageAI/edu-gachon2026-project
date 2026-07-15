"""조건부 엣지 — intent에 따라 다음 노드 결정."""
from app.graph.state import StockPilotState


def route_by_intent(state: StockPilotState) -> str:
    """router 이후 이동할 노드 이름을 반환한다."""
    intent = state.get("intent")
    if intent == "rag":
        return "rag"
    if intent == "tool":
        return "tool"
    return "response"

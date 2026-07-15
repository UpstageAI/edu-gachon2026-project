"""LangGraph State — 노드들이 공유하는 작업 데이터.

router → rag/tool → response 로 이어지는 동안, 각 노드가 이 State를 읽고
필요한 필드를 채워 넣는다.
"""
from typing import Annotated, Any, Literal, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# 라우터가 분류하는 의도
Intent = Literal["chat", "rag", "tool"]
ToolMode = Literal["market", "disclosure"]


class StockPilotState(TypedDict, total=False):
    """에이전트 상태."""

    messages: Annotated[list[BaseMessage], add_messages]
    intent: Optional[Intent]
    retrieved_docs: list[str]
    ticker: Optional[str]
    tool_name: Optional[str]
    tool_args: Optional[dict[str, Any]]
    tool_result: Optional[Any]
    tool_mode: Optional[ToolMode]       # market=시세·뉴스, disclosure=공시 전용
    response_mode: Optional[str]        # LLM 라우터가 지정한 응답 방식(disclosure_risk 등)
    price_data: Optional[Any]
    news_items: list[dict[str, Any]]
    disclosures: list[dict[str, Any]]   # 최근 공시 목록 (4번째 도구)
    direction_notice: Optional[str]      # 질문 방향과 실제 등락 방향이 다를 때 사용자 안내
    is_followup: Optional[bool]          # 직전 종목 문맥을 이어받은 질문인지 여부
    panel_update: Optional[bool]         # 프론트 인사이트 패널을 새로 갱신할지 여부
    screen: Optional[bool]              # 급등·급락 스크리너 모드
    screener_results: Optional[Any]     # 스크리너 결과 목록
    screener_panels: Optional[Any]      # 스크리너 상위 종목별 패널(시세·뉴스·공시)
    session_id: str
    user_id: Optional[str]
    model: Optional[str]        # 선택한 LLM 모델 id
    used_model: Optional[str]   # 실제 응답을 만든 모델(폴백 반영)


def create_initial_state(
    session_id: str,
    user_id: str | None = None,
    model: str | None = None,
) -> StockPilotState:
    """초기 상태 생성. 그래프 실행 시작 시 사용한다."""
    return {
        "messages": [],
        "intent": None,
        "retrieved_docs": [],
        "ticker": None,
        "tool_name": None,
        "tool_args": None,
        "tool_result": None,
        "tool_mode": None,
        "response_mode": None,
        "price_data": None,
        "news_items": [],
        "disclosures": [],
        "direction_notice": None,
        "screen": False,
        "screener_results": None,
        "session_id": session_id,
        "user_id": user_id,
        "model": model,
    }

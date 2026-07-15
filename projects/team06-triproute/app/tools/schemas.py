from typing import Any, Dict, Literal

from pydantic import BaseModel, Field


ToolName = Literal[
    "search_places",
    "get_related_places",
    "get_route_info",
    "estimate_cost",
]


class ToolCall(BaseModel):
    """
    ReAct Loop에서 Agent가 호출할 Tool의 이름과 입력값을 정의합니다.
    """

    tool_name: ToolName = Field(..., description="실행할 도구 이름")
    tool_input: Dict[str, Any] = Field(default_factory=dict, description="도구 입력값")


class ToolResult(BaseModel):
    """
    Tool 실행 결과를 공통 형식으로 반환합니다.
    """

    tool_name: str
    observation: Dict[str, Any]
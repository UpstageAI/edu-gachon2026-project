"""채팅 API 요청/응답 및 SSE 스트리밍 이벤트 스키마."""
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import orjson
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """클라이언트 → 서버 채팅 요청."""

    agent_mode: Literal["router", "react", "full_react"] = Field(
        default="full_react",
        description=(
            "답변 생성 방식. full_react는 기본 LangGraph prebuilt ReAct 루프, "
            "router는 기존 규칙 기반 안정 흐름, react는 JSON 기반 실험 루프."
        ),
    )

    model: Optional[str] = Field(
        default=None,
        description="사용할 LLM 모델 id (미지정 시 기본 solar). 예: gpt-4o-mini, gemini-2.0-flash, claude-haiku",
    )

    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="사용자 메시지",
        examples=["삼성전자 요즘 어때?", "PER이 뭐야?"],
    )
    session_id: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="세션 식별자(대화 지속성)",
    )
    user_id: Optional[str] = Field(
        default=None,
        max_length=100,
        description="사용자 식별자(선택)",
    )


class ChatResponse(BaseModel):
    """서버 → 클라이언트 단건 응답(비스트리밍)."""

    message: str = Field(..., description="에이전트 응답 메시지")
    tool_used: Optional[str] = Field(default=None, description="사용된 도구 이름")
    cached: bool = Field(default=False, description="캐시된 응답 여부")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="응답 생성 시각(UTC)",
    )


# SSE 이벤트 타입
StreamEventType = Literal["thinking", "token", "tool", "response", "glossary", "error", "done"]


class StreamEvent(BaseModel):
    """SSE로 전송되는 이벤트 한 조각.

    type별로 채워지는 필드:
        thinking : content(진행 상태, 예 "뉴스 분석 중...")
        token    : content(LLM 토큰 한 조각)
        tool     : tool_name (+ tool_result 요약)
        response : content(최종 응답) + tool_used
        glossary : terms(답변 안에서 발견된 용어 사전 매칭 목록)
        error    : error(에러 메시지)
        done     : 필드 없음(종료 신호)
    """

    type: StreamEventType = Field(..., description="이벤트 타입")
    node: Optional[str] = Field(default=None, description="현재 실행 중인 노드")
    content: Optional[str] = Field(default=None, description="텍스트(토큰/응답/상태)")
    tool_name: Optional[str] = Field(default=None, description="실행된 도구 이름")
    tool_result: Optional[Any] = Field(default=None, description="도구 실행 결과")
    tool_used: Optional[str] = Field(default=None, description="최종 응답에 쓰인 도구")
    terms: Optional[list[dict[str, Any]]] = Field(
        default=None, description="답변 텍스트 안에서 매칭된 용어 사전 항목"
    )
    model: Optional[str] = Field(default=None, description="실제 응답을 생성한 모델 이름")
    error: Optional[str] = Field(default=None, description="에러 메시지")

    def to_sse(self) -> str:
        """SSE 형식 문자열로 변환.

        Returns:
            'data: {json}\\n\\n' — None인 필드는 제외하고 직렬화한다.
        """
        data = {k: v for k, v in self.model_dump().items() if v is not None}
        return f"data: {orjson.dumps(data).decode('utf-8')}\n\n"

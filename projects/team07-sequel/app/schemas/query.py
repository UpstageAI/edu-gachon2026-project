"""API 요청/응답 DTO (Pydantic).

HTTP 경계에서 쓰는 스키마. 그래프 내부 상태(AgentState)와는 분리한다.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    """자연어 질의 요청.

    입력: question(1~2000자), session_id(옵션, 1~200자)
    """

    question: str = Field(..., min_length=1, max_length=2000)
    session_id: str | None = Field(
        default=None, min_length=1, max_length=200,
        description="프론트에서 생성한 접속 단위 UUID. 없으면 히스토리 없이(무상태) 처리.",
    )


class QueryResponse(BaseModel):
    """질의 처리 결과 (동기 응답).

    출력: 자연어 요약 + 표(columns/rows) + 실행 SQL + 라우팅 메타.
    """

    summary: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    sql: str = ""
    difficulty: str = ""
    model: str = ""
    error: str = ""


class SuggestionsRequest(BaseModel):
    """후속질문 제안 요청.

    입력: session_id(필수, 1~200자) — 직전 /query 또는 /query/stream 에 실어 보낸 것과 동일해야 함.
    """

    session_id: str = Field(..., min_length=1, max_length=200)


class SuggestionsResponse(BaseModel):
    """후속질문 제안 응답.

    출력: suggestions(0~2개). 히스토리가 없거나 만료됐으면 빈 배열(정상 케이스, 에러 아님).
    """

    suggestions: list[str] = Field(default_factory=list)


class StreamEvent(BaseModel):
    """SSE 이벤트 한 건.

    event: "node"(노드 완료) | "done"(최종) | "error"
    node:  노드 이름 (event=="node" 일 때)
    data:  JSON 직렬화된 페이로드
    """

    event: str = "node"
    node: str = ""
    data: str = ""

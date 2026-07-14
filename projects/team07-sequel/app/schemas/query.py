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
    # ── 관측 메타 (이 질의 1건 기준; UI 의 "지연·토큰·비용" 표시용) ──
    latency_ms: int = 0        # 그래프 전체 처리 wall-clock (ms)
    total_tokens: int = 0      # 이 질의가 쓴 LLM 토큰 합(입력+출력, 전 노드)
    cost_usd: float = 0.0      # total_tokens 의 Upstage 단가 환산 (Langfuse totalCost=0 라 직접 계산)


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


class Kpi(BaseModel):
    """대시보드 KPI 카드 1개.

    key: llm_calls | avg_latency_ms | total_tokens | cost_usd
      - llm_calls 는 Langfuse GENERATION(실제 LLM 호출) 수. 질의 1건이 4콜 안팎이라
        사용자 "질의 수"와 다르다(정확한 질의 수는 로컬 집계가 있어야 함).
      - avg_latency_ms 는 LLM 콜 1건당 평균 지연(질의 전체 wall-clock 아님).
    delta_pct: 어제 대비 증감률(%). 어제 값이 0/없으면 None.
    """

    key: str
    value: float = 0.0
    delta_pct: float | None = None


class MetricsResponse(BaseModel):
    """Home 대시보드 KPI (Langfuse Metrics API 집계 프록시).

    오늘(KST 00:00~현재) 값 + 어제 대비 delta. Langfuse 키가 없거나 조회 실패면
    available=False + 빈 kpis (에러 아님 — 대시보드는 빈 카드로 그리면 됨).
    """

    kpis: list[Kpi] = Field(default_factory=list)
    as_of: str = ""            # 기준 날짜 (KST, YYYY-MM-DD)
    available: bool = True     # Langfuse 미연결/조회 실패면 False


class StreamEvent(BaseModel):
    """SSE 이벤트 한 건.

    event: "node"(노드 완료) | "done"(최종) | "error"
    node:  노드 이름 (event=="node" 일 때)
    data:  JSON 직렬화된 페이로드
    """

    event: str = "node"
    node: str = ""
    data: str = ""

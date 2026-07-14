"""HTTP 컨트롤러 — 자연어 질의 엔드포인트. 얇게 유지(요청 수신 → 서비스 위임 → 응답).

POST /api/v1/query          동기 응답 (QueryResponse)
POST /api/v1/query/stream   SSE 로 노드 진행 상황 스트리밍
POST /api/v1/suggestions    직전 턴 기반 후속질문 제안 (동기)
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.schemas.query import (
    MetricsResponse,
    QueryRequest,
    QueryResponse,
    SuggestionsRequest,
    SuggestionsResponse,
)
from app.repositories import schema_repository
from app.services import metrics_service
from app.services.query_service import query_service

router = APIRouter()


@router.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """질의를 처리해 요약·표·SQL 을 반환한다."""
    return await query_service.run(req.question, req.session_id)


@router.post("/query/stream")
async def query_stream(req: QueryRequest):
    """각 노드 완료 시점을 SSE(text/event-stream) 로 흘려보낸다."""

    async def gen():
        async for event in query_service.stream(req.question, req.session_id):
            yield f"data: {event.model_dump_json()}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/suggestions", response_model=SuggestionsResponse)
async def suggestions(req: SuggestionsRequest) -> SuggestionsResponse:
    """직전 성공 턴을 바탕으로 후속질문 버튼용 텍스트를 최대 2개 반환한다."""
    return SuggestionsResponse(suggestions=await query_service.suggest_followups(req.session_id))


@router.get("/metrics", response_model=MetricsResponse)
async def metrics() -> MetricsResponse:
    """Home 대시보드 KPI (Langfuse Metrics API 집계 프록시). 미연결 시 available=False."""
    return await metrics_service.dashboard_kpis()


@router.get("/schema")
def schema() -> dict:
    """스키마 브라우저용 테이블·컬럼 카탈로그 (읽기 전용 메타, 행 데이터 없음).

    sync 라 FastAPI 가 스레드풀에서 실행(schema_repository 는 동기 SQLAlchemy).
    """
    return {"tables": schema_repository.catalog()}

"""AI agent(app/) 의 /api/v1 엔드포인트를 프론트로 그대로 흘려주는 패스스루 프록시.

프론트는 backend(이 서비스, LB 뒤)만 호출하지만, 스트리밍 진행상황·후속질문·비용/토큰
KPI 같은 기능은 agent(app/)에만 있다. 그래서 이 세 경로를 agent 로 투명하게 넘긴다.

    POST /api/v1/query/stream   → agent 스트림(SSE)을 청크 단위로 그대로 relay
    POST /api/v1/suggestions    → agent 로 전달, JSON 반환
    GET  /api/v1/metrics        → agent 로 전달, JSON 반환
    GET  /api/v1/schema         → agent 로 전달, JSON 반환 (스키마 브라우저)

주의: 이 경로들은 backend 의 guardrail 재검증·자체 DB 재실행(defense-in-depth,
/api/query 경로)을 거치지 않는다 — agent 결과를 그대로 전달한다. 재검증이 필요해지면
여기서 agent 응답을 가로채 검증 로직을 끼우면 된다.
"""

import json

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.schemas.query import QueryRequest

router = APIRouter()

# agent 질의는 스키마 링킹+LLM 다단계라 수십 초 걸림 → 넉넉히. 스트림 read 는 무제한.
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, write=30.0, read=None, pool=10.0)
_JSON_TIMEOUT = httpx.Timeout(30.0)


class SuggestionsRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


@router.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest):
    """agent 의 SSE 스트림을 그대로 relay. 연결 실패 시 error 이벤트로 마감."""

    async def relay():
        try:
            async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    "/api/v1/query/stream",
                    json={"question": req.question, "session_id": req.session_id},
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_raw():
                        yield chunk
        except Exception:  # noqa: BLE001 — agent 도달 실패도 스트림을 error 로 정상 종료
            payload = json.dumps({"event": "error", "data": "잠시 후 다시 시도해 주세요."}, ensure_ascii=False)
            yield f"data: {payload}\n\n".encode("utf-8")

    return StreamingResponse(relay(), media_type="text/event-stream")


@router.post("/api/v1/suggestions")
async def suggestions(req: SuggestionsRequest):
    """agent 후속질문 제안을 전달. 실패 시 빈 배열(정상 케이스)."""
    try:
        async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_JSON_TIMEOUT) as client:
            resp = await client.post("/api/v1/suggestions", json={"session_id": req.session_id})
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception:  # noqa: BLE001
        return JSONResponse({"suggestions": []})


@router.get("/api/v1/metrics")
async def metrics():
    """agent 대시보드 KPI 를 전달. 실패 시 available=false."""
    try:
        async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_JSON_TIMEOUT) as client:
            resp = await client.get("/api/v1/metrics")
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception:  # noqa: BLE001
        return JSONResponse({"kpis": [], "as_of": "", "available": False})


@router.get("/api/v1/schema")
async def schema():
    """agent 스키마 카탈로그(테이블·컬럼)를 전달. 실패 시 빈 목록(프론트가 안내 처리)."""
    try:
        async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_JSON_TIMEOUT) as client:
            resp = await client.get("/api/v1/schema")
            resp.raise_for_status()
            return JSONResponse(resp.json())
    except Exception:  # noqa: BLE001
        return JSONResponse({"tables": []})

"""AI agent(app/) 의 /api/v1 엔드포인트를 프론트로 흘려주는 프록시.

프론트는 backend(이 서비스, LB 뒤)만 호출하지만, 스트리밍 진행상황·후속질문·비용/토큰
KPI 같은 기능은 agent(app/)에만 있다. 그래서 이 세 경로를 agent 로 넘긴다.

    POST /api/v1/query/stream   → agent 스트림(SSE)을 이벤트 단위로 파싱해서 relay.
                                   단, "done" 이벤트만은 그냥 흘려보내지 않고 백엔드가
                                   가로채 guardrail 재검증 + 자체 DB 재실행 + 결과 재검증까지
                                   다시 거친 뒤(defense-in-depth), 통과한 결과만 done으로
                                   내보낸다. 재검증 실패 시 재시도 없이 바로 error 이벤트로
                                   마감한다(레거시 /api/query 와 동일한 "실패=즉시 종료" 정책 —
                                   agent에게 재생성을 요청하는 재생성 피드백 루프는 아직
                                   로컬 전용(`_wip_query_with_retry_loop.py.txt`)이라 여기
                                   엮지 않는다).
    POST /api/v1/suggestions    → agent 로 전달, JSON 반환 (재검증 대상 아님 — 텍스트 제안일 뿐)
    GET  /api/v1/metrics        → agent 로 전달, JSON 반환 (재검증 대상 아님 — 집계 KPI일 뿐)
"""

import json
import logging

import httpx
from fastapi import APIRouter
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.database import run_readonly_query_table
from app.schemas.query import QueryRequest
from app.services.guardrail import GuardrailError, validate_sql
from app.services.result_validator import ResultValidationError, validate_result

router = APIRouter()
logger = logging.getLogger(__name__)

# agent 질의는 스키마 링킹+LLM 다단계라 수십 초 걸림 → 넉넉히. 스트림 read 는 무제한.
_STREAM_TIMEOUT = httpx.Timeout(connect=10.0, write=30.0, read=None, pool=10.0)
_JSON_TIMEOUT = httpx.Timeout(30.0)
_GENERIC_ERROR = "잠시 후 다시 시도해 주세요."


class SuggestionsRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


def _sse_error(message: str) -> bytes:
    """agent 원본과 동일한 프레임 형식("data: {...}\\n\\n")으로 error 이벤트를 만든다."""
    payload = json.dumps({"event": "error", "node": "", "data": message}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _revalidate_done(data_str: str) -> bytes:
    """agent 의 done 페이로드(JSON 문자열)를 백엔드가 재검증한 뒤 done/error 프레임으로 변환.

    순서: guardrail(SQL 안전성) → 백엔드 자체 DB 재실행(read-only 계정) →
    result_validator(결과 타당성). 어느 하나라도 실패하면 agent에게 되돌려보내지
    않고(재생성 피드백 루프는 별도 기능, 아직 로컬 전용) 바로 error 이벤트로 끝낸다 —
    query.py(레거시 /api/query)의 실패 처리 정책과 동일하다.
    """
    try:
        answer = json.loads(data_str)
    except (TypeError, ValueError):
        logger.exception("agent done 페이로드 파싱 실패")
        return _sse_error(_GENERIC_ERROR)

    try:
        safe_sql = validate_sql(answer.get("sql", ""))
    except GuardrailError as e:
        return _sse_error(e.message)

    try:
        columns, row_lists = run_readonly_query_table(safe_sql)
    except Exception:  # noqa: BLE001 — DB 재실행 실패
        logger.exception("defense-in-depth 재실행 실패")
        return _sse_error("쿼리 실행 중 오류가 발생했습니다. SQL 문법이나 컬럼/테이블명을 확인해주세요.")

    if not row_lists:
        return _sse_error("조건에 맞는 결과가 없습니다.")

    try:
        validate_result([dict(zip(columns, row)) for row in row_lists])
    except ResultValidationError as e:
        return _sse_error(e.message)

    verified = {**answer, "sql": safe_sql, "table": {"columns": columns, "rows": row_lists}}
    payload = json.dumps(
        {"event": "done", "node": "", "data": json.dumps(verified, ensure_ascii=False, default=str)},
        ensure_ascii=False,
    )
    return f"data: {payload}\n\n".encode("utf-8")


def _process_frame(frame: str) -> bytes | None:
    """agent 가 보낸 SSE 프레임 한 개(개행 2개로 구분된 단위)를 처리한다.

    "data: <json>" 형식이 아니면 무시. event=="done"만 재검증을 거치고,
    나머지(node/error, 즉 진행 상황·agent 자체 오류)는 가공 없이 그대로 relay한다.
    """
    stripped = frame.strip()
    if not stripped.startswith("data:"):
        return None
    raw = stripped[len("data:"):].strip()
    try:
        outer = json.loads(raw)
    except (TypeError, ValueError):
        return _sse_error(_GENERIC_ERROR)

    if outer.get("event") == "done":
        return _revalidate_done(outer.get("data", ""))
    return (frame + "\n\n").encode("utf-8")


@router.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest):
    """agent 의 SSE 스트림을 이벤트 단위로 파싱해서 relay(done만 재검증). 연결 실패 시 error로 마감."""

    async def relay():
        buffer = ""
        try:
            async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_STREAM_TIMEOUT) as client:
                async with client.stream(
                    "POST",
                    "/api/v1/query/stream",
                    json={"question": req.question, "session_id": req.session_id},
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_text():
                        buffer += chunk
                        while "\n\n" in buffer:
                            frame, buffer = buffer.split("\n\n", 1)
                            out = _process_frame(frame)
                            if out is not None:
                                yield out
            if buffer.strip():  # agent 가 마지막 프레임을 개행 2개 없이 끝냈을 경우 대비
                out = _process_frame(buffer)
                if out is not None:
                    yield out
        except Exception:  # noqa: BLE001 — agent 도달 실패도 스트림을 error 로 정상 종료
            logger.exception("agent 스트림 relay 실패")
            yield _sse_error(_GENERIC_ERROR)

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

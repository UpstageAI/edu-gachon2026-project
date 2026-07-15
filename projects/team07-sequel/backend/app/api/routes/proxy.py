"""AI agent(app/) 의 /api/v1 엔드포인트를 프론트로 흘려주는 프록시.

프론트는 backend(이 서비스, LB 뒤)만 호출하지만, 스트리밍 진행상황·후속질문·비용/토큰
KPI·스키마 같은 기능은 agent(app/)에만 있다. 그래서 이 경로들을 agent 로 넘긴다.

    POST /api/v1/query/stream   → agent 스트림(SSE)을 이벤트 단위로 파싱해서 relay.
                                   단, "done" 이벤트만은 그냥 흘려보내지 않고 백엔드가
                                   가로채 guardrail 재검증 + 자체 DB 재실행 + 결과 재검증까지
                                   다시 거친 뒤(defense-in-depth), 통과한 결과만 done으로
                                   내보낸다.
    POST /api/v1/suggestions    → agent 로 전달, JSON 반환 (재검증 대상 아님 — 텍스트 제안일 뿐)
    GET  /api/v1/metrics        → agent 로 전달, JSON 반환 (재검증 대상 아님 — 집계 KPI일 뿐)
    GET  /api/v1/schema         → agent 로 전달, JSON 반환 (재검증 대상 아님 — 스키마 메타일 뿐)
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
# guardrail/DB 재실행/결과검증 실패를 _MAX_RETRIES회 재시도해도 못 넘기면 이 메시지로 마감한다.
# agent 쪽 formatter.py(검증 소진 분기)와 동일한 문구로 맞춰서, 사용자에게는 내부 guardrail
# 정규식 에러 원문("SELECT(또는 WITH로...)") 대신 이 사용자 친화적 문구만 노출한다.
_VALIDATION_FAILED_ERROR = "질문을 조금 다르게 표현해 주시겠어요? 안전한 SQL 을 만들지 못했어요."

# 최초 시도 포함 총 (_MAX_RETRIES + 1)번까지 agent에게 SQL 생성을 재요청한다.
# 너무 크게 잡으면 실패하는 질문에 대해 사용자가 오래 기다리게 되므로 작게 유지.
_MAX_RETRIES = 2


class SuggestionsRequest(BaseModel):
    session_id: str = Field(..., min_length=1, max_length=200)


class _TerminalError(Exception):
    """재시도해도 나아질 여지가 없는 실패 (payload 파싱 실패, 결과 없음 등)."""

    def __init__(self, message: str):
        self.message = message


class _RetryableError(Exception):
    """agent에게 사유를 알려주고 다시 시도해볼 가치가 있는 실패 (guardrail/DB 재실행/결과검증)."""

    def __init__(self, message: str):
        self.message = message


def _sse_error(message: str) -> bytes:
    """agent 원본과 동일한 프레임 형식("data: {...}\\n\\n")으로 error 이벤트를 만든다."""
    payload = json.dumps({"event": "error", "node": "", "data": message}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _sse_status(message: str) -> bytes:
    """agent 원본과 동일한 프레임 형식으로 status 이벤트를 만든다(재시도 중임을 알림)."""
    payload = json.dumps({"event": "status", "node": "", "data": message}, ensure_ascii=False)
    return f"data: {payload}\n\n".encode("utf-8")


def _done_frame(verified: dict) -> bytes:
    """재검증까지 통과한 최종 결과를 done 프레임으로 만든다."""
    payload = json.dumps(
        {"event": "done", "node": "", "data": json.dumps(verified, ensure_ascii=False, default=str)},
        ensure_ascii=False,
    )
    return f"data: {payload}\n\n".encode("utf-8")


def _build_retry_question(original_question: str, previous_failure: str | None) -> str:
    """agent에게 보낼 질문 문자열을 만든다.

    previous_failure가 없으면(최초 시도) 원본 질문 그대로 보낸다. 있으면(재시도)
    실패 이유를 자연어로 덧붙여서 agent가 같은 실수를 반복하지 않도록 유도한다.
    agent API(`ask_ai_agent`/`docs/api.md`)는 question·session_id 두 필드만
    받고 전용 피드백 파라미터가 없으므로, 새 파라미터를 추가하는 대신 이렇게
    question 문자열에 얹어 보내는 방식을 쓴다.
    """
    if previous_failure is None:
        return original_question
    return (
        f"{original_question}\n\n"
        f"(참고: 이전 시도에서 다음 문제가 발생했습니다 — {previous_failure} "
        "이 문제를 피해서 SQL을 다시 만들어주세요.)"
    )


def _revalidate(data_str: str) -> dict:
    """agent 의 done 페이로드(JSON 문자열)를 백엔드가 재검증한 뒤 통과한 결과를 돌려준다.

    순서: guardrail(SQL 안전성) → 백엔드 자체 DB 재실행(read-only 계정) →
    result_validator(결과 타당성). guardrail·DB 재실행·결과검증 실패는
    _RetryableError로(호출부가 agent에게 재요청할 수 있도록), payload 파싱 실패나
    "결과 없음"처럼 재시도해도 소용없는 경우는 _TerminalError로 구분해서 던진다.
    """
    try:
        answer = json.loads(data_str)
    except (TypeError, ValueError):
        logger.exception("agent done 페이로드 파싱 실패")
        raise _TerminalError(_GENERIC_ERROR)

    # 되묻기(값 모호)·안전성 거절·생성 실패처럼 agent 가 의도적으로 SQL 없이 보낸 답변은
    # 재실행할 쿼리가 없다 → 빈 SQL 을 guardrail 위반으로 막지 말고 그대로 통과시킨다.
    # (이게 없으면 되묻기 메시지가 guardrail 에러로 뒤덮여 사용자에게 도달하지 못함)
    if not (answer.get("sql") or "").strip():
        return answer

    try:
        safe_sql = validate_sql(answer.get("sql", ""))
    except GuardrailError as e:
        raise _RetryableError(e.message)

    try:
        columns, row_lists = run_readonly_query_table(safe_sql)
    except Exception as e:  # noqa: BLE001 — DB 재실행 실패
        logger.exception("defense-in-depth 재실행 실패")
        # 재시도 피드백에 실제 DB 에러 첫 줄을 실어 agent 가 무엇을 고칠지 알게 한다
        # (예: syntax error at or near "UNION"). 이 문구는 재시도 질문·로그로만 가고 사용자엔 노출 안 됨.
        detail = (str(e).splitlines() or ["알 수 없는 오류"])[0][:300]
        raise _RetryableError(f"쿼리 실행 중 오류가 발생했습니다 — {detail}")

    if not row_lists:
        raise _TerminalError("조건에 맞는 결과가 없습니다.")

    try:
        validate_result([dict(zip(columns, row)) for row in row_lists])
    except ResultValidationError as e:
        raise _RetryableError(e.message)

    return {**answer, "sql": safe_sql, "table": {"columns": columns, "rows": row_lists}}


def _handle_frame(frame: str):
    """agent 가 보낸 SSE 프레임 한 개(개행 2개로 구분된 단위)를 처리한다.

    "data: <json>" 형식이 아니면 None. event=="done"이 아니면 그대로 relay할
    ("frame", bytes)를 돌려준다. event=="done"이면 재검증까지 수행해서
    ("done", bytes) / ("terminal", bytes) / ("retry", 실패사유문자열) 중 하나를
    돌려준다 — 셋 다 해당 attempt의 스트림을 끝내야 함을 뜻한다.
    """
    stripped = frame.strip()
    if not stripped.startswith("data:"):
        return None
    raw = stripped[len("data:"):].strip()
    try:
        outer = json.loads(raw)
    except (TypeError, ValueError):
        return ("terminal", _sse_error(_GENERIC_ERROR))

    if outer.get("event") != "done":
        return ("frame", (frame + "\n\n").encode("utf-8"))

    try:
        verified = _revalidate(outer.get("data", ""))
    except _TerminalError as e:
        return ("terminal", _sse_error(e.message))
    except _RetryableError as e:
        return ("retry", e.message)
    return ("done", _done_frame(verified))


async def _run_attempt(client: httpx.AsyncClient, question: str, session_id: str):
    """agent 스트림을 한 번 열어서 relay하다가, done 프레임을 만나면 재검증까지 수행한다.

    진행 상황 프레임은 ("frame", bytes)로 계속 내보내고, done에 도달하면
    ("done"|"terminal", bytes) 또는 ("retry", 실패사유)를 마지막으로 하나 내보낸
    뒤 이 attempt를 끝낸다(agent가 done 없이 스트림을 끝내면 아무 결과도 없이 끝남).
    """
    buffer = ""
    async with client.stream(
        "POST",
        "/api/v1/query/stream",
        json={"question": question, "session_id": session_id},
    ) as resp:
        resp.raise_for_status()
        async for chunk in resp.aiter_text():
            buffer += chunk
            while "\n\n" in buffer:
                frame, buffer = buffer.split("\n\n", 1)
                result = _handle_frame(frame)
                if result is None:
                    continue
                yield result
                if result[0] in ("done", "terminal", "retry"):
                    return
    if buffer.strip():
        result = _handle_frame(buffer)
        if result is not None:
            yield result


@router.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest):
    """agent 의 SSE 스트림을 이벤트 단위로 파싱해서 relay(done만 재검증).

    재검증에서 guardrail/DB 재실행/결과검증이 실패하면(_RetryableError), 사용자에게
    바로 보여주지 않고 실패 사유를 질문에 자연어로 덧붙여 agent를 최대 _MAX_RETRIES회
    다시 호출한다. 파싱 실패·결과 없음(_TerminalError)이나 agent 연결 자체 실패는
    재시도 없이 바로 error로 마감한다.
    """

    async def relay():
        previous_failure: str | None = None
        try:
            async with httpx.AsyncClient(base_url=settings.AI_AGENT_BASE_URL, timeout=_STREAM_TIMEOUT) as client:
                for attempt in range(_MAX_RETRIES + 1):
                    question = _build_retry_question(req.question, previous_failure)
                    if attempt > 0:
                        yield _sse_status(f"이전 시도가 실패해서 다시 생성하는 중… ({attempt}/{_MAX_RETRIES})")

                    outcome = None
                    async for kind, payload in _run_attempt(client, question, req.session_id):
                        if kind == "frame":
                            yield payload
                        else:
                            outcome = (kind, payload)

                    if outcome is None:
                        # agent가 done도 error도 없이 스트림을 끝낸 이례적 케이스
                        yield _sse_error(_GENERIC_ERROR)
                        return

                    kind, payload = outcome
                    if kind in ("done", "terminal"):
                        yield payload
                        return

                    # kind == "retry" — 실패 사유를 다음 attempt의 질문에 실어 재시도
                    previous_failure = payload
                    if attempt == _MAX_RETRIES:
                        # 사용자에게는 guardrail 원문 대신 사용자 친화적 문구만 보여주고,
                        # 실제 실패 사유는 로그로만 남긴다(디버깅/Langfuse 교차 확인용).
                        logger.info(
                            "재시도 %d회 소진 — 마지막 실패 사유: %s", _MAX_RETRIES + 1, previous_failure
                        )
                        yield _sse_error(_VALIDATION_FAILED_ERROR)
                        return
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

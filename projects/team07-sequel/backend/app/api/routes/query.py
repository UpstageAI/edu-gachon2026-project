"""POST /api/query — 프론트엔드가 호출하는 유일한 진입점.

응답은 SSE(Server-Sent Events)로 스트리밍되며, 이벤트는 다음 순서로 흐른다.

    status (쿼리 생성 중) -> status (안전성 확인 중) -> status (실행 중)
        -> result (표 + 요약 + 추천 후속 질문) -> sql (원문, 투명성 제공) -> done

실패 시 위 순서 어디서든 error 이벤트가 오고 스트림이 종료된다.
"""

import json
from collections.abc import AsyncGenerator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.db.database import run_readonly_query
from app.schemas.query import ErrorCode, QueryRequest, SSEEvent
from app.services.agent_client import ask_ai_agent, fetch_suggestions
from app.services.guardrail import GuardrailError, validate_sql
from app.services.result_validator import ResultValidationError, validate_result

router = APIRouter()


def _sse(event: str, data: dict) -> str:
    """dict를 SSE(text/event-stream) 프레임 형식의 문자열로 감싼다.

    형식: "event: <타입>\\ndata: <JSON>\\n\\n" — 프론트엔드의
    queryStream.js가 이 정확한 형식을 기준으로 파싱하므로 형식을 바꾸면
    프론트도 같이 수정해야 한다.
    """
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _query_stream(req: QueryRequest) -> AsyncGenerator[str, None]:
    """실제 요청 처리 파이프라인. 각 단계마다 SSE 이벤트를 하나씩 내보낸다."""
    try:
        yield _sse(SSEEvent.STATUS, {"message": "쿼리를 생성하는 중…"})

        # 1) AI agent에게 SQL 생성을 요청한다. session_id를 그대로 넘기면
        #    agent가 자기 쪽 히스토리(성공한 턴만 최근 5개)를 참고해서
        #    후속 질문 맥락("그 중에 1위만" 등)을 반영한 SQL을 만든다.
        try:
            agent_result = await ask_ai_agent(req.question, req.session_id)
        except Exception:
            yield _sse(
                SSEEvent.ERROR,
                {"code": ErrorCode.INTERNAL_ERROR, "message": "AI agent 호출 중 오류가 발생했습니다."},
            )
            return

        # 2) AI agent가 만든 SQL을 백엔드 자체 가드레일로 한 번 더 검증한다.
        #    (SELECT 외 쿼리 차단, LIMIT 자동 추가) — 신뢰성 문제 대응.
        yield _sse(SSEEvent.STATUS, {"message": "안전성을 확인하는 중…"})
        try:
            safe_sql = validate_sql(agent_result.sql)
        except GuardrailError as e:
            yield _sse(SSEEvent.ERROR, {"code": ErrorCode.VALIDATION_FAILED, "message": e.message})
            return

        # 3) 검증을 통과한 SQL만 text2sql_reader(읽기 전용) 계정으로 실행한다.
        yield _sse(SSEEvent.STATUS, {"message": "쿼리를 실행하는 중…"})
        try:
            rows = run_readonly_query(safe_sql)
        except Exception:
            yield _sse(
                SSEEvent.ERROR,
                {
                    "code": ErrorCode.INTERNAL_ERROR,
                    "message": "쿼리 실행 중 오류가 발생했습니다. SQL 문법이나 컬럼/테이블명을 확인해주세요.",
                },
            )
            return

        if not rows:
            yield _sse(
                SSEEvent.ERROR,
                {"code": ErrorCode.NO_RESULT, "message": "조건에 맞는 결과가 없습니다."},
            )
            return

        # 3-1) 실행된 결과 자체의 스키마/타입/행 수가 정상적인지 한 번 더 확인한다.
        #      guardrail이 "SQL이 안전한가"를 봤다면, 여기는 "결과가 타당한가"를 본다.
        try:
            validate_result(rows)
        except ResultValidationError as e:
            yield _sse(SSEEvent.ERROR, {"code": ErrorCode.RESULT_VALIDATION_FAILED, "message": e.message})
            return

        # 4) 성공했으니, agent에게 방금 이 턴을 바탕으로 한 추천 후속 질문을
        #    별도로 물어본다. agent가 session_id로 자기 히스토리에서 방금 저장된
        #    성공 턴을 읽어 추천을 만드는 구조라, 반드시 /query 성공 "직후"에만
        #    호출 의미가 있다. 이 호출이 실패해도(네트워크 등) 추천 질문은
        #    부가 기능이라 전체 요청을 실패시키지 않고 빈 배열로 처리한다.
        try:
            suggestions = await fetch_suggestions(req.session_id)
        except Exception:
            suggestions = []

        # 5) 결과(표+요약+추천 후속 질문)를 먼저 보내고, SQL 원문은 별도 이벤트로
        #    나중에 보낸다. 프론트엔드는 sql 이벤트를 "SQL 보기" 토글에만 사용하고
        #    기본으로는 숨긴다.
        yield _sse(
            SSEEvent.RESULT,
            {"table": rows, "summary": agent_result.summary, "suggestions": suggestions},
        )
        yield _sse(SSEEvent.SQL, {"sql": safe_sql})
        yield _sse(SSEEvent.DONE, {})

    except Exception:
        # 위 단계들에서 예상하지 못한 예외가 나도 스트림이 그냥 끊기지 않고
        # 반드시 error 이벤트로 마무리되도록 하는 최종 방어선.
        yield _sse(
            SSEEvent.ERROR,
            {"code": ErrorCode.INTERNAL_ERROR, "message": "예상치 못한 오류가 발생했습니다."},
        )


@router.post("/api/query")
async def query(req: QueryRequest) -> StreamingResponse:
    """프론트엔드가 호출하는 유일한 엔드포인트. 응답은 SSE 스트림이다."""
    return StreamingResponse(_query_stream(req), media_type="text/event-stream")

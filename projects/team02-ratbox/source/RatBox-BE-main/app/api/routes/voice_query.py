import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.agent.voice_graph import run_voice_query
from app.api.schemas.request import VoiceQueryRequest

router = APIRouter(prefix="/cooking", tags=["voice-query"])

_CHUNK_SIZE = 4
_CHUNK_DELAY_SECONDS = 0.03


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _stream_answer(answer: str) -> AsyncIterator[str]:
    if not answer:
        yield _sse_event({"answer": ""})
    else:
        for end in range(_CHUNK_SIZE, len(answer) + _CHUNK_SIZE, _CHUNK_SIZE):
            yield _sse_event({"answer": answer[:end]})
            await asyncio.sleep(_CHUNK_DELAY_SECONDS)
    yield "event: done\ndata: {}\n\n"


_KEEPALIVE_INTERVAL_SECONDS = 10


async def _run_and_stream(payload: VoiceQueryRequest) -> AsyncIterator[str]:
    task = asyncio.ensure_future(
        run_in_threadpool(
            run_voice_query,
            recipe_id=payload.recipe_id,
            allergen_ids=payload.allergen_ids,
            question=payload.question,
            current_step_text=payload.current_step_text,
        )
    )
    # 대체재 질문은 react_agent<->tool_node 루프에서 LLM을 여러 번 호출해 응답을
    # 완성하기까지 로드밸런서 백엔드 타임아웃(기본 30초)을 넘기기 쉽다. 완성된
    # 답변이 나올 때까지 아무 바이트도 보내지 않으면 GFE가 "upstream request
    # timeout"으로 끊어버리므로, 대기 중에도 SSE 주석 라인을 흘려보내 연결을 살려둔다.
    while not task.done():
        yield ": keep-alive\n\n"
        await asyncio.wait({task}, timeout=_KEEPALIVE_INTERVAL_SECONDS)

    state = await task
    async for chunk in _stream_answer(state.final_answer or ""):
        yield chunk


@router.post("/voice-query")
async def voice_query(payload: VoiceQueryRequest) -> StreamingResponse:
    """조리 중 음성 질의 응답을 SSE로 실시간 전송한다.

    LangGraph invoke 자체는 동기 호출이라 스레드풀에서 돌려 이벤트 루프를 막지 않고,
    완성된 답변을 청크 단위로 흘려보내 프론트가 실시간으로 받는 것처럼 렌더링하게 한다.
    """
    return StreamingResponse(
        _run_and_stream(payload),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

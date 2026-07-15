"""
backend/routers/chat.py
추천 엔드포인트.
- POST /api/v1/chat/sync : 한 번에 응답 (테스트·디버깅용)
- POST /api/v1/chat      : SSE 스트리밍 (실제 사용자용)

backend는 '정문', app은 '주방'. 여기서는 run_agent를 호출해 결과를
API 응답(ChatResponse)으로만 정리한다. 추천 로직 자체는 app에 있다.
"""

import asyncio
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.graph import stream_agent
from app.agents.meal_agent import run_agent
from app.schemas import AgentState, UserProfile
from app.services.condition_extractor import extract_conditions_llm
from app.services.intent_router import classify_intent_llm
from backend.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api/v1", tags=["chat"])


def _to_response(state: AgentState) -> ChatResponse:
    """run_agent가 돌려준 AgentState를 프론트가 쓰기 좋은 형태로 평평하게 변환.

    검증에 최종 실패(FAIL)한 식단은 사용자에게 카드로 노출하지 않는다.
    (기획 원칙: FAIL 식단 대신 정직한 안내 문구만 보여준다. 알레르기 유발 음식이
    화면에 뜨는 것도 이 지점에서 함께 차단된다.)
    """
    mp = state.meal_plan
    vr = state.validation_result
    failed = vr is not None and vr.status == "FAIL"
    show_meal = mp is not None and not failed
    return ChatResponse(
        intent=state.intent,
        meal_type=mp.meal_type if show_meal else None,
        items=mp.items if show_meal else [],
        nutrition=state.nutrition_total if show_meal else None,
        reason=mp.reason if show_meal else "",
        status=vr.status if vr else None,
        warnings=vr.warnings if vr else [],
        final_response=state.final_response,
        retry_count=state.retry_count,
    )


def _run(req: ChatRequest) -> AgentState:
    """공용 실행부. LLM 의도분류·조건추출(각각 실패 시 stub 폴백)을 주입해 돌린다."""
    profile = req.profile or UserProfile()
    return run_agent(
        req.message,
        profile=profile,
        extractor=extract_conditions_llm,
        classifier=classify_intent_llm,
        thread_id=req.thread_id,  # 있으면 멀티턴(되묻기→이어받기), 없으면 무상태
    )


@router.post("/chat/sync", response_model=ChatResponse)
def chat_sync(req: ChatRequest) -> ChatResponse:
    """한 번에 추천 결과를 돌려준다. 요청→추천 전체가 API로 도는지 확인하는 경로."""
    state = _run(req)
    return _to_response(state)


def _sse(event: str, data: dict) -> str:
    """SSE 한 프레임 포맷. 프론트는 event 타입으로 단계를 구분한다."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat")
async def chat_stream(req: ChatRequest) -> StreamingResponse:
    """
    SSE 스트리밍. LangGraph 파이프라인의 '각 단계'를 실시간으로 흘려보낸다.
      - status(progress): "건강 조건을 분석하고 있어요…" 등 단계별 진행 문구
      - result: 최종 추천 payload
      - error: 예외 시 안내 후 스트림 종료
    stream_agent는 동기(블로킹) 제너레이터라, 이벤트 루프를 막지 않게
    별도 스레드에서 돌리고 asyncio.Queue로 프레임을 건네받는다.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    _DONE = object()

    def produce() -> None:
        """워커 스레드: 그래프를 스트리밍하며 각 이벤트를 큐로 넘긴다."""
        try:
            profile = req.profile or UserProfile()
            final_state = None
            for kind, value in stream_agent(
                req.message,
                profile=profile,
                extractor=extract_conditions_llm,
                classifier=classify_intent_llm,
                thread_id=req.thread_id,
            ):
                if kind == "progress":
                    loop.call_soon_threadsafe(
                        queue.put_nowait, _sse("status", {"stage": "progress", "message": value})
                    )
                elif kind == "result":
                    final_state = value
            payload = _to_response(final_state).model_dump()
            loop.call_soon_threadsafe(queue.put_nowait, _sse("result", payload))
        except Exception as e:  # LLM 타임아웃 등 예기치 못한 실패
            loop.call_soon_threadsafe(
                queue.put_nowait, _sse("error", {"message": f"추천 중 오류가 발생했어요: {e}"})
            )
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _DONE)

    async def event_gen():
        yield _sse("status", {"stage": "start", "message": "요청을 받았어요…"})
        loop.run_in_executor(None, produce)
        while True:
            frame = await queue.get()
            if frame is _DONE:
                break
            yield frame

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

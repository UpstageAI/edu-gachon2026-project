from __future__ import annotations

import json

from fastapi import APIRouter
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from app.core.tracing import get_trace_callbacks
from app.graph import compiled_graph
from app.tools.price_cache import ping as db_ping

router = APIRouter()

# 그래프 노드 완료 직후 다음 단계를 안내하는 상태 메시지
# (checklist 6번 SSE 이벤트 구조 참고: 의도 분류 중 → 가격 조회 중 → 판정 중 → result → done)
_NEXT_STEP_STATUS = {
    "router": "가격 조회 중...",
    "get_raw_price": "판정 중...",
}

# LLM이 실제로 답변을 생성하는 노드 — 이 노드에서 나오는 토큰만 실시간으로 흘려보냄
# (router의 구조화 출력 호출도 LLM 토큰을 만들지만 그건 사용자에게 보여줄 답변이 아님)
_STREAMING_ANSWER_NODES = {"generate_answer"}


class ChatRequest(BaseModel):
    query: str
    region: str | None = None
    unit: str | None = None


def _sse(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}


@router.post("/chat")
async def chat(request: ChatRequest):
    async def event_generator():
        yield _sse("status", {"step": "의도 분류 중..."})

        state: dict = {
            "user_query": request.query,
            "region": request.region,
            "unit": request.unit,}
        print(f"[/chat] ChatRequest 수신: query={state['user_query']}, region={state['region']}, unit={state['unit']}")
        try:
            async for mode, payload in compiled_graph.astream(
                state,
                stream_mode=["updates", "messages"],
                # [2026-07-14] Langfuse 트레이싱(선택 가점) — 실제 /chat 트래픽만 추적.
                # get_trace_callbacks()는 langfuse 미설치·키 미설정 시 빈 리스트를 반환해
                # 기존 동작에 영향 없음(pytest의 compiled_graph.ainvoke() 직접 호출 경로는
                # 이 config를 거치지 않으므로 트레이싱 대상이 아님).
                config={
                    "callbacks": get_trace_callbacks(),
                    "run_name": "food-compass-chat",
                    "metadata": {"langfuse_tags": ["chat"]},
                },
            ):
                if mode == "messages":
                    message_chunk, metadata = payload
                    if metadata.get("langgraph_node") in _STREAMING_ANSWER_NODES and message_chunk.content:
                        yield _sse("token", {"delta": message_chunk.content})
                    continue

                # mode == "updates": 노드 하나가 완료될 때마다 전체 상태(state)를 갱신
                for node_name, node_output in payload.items():
                    # [2026-07-14 근본 원인 수정] resolve_processed_items_node처럼 상태를
                    # 바꾸지 않는(빈 dict `{}` 반환) 노드의 출력을, LangGraph가 이 스트리밍
                    # payload에서 `None`으로 표현하는 경우가 있음(재현 확인함) —
                    # state.update(None)은 "TypeError: 'NoneType' object is not iterable"을
                    # 던져서 SSE 스트림 전체가 죽었었음. 실제로 원물 1개만 조회하는(시나리오 1의
                    # 2품목 비교가 아닌) 흔한 경로마다 이 노드가 항상 빈 dict를 반환해서 자주
                    # 터졌던 것 — "상추 지금 비싸?"는 실패하고 "쌀 vs 즉석밥"은 성공했던 이유.
                    if node_output:
                        state.update(node_output)
                    print(f"[Graph] 노드 실행: {node_name} (route={state.get('route')})")
                    if node_name == "router" and state.get("route") != "price":
                        continue
                    next_status = _NEXT_STEP_STATUS.get(node_name)
                    if next_status:
                        yield _sse("status", {"step": next_status})
        except Exception as e:
            # [2026-07-14 추가] 여기 try/except가 없어서 그래프 실행 중 예외(예: Supabase
            # 일시적 연결 장애)가 나면 SSE 스트림이 완료 이벤트 없이 그대로 끊겼음 — 프론트
            # 엔드(httpx.stream)에서는 이게 "peer closed connection without sending complete
            # message body"(RemoteProtocolError)로 보임. 어떤 노드에서 실패하든 항상
            # result+done 이벤트로 스트림을 정상 종료시켜서 이 문제를 방지.
            print(f"[/chat] 그래프 실행 중 오류: {e!r}")
            yield _sse("result", {"answer": "죄송해요, 일시적인 오류로 답변을 만들지 못했어요. 잠시 후 다시 시도해주세요."})
            yield _sse("done", {})
            return

        yield _sse("result", {"answer": state.get("answer", "")})
        yield _sse("done", {})

    return EventSourceResponse(event_generator())


@router.get("/health")
async def health():
    db_status = "connected" if db_ping() else "disconnected"
    return {"status": "ok", "db": db_status}

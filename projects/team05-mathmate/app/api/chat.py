"""튜터 대화 엔드포인트 (SSE 스트리밍)."""
from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
from app.schemas.chat import ChatRequest
from app.service.tutor_service import handle_turn

router = APIRouter()


@router.post("/chat")
async def chat(req: ChatRequest):
    async def event_generator():
        async for chunk in handle_turn(req):
            yield {"data": chunk}
    return EventSourceResponse(event_generator())

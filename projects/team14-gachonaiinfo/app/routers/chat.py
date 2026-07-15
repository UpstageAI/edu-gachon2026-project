"""/api/chat — LangGraph 에이전트 (router → rag/tool → response).

체크포인터(session_id=thread_id별 대화 상태 영속) 도입 이후로는 매 요청마다
새 초기 상태를 만들지 않고, 새 사용자 메시지만 그래프에 넘긴다. 이전 턴의
상태는 체크포인터가 자동으로 복원해 병합한다.

/chat/stream은 컴파일된 그래프를 astream_events로 실행해, 그래프 실행(라우팅
·검색·도구 실행)은 정상적으로 체크포인터와 맞물리게 하면서도 response 노드의
LLM 호출만 토큰 단위로 프론트에 전달한다(response_node 자체는 llm.ainvoke를
쓰는 일반 호출이지만, astream_events로 감싸 실행하면 LangChain이 자동으로
스트리밍 이벤트를 방출한다 — 별도의 수동 스트리밍 클라이언트 호출이 필요 없음).
"""

import json
import logging

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

from app import config
from app.graph.graph import get_graph
from app.observability import build_run_config, trace_context

router = APIRouter(prefix="/api", tags=["chat"])
logger = logging.getLogger("app.rag")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


def _rag_sources(docs: list[dict]) -> list[dict]:
    """검색 문서를 출처별로 묶어 프론트가 쓰는 {source, page, score} 형태로."""
    best: dict[str, dict] = {}
    for d in docs:
        src = d.get("source") or "출처 없음"
        score = d.get("score", 0)
        if src not in best or score > best[src]["score"]:
            best[src] = {
                "source": src,
                "page": d.get("page"),
                "score": round(float(score), 3),
            }
    return sorted(best.values(), key=lambda s: s["score"], reverse=True)


def _contact_sources(contact: dict | None) -> list[dict]:
    """가드레일 안내의 문의처/링크를 프론트 sources({source}) 형태로."""
    if not contact:
        return []
    srcs: list[dict] = []
    if contact.get("matched"):
        phone = (contact.get("담당") or {}).get("전화") or contact.get("대표전화")
        label = contact["부서"] + (f" ☎ {phone}" if phone else "")
        srcs.append({"source": label})
    for link in contact.get("링크", []):
        srcs.append({"source": f"{link['이름']} ({link['URL']})"})
    return srcs


def _build_meta(acc: dict) -> dict:
    """router/rag/tool 노드가 채운 상태(acc)로부터 프론트용 meta를 구성."""
    intent = acc.get("intent")
    sources: list[dict] = []
    response_type = "chat_answer"
    contact = acc.get("contact")

    if intent == "rag" and acc.get("guardrail"):
        response_type = "guardrail"
        sources = _contact_sources(contact)
    elif intent == "rag":
        sources = _rag_sources(acc.get("retrieved_docs") or [])
        response_type = "rag_llm_answer"
    elif intent == "tool":
        tr = acc.get("tool_result") or {}
        data = tr.get("data") if isinstance(tr, dict) else None
        if isinstance(data, dict) and data.get("출처"):
            # page/score는 생략 → 프론트에서 undefined로 처리되어 표기 안 됨
            sources = [{"source": data["출처"]}]
        response_type = "tool_answer"

    elif intent == "reminder":
        # 리마인드 확인/안내 메시지(출처 없음)
        response_type = "reminder_answer"

    elif intent == "ask_year":
        # 학번 되묻기 메시지(출처 없음)
        response_type = "ask_year_answer"

    return {
        "type": response_type,
        "intent": intent,
        "tool_name": acc.get("tool_name"),
        "sources": sources,
        "contact": contact,
    }


@router.post("/chat")
async def chat(req: ChatRequest):
    graph = get_graph()
    thread_id = req.session_id or "default"
    run_config = build_run_config(thread_id, "chat")

    with trace_context(
        trace_name="gachon-ai-chat",
        session_id=thread_id,
        tags=["gachon-ai", "langgraph", config.LANGFUSE_ENV],
        metadata={
            "endpoint": "/api/chat",
            "project": "gachon-ai-agent",
            "environment": config.LANGFUSE_ENV,
        },
    ):
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content=req.message)], "session_id": thread_id},
            config=run_config,
        )

    answer = result["messages"][-1].content
    return {"answer": answer, **_build_meta(result)}


def sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    thread_id = req.session_id or "default"
    run_config = build_run_config(thread_id, "chat-stream")

    async def event_generator():
        yield sse_event("status", {"message": "질문을 분석하는 중이에요."})

        graph = get_graph()
        acc: dict = {}
        meta_sent = False
        answer_parts: list[str] = []
        # reminder 노드는 response(LLM 스트리밍)를 거치지 않고 답을 직접 만든다.
        # 그 최종 메시지를 담아 두었다가 루프 종료 후 한 번에 흘려보낸다.
        direct_text: str | None = None

        try:
            # Langfuse trace context는 반드시 astream_events 루프를 감싸야 한다.
            # (generator 바깥/StreamingResponse에 두면 실제 그래프 실행 시점엔
            #  context가 이미 닫혀 trace 속성이 붙지 않는다.)
            with trace_context(
                trace_name="gachon-ai-chat-stream",
                session_id=thread_id,
                tags=["gachon-ai", "langgraph", "rag", config.LANGFUSE_ENV],
                metadata={
                    "endpoint": "/api/chat/stream",
                    "project": "gachon-ai-agent",
                    "environment": config.LANGFUSE_ENV,
                },
            ):
                async for ev in graph.astream_events(
                    {"messages": [HumanMessage(content=req.message)], "session_id": thread_id},
                    config=run_config,
                    version="v2",
                ):
                    kind = ev["event"]
                    node = ev.get("metadata", {}).get("langgraph_node")

                    # router/rag/tool/reminder/ask_year 노드가 반환한 부분 상태를 누적 (meta 구성용)
                    if kind == "on_chain_end" and node in (
                        "router",
                        "rag",
                        "tool",
                        "reminder",
                        "ask_year",
                    ):
                        output = ev["data"].get("output")
                        if isinstance(output, dict):
                            acc.update(output)
                            # reminder처럼 LLM 스트리밍 없이 노드가 직접 만든 최종 메시지 포착
                            msgs = output.get("messages")
                            if msgs and getattr(msgs[-1], "content", None):
                                direct_text = msgs[-1].content

                    # response 노드의 LLM 호출만 토큰 단위로 프론트에 전달
                    if kind == "on_chat_model_stream" and node == "response":
                        if not meta_sent:
                            yield sse_event("meta", _build_meta(acc))
                            meta_sent = True
                        token = ev["data"]["chunk"].content
                        if token:
                            answer_parts.append(token)
                            yield sse_event("delta", {"text": token})

            if not meta_sent:
                yield sse_event("meta", _build_meta(acc))
                meta_sent = True

            # LLM 토큰이 하나도 안 흐른 경우(예: reminder 노드) 최종 메시지를 delta로 전달
            if not answer_parts and direct_text:
                answer_parts.append(direct_text)
                yield sse_event("delta", {"text": direct_text})

            yield sse_event("done", {"message": "complete"})

        except Exception as e:
            yield sse_event(
                "error",
                {"message": f"스트리밍 중 오류가 발생했습니다: {str(e)}"},
            )
        finally:
            logger.info(
                json.dumps(
                    {
                        "stage": "response",
                        "session_id": thread_id,
                        "question": req.message,
                        "intent": acc.get("intent"),
                        "guardrail": acc.get("guardrail"),
                        "tool_name": acc.get("tool_name"),
                        "answer": "".join(answer_parts),
                    },
                    ensure_ascii=False,
                )
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

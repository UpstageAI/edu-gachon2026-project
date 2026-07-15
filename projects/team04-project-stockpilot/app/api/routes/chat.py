"""채팅 라우트 — /chat(단건), /chat/stream(SSE 스트리밍)."""
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage
from loguru import logger

from app.agents.react_agent import run_react_agent, stream_react_agent
from app.core.guardrails import GuardrailViolation, ensure_safe_user_input
from app.graph.graph import get_stockpilot_graph
from app.graph.nodes import fetch_screener_panel
from app.core.observability import langfuse_config
from app.graph.state import create_initial_state
from app.repositories.glossary import find_terms_in_text, list_all_terms
from app.schemas.chat import ChatRequest, ChatResponse, StreamEvent

router = APIRouter()

# 노드 -> 사용자에게 보여줄 진행 상태 문구
_THINKING_MESSAGE = {
    "router": "질문 의도를 파악하고 있어요...",
    "rag": "관련 문서를 찾고 있어요...",
    "tool": "시세·뉴스를 수집하고 있어요...",
    "disclosure": "최근 공시를 조회하고 있어요...",
}


def _thinking_content(node_name: str, node_output: dict) -> str:
    """Return a user-facing progress message for a completed graph node."""

    if node_name == "router":
        intent = node_output.get("intent")
        if intent == "tool":
            if node_output.get("tool_mode") == "disclosure":
                return _THINKING_MESSAGE["disclosure"]
            return _THINKING_MESSAGE["tool"]
        if intent == "rag":
            return _THINKING_MESSAGE["rag"]
        return "답변을 준비하고 있어요..."
    if node_name == "tool" and node_output.get("tool_mode") == "disclosure":
        return _THINKING_MESSAGE["disclosure"]
    return _THINKING_MESSAGE[node_name]


def _build_state(request: ChatRequest) -> dict:
    """요청으로부터 그래프 초기 상태를 만들고 사용자 메시지를 넣는다."""
    ensure_safe_user_input(request.message)
    state = create_initial_state(request.session_id, request.user_id, model=request.model)
    state["messages"] = [HumanMessage(content=request.message)]
    return state


def _one_stock_payload(
    price: dict | None,
    news: list,
    disclosures: list,
    disclosure_error: str | None = None,
) -> dict:
    """단일 종목의 시세·뉴스·공시를 프론트 패널 형태로 정리한다."""
    price = price or {}
    fundamentals = price.get("fundamentals") or None
    return {
        "price": (
            {
                "name": price.get("name"),
                "ticker": price.get("ticker"),
                "change_pct": price.get("change_pct"),
                "current_price": price.get("current_price"),
                "as_of": price.get("as_of"),
                "snapshot_at": price.get("snapshot_at"),
                "period": price.get("period"),
                # 차트용 일봉 시계열 (date, open, high, low, close, volume, change_pct)
                "ohlcv": price.get("ohlcv") or [],
                # 좌측 패널 하단 재무지표 카드용 (PER/PBR/EPS/BPS/DIV/DPS)
                "fundamentals": fundamentals,
            }
            if price
            else None
        ),
        "news": [
            {
                "title": item.get("title"),
                "url": item.get("original_link") or item.get("link"),
                "source": item.get("source_domain"),
                "session": item.get("market_session"),
            }
            for item in (news or [])[:5]
        ],
        # 좌측 패널 하단 "공시정보" 카드용 (4번째 도구: get_disclosure)
        "disclosures": [
            {
                "title": d.get("report_name") or d.get("title"),
                "url": d.get("source_url") or d.get("url"),
                "date": d.get("received_date") or d.get("date"),
                "corp": d.get("corp_name"),
            }
            for d in (disclosures or [])[:8]
        ],
        "disclosure_error": disclosure_error,
    }


def _tool_payload(node_output: dict) -> dict:
    """tool 노드 결과에서 프론트가 쓸 시세·뉴스·공시 요약을 추린다."""
    payload = _one_stock_payload(
        node_output.get("price_data"),
        node_output.get("news_items") or [],
        node_output.get("disclosures") or [],
        node_output.get("disclosure_error"),
    )
    payload["panel_update"] = node_output.get("panel_update", True)
    payload["is_followup"] = bool(node_output.get("is_followup"))
    if node_output.get("direction_notice"):
        payload["direction_notice"] = node_output["direction_notice"]
    # 급등 스크리너: 상위 종목별 패널을 순서대로 함께 내보낸다(가운데 스택용).
    panels = node_output.get("screener_panels") or []
    if panels:
        payload["stocks"] = [
            _one_stock_payload(
                p.get("price"),
                p.get("news") or [],
                p.get("disclosures") or [],
                p.get("disclosure_error"),
            )
            for p in panels
        ]
    return payload


async def _match_glossary_terms(answer_text: str) -> list[dict]:
    """답변 텍스트에서 사전에 등록된 투자 용어를 찾는다. 실패해도 응답 자체는 막지 않는다."""
    if not answer_text.strip():
        return []
    try:
        terms = await list_all_terms()
        return find_terms_in_text(answer_text, terms)
    except Exception:
        logger.warning("용어 매칭 실패 — 밑줄 각주 없이 진행")
        return []


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """단건(비스트리밍) 응답. 그래프를 끝까지 실행해 최종 답변을 반환한다."""
    if request.agent_mode == "react":
        try:
            ensure_safe_user_input(request.message)
            result = await run_react_agent(
                message=request.message,
                session_id=request.session_id,
                model_id=request.model,
            )
        except GuardrailViolation as exc:
            raise HTTPException(status_code=400, detail=exc.decision.safe_message)
        except Exception:
            logger.exception(f"ReAct chat failed: session={request.session_id}")
            raise HTTPException(
                status_code=500,
                detail="답변을 생성하는 중 문제가 발생했어요. 잠시 후 다시 시도해주세요.",
            )
        return ChatResponse(message=result.answer, tool_used=result.tool_used)

    graph = get_stockpilot_graph()
    try:
        result = await graph.ainvoke(
            _build_state(request),
            config=langfuse_config(request.session_id, request.user_id),
        )
    except GuardrailViolation as exc:
        raise HTTPException(status_code=400, detail=exc.decision.safe_message)
    except Exception:
        logger.exception(f"채팅 처리 실패: session={request.session_id}")
        raise HTTPException(
            status_code=500,
            detail="응답을 생성하는 중 문제가 발생했어요. 잠시 후 다시 시도해주세요.",
        )
    messages = result.get("messages") or []
    answer = messages[-1].content if messages else "응답을 생성하지 못했어요."
    return ChatResponse(message=answer, tool_used=result.get("tool_name"))


async def _stream_events(request: ChatRequest) -> AsyncIterator[str]:
    """그래프를 흘리며 진행상황(updates)과 Solar 토큰(messages)을 SSE로 내보낸다."""
    if request.agent_mode == "react":
        answer_text = ""
        try:
            ensure_safe_user_input(request.message)
            async for event in stream_react_agent(
                message=request.message,
                session_id=request.session_id,
                model_id=request.model,
            ):
                if event.get("type") == "response":
                    answer_text = event.get("content") or answer_text
                yield StreamEvent(**event).to_sse()

            terms = await _match_glossary_terms(answer_text)
            if terms:
                yield StreamEvent(type="glossary", node="response", terms=terms).to_sse()
            yield StreamEvent(type="done").to_sse()
        except GuardrailViolation as exc:
            logger.warning(f"Guardrail blocked ReAct request: session={request.session_id}")
            yield StreamEvent(type="error", error=exc.decision.safe_message).to_sse()
            yield StreamEvent(type="done").to_sse()
        except Exception:
            logger.exception(f"ReAct stream failed: session={request.session_id}")
            yield StreamEvent(
                type="error",
                error="답변을 생성하는 중 문제가 발생했어요. 잠시 후 다시 시도해주세요.",
            ).to_sse()
            yield StreamEvent(type="done").to_sse()
        return

    graph = get_stockpilot_graph()
    tool_used = None
    streamed_token = False
    answer_text = ""
    used_model = None
    suppress_response_tokens = False
    try:
        async for mode, chunk in graph.astream(
            _build_state(request),
            stream_mode=["updates", "messages"],
            config=langfuse_config(request.session_id, request.user_id),
        ):
            # Solar가 생성하는 토큰 조각
            if mode == "messages":
                message_chunk, metadata = chunk
                if (
                    metadata.get("langgraph_node") == "response"
                    and isinstance(message_chunk, AIMessageChunk)
                ):
                    text = message_chunk.content or ""
                    if text:
                        if suppress_response_tokens:
                            # 방향 보정 같은 후처리 필수 케이스에서는 LLM 원시 토큰이
                            # 잘못된 전제를 먼저 보여줄 수 있으므로 최종 정제 응답만 보낸다.
                            continue
                        streamed_token = True
                        answer_text += text
                        yield StreamEvent(
                            type="token",
                            node="response",
                            content=text,
                        ).to_sse()
                continue

            # 노드 완료 단위 진행상황
            for node_name, node_output in chunk.items():
                node_output = node_output or {}
                if node_name in _THINKING_MESSAGE:
                    yield StreamEvent(
                        type="thinking",
                        node=node_name,
                        content=_thinking_content(node_name, node_output),
                    ).to_sse()
                if node_name == "tool":
                    tool_used = node_output.get("tool_name")
                    if node_output.get("direction_notice"):
                        suppress_response_tokens = True
                    yield StreamEvent(
                        type="tool",
                        node="tool",
                        tool_name=tool_used,
                        tool_result=_tool_payload(node_output),
                    ).to_sse()
                    # 급등 스크리너: 종목을 하나씩 순차 조회해 완성되는 대로 개별 패널 전송
                    # (tool_node는 속도를 위해 패널을 선조회하지 않음 → 라우트에서 스트리밍)
                    for stock in (node_output.get("screener_results") or [])[:6]:
                        panel = await fetch_screener_panel(stock)
                        if not panel:
                            continue
                        yield StreamEvent(
                            type="tool",
                            node="tool",
                            tool_name="screener_panel",
                            tool_result={
                                "stocks": [
                                    _one_stock_payload(
                                        panel.get("price"),
                                        panel.get("news") or [],
                                        panel.get("disclosures") or [],
                                        panel.get("disclosure_error"),
                                    )
                                ]
                            },
                        ).to_sse()
                # 토큰 스트리밍이 안 된 경우(폴백)에만 최종 답을 한 번에 전송
                if node_name == "response":
                    used_model = node_output.get("used_model") or used_model
                    if not streamed_token:
                        messages = node_output.get("messages") or []
                        content = messages[-1].content if messages else ""
                        answer_text = content
                        yield StreamEvent(
                            type="response",
                            node="response",
                            content=content,
                            tool_used=tool_used,
                            model=used_model,
                        ).to_sse()

        # 토큰으로 흘린 경우: 완료 신호로 tool_used만 담은 response 이벤트
        if streamed_token:
            yield StreamEvent(type="response", node="response", tool_used=tool_used, model=used_model).to_sse()

        # 답변 텍스트 안에 등장하는 투자 용어를 찾아 밑줄 각주용으로 흘려보낸다.
        terms = await _match_glossary_terms(answer_text)
        if terms:
            yield StreamEvent(type="glossary", node="response", terms=terms).to_sse()

        yield StreamEvent(type="done").to_sse()
    except GuardrailViolation as exc:
        logger.warning(f"Guardrail blocked request: session={request.session_id}")
        yield StreamEvent(type="error", error=exc.decision.safe_message).to_sse()
        yield StreamEvent(type="done").to_sse()
    except Exception:
        logger.exception(f"스트리밍 처리 실패: session={request.session_id}")
        yield StreamEvent(
            type="error",
            error="응답을 생성하는 중 문제가 발생했어요. 잠시 후 다시 시도해주세요.",
        ).to_sse()
        yield StreamEvent(type="done").to_sse()


@router.post("/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """SSE 스트리밍 응답. 진행 상태와 최종 답변(토큰)을 이벤트로 흘려보낸다."""
    return StreamingResponse(
        _stream_events(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

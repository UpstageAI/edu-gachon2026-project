import json
from typing import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agents.nodes import (
    GENERATION_SYSTEM_PROMPT,
    LLM_ONLY_SYSTEM_PROMPT,
    LEGAL_NOTICE,
    RELATED_HYBRID_SYSTEM_PROMPT,
    AgentState,
    _build_generation_prompt,
    _build_llm_only_prompt,
    _build_related_hybrid_prompt,
    _format_suggested_questions,
    _official_institution_line,
    _strip_unverified_urls,
    build_source_link_line,
    fallback_response,
    guardrail_exit,
    scope_check,
)
from app.agents.workflow import prepare_routing_state, run_chat_workflow
from app.core.llm import LLMError, stream_text
from app.core.observability import (
    add_trace_attributes,
    build_route_trace_metadata,
    build_trace_metadata,
    guardrail_result_from_state,
    mask_sensitive_text,
    response_type_from_state,
    start_trace,
    trace_tags,
)
from app.core.routing import AnswerRoute
from app.schemas.chat import ChatRequest, ChatResponse


router = APIRouter(prefix="/chat", tags=["chat"])
STREAM_TRACE_NAME = "law-help-chat-stream"
STREAM_ENDPOINT = "/chat/stream"


@router.post("/sync", response_model=ChatResponse)
def chat_sync(request: ChatRequest) -> ChatResponse:
    return run_chat_workflow(
        message=request.message,
        thread_id=request.thread_id,
    )


@router.post("/stream")
def chat_stream(request: ChatRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_chat_events(request),
        media_type="text/event-stream",
    )


def _stream_chat_events(request: ChatRequest) -> Iterator[str]:
    state = _initial_state(request)

    with start_trace(
        name=STREAM_TRACE_NAME,
        input={"question": mask_sensitive_text(request.message)},
        metadata=build_trace_metadata(endpoint=STREAM_ENDPOINT, mode="stream"),
        tags=trace_tags("stream", "pending"),
    ) as trace:
        state = scope_check(state)
        if state.get("guardrail_blocked"):
            state = guardrail_exit(state)
            yield from _fixed_stream_response(trace, state)
            return

        state = prepare_routing_state(state)
        if state.get("response_type") == AnswerRoute.OUT_OF_SCOPE.value:
            yield from _fixed_stream_response(trace, state)
            return

        documents = state.get("documents", [])
        if state.get("response_type") == AnswerRoute.GROUNDED_RAG.value and not documents:
            state = fallback_response(state)
            yield from _fixed_stream_response(trace, state)
            return

        try:
            prompt, system = _stream_prompt_and_system(state)
            route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
            prefix_text = _stream_prefix_text(state)
            streamed_text = ""
            body_text = ""
            if prefix_text:
                yield _sse_event("token", {"text": prefix_text})

            if route in {AnswerRoute.RELATED_HYBRID.value, AnswerRoute.LLM_ONLY.value}:
                for text in stream_text(prompt=prompt, system=system):
                    streamed_text += text
                body_text = _clean_general_knowledge_body(streamed_text)
                if body_text:
                    yield _sse_event("token", {"text": body_text})
            else:
                for text in stream_text(prompt=prompt, system=system):
                    streamed_text += text
                    yield _sse_event("token", {"text": text})
                body_text = streamed_text

            tail_text = _stream_tail_text(state, body_text)
            if tail_text:
                yield _sse_event("token", {"text": tail_text})

            final_state = {
                **state,
                "answer": prefix_text + body_text + tail_text,
                "guardrail_blocked": False,
                "is_fallback": False,
                "retrieved_count": len(documents),
            }
            _complete_stream_trace(trace, final_state, final_state["answer"])
            yield _sse_event("metadata", _stream_metadata(final_state))
            yield _sse_event("done", {})
        except LLMError as exc:
            _fail_stream_trace(trace, state, exc)
            yield _sse_event("error", {"message": str(exc)})


def _initial_state(request: ChatRequest) -> AgentState:
    return {
        "message": request.message,
        "thread_id": request.thread_id,
        "category": "기타",
        "documents": [],
        "guardrail_blocked": False,
        "is_fallback": False,
        "retrieved_count": 0,
        "response_type": "pending",
        "suggested_questions": [],
        "sources": [],
        "is_grounded": False,
        "use_raw_search": True,
    }


def _fixed_stream_response(trace, state: AgentState) -> Iterator[str]:
    answer = state.get("answer", "")
    _complete_stream_trace(trace, state, answer)
    yield _sse_event("token", {"text": answer})
    yield _sse_event("metadata", _stream_metadata(state))
    yield _sse_event("done", {})


def _stream_prompt_and_system(state: AgentState) -> tuple[str, str]:
    route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
    message = state.get("message", "")
    documents = state.get("documents", [])

    if route == AnswerRoute.RELATED_HYBRID.value:
        return _build_related_hybrid_prompt(message, documents), RELATED_HYBRID_SYSTEM_PROMPT
    if route == AnswerRoute.LLM_ONLY.value:
        return (
            _build_llm_only_prompt(message, state.get("domain_category", "unknown")),
            LLM_ONLY_SYSTEM_PROMPT,
        )
    return _build_generation_prompt(message, documents), GENERATION_SYSTEM_PROMPT


def _stream_prefix_text(state: AgentState) -> str:
    route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
    if route in {AnswerRoute.RELATED_HYBRID.value, AnswerRoute.LLM_ONLY.value}:
        warning = state.get("warning")
        return f"{warning}\n\n" if warning else ""
    return ""


def _clean_general_knowledge_body(text: str) -> str:
    answer = _strip_unverified_urls(text).strip()
    if LEGAL_NOTICE in answer:
        answer = answer.replace(LEGAL_NOTICE, "").strip()
    return answer


def _stream_tail_text(state: AgentState, body_text: str) -> str:
    route = state.get("response_type", AnswerRoute.GROUNDED_RAG.value)
    tail_parts = []

    if route == AnswerRoute.GROUNDED_RAG.value:
        link_line = build_source_link_line(state.get("documents", []))
        if link_line:
            tail_parts.append(link_line)
        if LEGAL_NOTICE not in body_text:
            tail_parts.append(LEGAL_NOTICE)
    elif route in {AnswerRoute.RELATED_HYBRID.value, AnswerRoute.LLM_ONLY.value}:
        tail_parts.append(_official_institution_line(state.get("domain_category", "unknown")))
        suggestion_text = _format_suggested_questions(state.get("suggested_questions", []))
        if suggestion_text:
            tail_parts.append(suggestion_text)
        tail_parts.append(LEGAL_NOTICE)

    if not tail_parts:
        return ""
    return "\n\n" + "\n\n".join(tail_parts)


def _complete_stream_trace(trace, state: AgentState, answer: str) -> None:
    response_type = response_type_from_state(state)
    add_trace_attributes(
        trace_name=STREAM_TRACE_NAME,
        tags=trace_tags("stream", response_type),
    )
    trace.update(
        output={
            "response_type": response_type,
            "answer": answer,
        },
        metadata={
            **build_trace_metadata(
                endpoint=STREAM_ENDPOINT,
                mode="stream",
                guardrail_result=guardrail_result_from_state(state),
                retrieved_count=state.get("retrieved_count", 0),
                response_type=response_type,
                success=True,
            ),
            **build_route_trace_metadata(state),
        },
    )


def _stream_metadata(state: AgentState) -> dict:
    return {
        "response_type": response_type_from_state(state),
        "guardrail_result": guardrail_result_from_state(state),
        "retrieved_count": state.get("retrieved_count", 0),
        "is_grounded": state.get("is_grounded", False),
        "warning": state.get("warning"),
        "suggested_questions": state.get("suggested_questions", []),
        "sources": state.get("sources", []),
    }


def _fail_stream_trace(trace, state: AgentState, exc: LLMError) -> None:
    add_trace_attributes(
        trace_name=STREAM_TRACE_NAME,
        tags=trace_tags("stream", "error"),
    )
    trace.update(
        output={"response_type": "error"},
        metadata=build_trace_metadata(
            endpoint=STREAM_ENDPOINT,
            mode="stream",
            guardrail_result=guardrail_result_from_state(state),
            retrieved_count=state.get("retrieved_count", 0),
            response_type="error",
            success=False,
            error_type=type(exc).__name__,
        ),
        level="ERROR",
        status_message=str(exc),
    )


def _sse_event(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

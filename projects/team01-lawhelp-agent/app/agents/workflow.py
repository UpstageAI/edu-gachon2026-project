from typing import Any, Optional

from app.agents.nodes import (
    AgentState,
    decide_route,
    domain_guardrail,
    generate,
    guardrail_exit,
    output_guardrail,
    out_of_scope_response,
    retrieve,
    scope_check,
)
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
from app.schemas.chat import ChatResponse
from app.core.routing import AnswerRoute, DomainGuardrailResult


_COMPILED_WORKFLOW: Optional[Any] = None
SYNC_TRACE_NAME = "law-help-chat-sync"
SYNC_ENDPOINT = "/chat/sync"


def run_chat_workflow(message: str, thread_id: Optional[str] = None) -> ChatResponse:
    initial_state: AgentState = {
        "message": message,
        "thread_id": thread_id,
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

    with start_trace(
        name=SYNC_TRACE_NAME,
        input={"question": mask_sensitive_text(message)},
        metadata=build_trace_metadata(endpoint=SYNC_ENDPOINT, mode="sync"),
        tags=trace_tags("sync", "pending"),
    ) as trace:
        try:
            workflow = _get_compiled_workflow()
            if workflow is None:
                final_state = _run_function_chain(initial_state)
            else:
                final_state = workflow.invoke(initial_state)
        except Exception as exc:
            add_trace_attributes(
                trace_name=SYNC_TRACE_NAME,
                tags=trace_tags("sync", "error"),
            )
            trace.update(
                output={"response_type": "error"},
                metadata=build_trace_metadata(
                    endpoint=SYNC_ENDPOINT,
                    mode="sync",
                    response_type="error",
                    success=False,
                    error_type=type(exc).__name__,
                ),
                level="ERROR",
                status_message=type(exc).__name__,
            )
            raise

        response = _to_chat_response(final_state)
        response_type = response_type_from_state(final_state)
        add_trace_attributes(
            trace_name=SYNC_TRACE_NAME,
            tags=trace_tags("sync", response_type),
        )
        trace.update(
            output={
                "response_type": response_type,
                "answer": response.answer,
            },
            metadata={
                **build_trace_metadata(
                    endpoint=SYNC_ENDPOINT,
                    mode="sync",
                    guardrail_result=guardrail_result_from_state(final_state),
                    retrieved_count=final_state.get("retrieved_count", 0),
                    response_type=response_type,
                    success=True,
                ),
                **build_route_trace_metadata(final_state),
            },
        )
        return response


def _get_compiled_workflow() -> Optional[Any]:
    global _COMPILED_WORKFLOW
    if _COMPILED_WORKFLOW is not None:
        return _COMPILED_WORKFLOW

    try:
        from langgraph.graph import END, StateGraph
    except ModuleNotFoundError:
        return None

    graph = StateGraph(AgentState)
    graph.add_node("scope_check", scope_check)
    graph.add_node("guardrail_exit", guardrail_exit)
    graph.add_node("prepare_routing", prepare_routing_state)
    graph.add_node("generate", generate)
    graph.add_node("output_guardrail", output_guardrail)

    graph.set_entry_point("scope_check")
    graph.add_conditional_edges(
        "scope_check",
        _route_after_scope_check,
        {
            "blocked": "guardrail_exit",
            "passed": "prepare_routing",
        },
    )
    graph.add_conditional_edges(
        "prepare_routing",
        _route_after_decision,
        {
            "out_of_scope": END,
            "generate": "generate",
        },
    )
    graph.add_edge("generate", "output_guardrail")
    graph.add_edge("guardrail_exit", END)
    graph.add_edge("output_guardrail", END)

    _COMPILED_WORKFLOW = graph.compile()
    return _COMPILED_WORKFLOW


def _run_function_chain(state: AgentState) -> AgentState:
    state = scope_check(state)
    if state.get("guardrail_blocked"):
        return guardrail_exit(state)

    state = prepare_routing_state(state)
    if _route_after_decision(state) == "out_of_scope":
        return state

    state = generate(state)
    return output_guardrail(state)


def prepare_routing_state(state: AgentState) -> AgentState:
    state = domain_guardrail(state)
    if _route_after_domain_guardrail(state) == "out_of_scope":
        return out_of_scope_response(state)

    state = retrieve(state)
    state = decide_route(state)
    if _route_after_decision(state) == "out_of_scope":
        return out_of_scope_response(state)

    return state


def _route_after_scope_check(state: AgentState) -> str:
    return "blocked" if state.get("guardrail_blocked") else "passed"


def _route_after_domain_guardrail(state: AgentState) -> str:
    return (
        "out_of_scope"
        if state.get("domain_guardrail_result") == DomainGuardrailResult.OUT_OF_SCOPE.value
        else "search"
    )


def _route_after_decision(state: AgentState) -> str:
    return (
        "out_of_scope"
        if state.get("response_type") == AnswerRoute.OUT_OF_SCOPE.value
        else "generate"
    )


def _to_chat_response(state: AgentState) -> ChatResponse:
    return ChatResponse(
        answer=state.get("answer", ""),
        category=state.get("category", "기타"),
        guardrail_blocked=state.get("guardrail_blocked", False),
        is_fallback=state.get("is_fallback", False),
        retrieved_count=state.get("retrieved_count", 0),
        response_type=state.get("response_type", "normal"),
        warning=state.get("warning"),
        suggested_questions=state.get("suggested_questions", []),
        sources=state.get("sources", []),
        is_grounded=state.get("is_grounded", False),
        top_documents=_top_documents_from_state(state),
    )


def _top_documents_from_state(state: AgentState) -> list[dict]:
    """decide_route가 원시 검색 결과로 채운 top1~3 state 필드를 평가용으로 노출한다.

    검색이 실행되지 않은 경로(scope_check 차단, explicit_out_of_scope)는 해당
    필드가 없어 빈 리스트가 된다. uncertain_vector_fail 차단은 검색이 1회
    실행되므로 결과가 남는다 (distance 분포 수집용 — 평가 작업지시 2절).
    """
    top_documents: list[dict] = []
    for rank in (1, 2, 3):
        document_id = state.get(f"top{rank}_document_id")
        distance = state.get(f"top{rank}_distance")
        if document_id is None or distance is None:
            continue
        top_documents.append({"id": document_id, "distance": round(float(distance), 4)})
    return top_documents

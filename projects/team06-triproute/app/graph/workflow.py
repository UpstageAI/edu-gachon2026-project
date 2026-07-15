# app/graph/workflow.py

import uuid
from typing import Any, Dict, Iterator, Optional, Tuple

from langfuse import get_client, observe
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.core.state import TripRouteState
from app.graph.checkpointer import get_checkpointer
from app.graph.edges import LINEAR_EDGES
from app.graph.nodes import (
    FINALIZE_NODE,
    FINANCIAL_NODE,
    PARSE_NODE,
    ROUTE_PLANNER_NODE,
    finalize_node,
    financial_node,
    parse_node,
    route_planner_node,
)


def build_trip_route_graph(
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """
    TripRoute Agentic Workflow를 LangGraph StateGraph로 조립한다.

    parse_trip_request -> route_planner -> financial -> finalize 순서의
    선형 그래프이며, react_trace는 각 노드가 실제로 실행되며 남기는 기록이다
    (기존처럼 미리 하드코딩된 6단계 설명이 아니라 실제 그래프 실행 결과).

    checkpointer를 넘기면 매 노드 실행 직후 State 스냅샷이 자동 저장돼서(thread_id
    기준), 같은 thread_id로 이어서 실행하거나 중간에 죽어도 재개할 수 있다. None이면
    (SUPABASE_DB_URL 미설정 등) 체크포인트 없이 기존과 동일하게 매번 처음부터 실행된다.
    """
    graph: StateGraph = StateGraph(TripRouteState)

    graph.add_node(PARSE_NODE, parse_node)
    graph.add_node(ROUTE_PLANNER_NODE, route_planner_node)
    graph.add_node(FINANCIAL_NODE, financial_node)
    graph.add_node(FINALIZE_NODE, finalize_node)

    graph.add_edge(START, PARSE_NODE)
    for start, end in LINEAR_EDGES:
        graph.add_edge(start, end)
    graph.add_edge(FINALIZE_NODE, END)

    return graph.compile(checkpointer=checkpointer)


_TRIP_ROUTE_GRAPH = build_trip_route_graph(get_checkpointer())


@observe(name="trip_plan_workflow")
def run_trip_route_workflow(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Dict[str, Any]:
    """
    컴파일된 TripRoute 그래프를 실행하고 최종 응답 dict를 반환한다.

    previous_condition_summary(직전 턴의 condition_summary)를 넘기면 후속 대화
    맥락을 이어받아 파싱한다(parse_node -> parse_trip_request로 전달됨).
    previous_result(직전 턴의 전체 결과)를 함께 넘기면, 기간 연장 후속 요청에서
    route_planner_node가 기존 일정을 유지한 채 늘어난 날짜만 새로 채운다.

    thread_id(보통 대화 세션 id)는 체크포인터가 State 스냅샷을 구분해서 저장하는 단위다.
    체크포인터가 켜져 있는데(SUPABASE_DB_URL 설정됨) thread_id를 안 넘기면, 이번 호출
    한 번만을 위한 임의 thread_id를 만들어서 쓴다(LangGraph는 체크포인터가 있으면
    thread_id를 요구하므로) — 다음 턴과 이어지진 않지만 실행 자체는 문제없이 된다.

    같은 thread_id로 다음 턴을 이어서 호출할 때(대화 세션이 이어지는 경우) warnings/
    react_trace는 operator.add로 누적되는 채널이라, 새 호출에 빈 리스트를 넣어도
    체크포인터에 저장된 이전 턴 값 뒤에 이어 붙을 뿐 리셋되지 않는다. 이 함수는 매
    호출이 "새 턴"이고(재개용 invoke(None, ...) 호출은 코드베이스 어디서도 쓰지 않음)
    turn 간 이어받을 상태는 previous_condition_summary/previous_result로 호출자가
    직접 넘겨주므로, 매번 실행 전에 해당 thread의 체크포인트를 지워서 이번 턴이 항상
    빈 상태에서 시작하게 한다.

    @observe()로 이 함수 전체를 감싸서, 안쪽 4개 노드(parse/route_planner/financial/
    finalize)의 @observe() 스팬과 Solar/임베딩 호출(langfuse.openai)이 전부 "요청 하나 =
    트레이스 하나"로 같이 묶이게 한다 — 이게 없으면 각 LLM 호출이 서로 무관한 독립
    트레이스로 따로따로 찍혀서 한 사용자 요청 안에서 어디가 느린지 못 본다.
    """
    config = None
    checkpointer = get_checkpointer()
    if checkpointer is not None:
        actual_thread_id = thread_id or str(uuid.uuid4())
        checkpointer.delete_thread(actual_thread_id)
        config = {"configurable": {"thread_id": actual_thread_id}}

    final_state = _TRIP_ROUTE_GRAPH.invoke(
        {
            "user_input": user_input,
            "transport_mode": transport_mode,
            "people_count": people_count,
            "previous_condition_summary": previous_condition_summary,
            "previous_result": previous_result,
            "warnings": [],
            "react_trace": [],
        },
        config=config,
    )

    return final_state["result"]


# 노드 이름 -> 사용자에게 보여줄 진행 상황 메시지. Gradio가 이 문구를 채팅창에 실시간으로
# 표시해서, 4단계 파이프라인 중 지금 어디쯤인지 사용자가 알 수 있게 한다.
NODE_PROGRESS_MESSAGES: Dict[str, str] = {
    PARSE_NODE: "여행 조건을 분석하고 있어요...",
    ROUTE_PLANNER_NODE: "관광지와 동선을 찾고 있어요...",
    FINANCIAL_NODE: "예상 비용을 계산하고 있어요...",
    FINALIZE_NODE: "결과를 정리하고 있어요...",
}


def stream_trip_route_workflow(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Iterator[Tuple[str, Optional[Dict[str, Any]]]]:
    """
    run_trip_route_workflow와 파라미터는 동일하지만, 그래프를 한 번에 끝까지 돌리는 대신
    노드가 하나씩 끝날 때마다 (진행 메시지, 결과 or None)을 yield한다 — Gradio가 "관광지
    찾는 중...", "비용 계산 중..." 같은 단계별 상태를 실시간으로 보여줄 수 있게 하기 위함.
    마지막 노드(finalize)가 끝났을 때만 두 번째 값이 실제 결과 dict로 채워진다.

    @observe() 데코레이터는 제너레이터 함수에 그대로 쓰면 함수 본문이 실행되기 전에
    반환값(제너레이터 객체)부터 넘어가버려서 스팬이 너무 일찍 닫힐 수 있다. 대신 Langfuse
    클라이언트의 컨텍스트 매니저(start_as_current_observation)로 for 루프 전체를 감싸서,
    제너레이터가 소진될 때까지 스팬이 열려있게 한다 — 그래야 안쪽 4개 노드의 @observe()
    스팬이 이 스트리밍 실행에도 똑같이 "요청 하나 = 트레이스 하나"로 묶인다.

    run_trip_route_workflow와 마찬가지로, 같은 thread_id로 다음 턴이 이어질 때
    warnings/react_trace가 이전 턴 값에 누적되지 않도록 실행 전에 해당 thread의
    체크포인트를 지운다.
    """
    config = None
    checkpointer = get_checkpointer()
    if checkpointer is not None:
        actual_thread_id = thread_id or str(uuid.uuid4())
        checkpointer.delete_thread(actual_thread_id)
        config = {"configurable": {"thread_id": actual_thread_id}}

    with get_client().start_as_current_observation(
        name="trip_plan_workflow_stream", as_type="span"
    ):
        for update in _TRIP_ROUTE_GRAPH.stream(
            {
                "user_input": user_input,
                "transport_mode": transport_mode,
                "people_count": people_count,
                "previous_condition_summary": previous_condition_summary,
                "previous_result": previous_result,
                "warnings": [],
                "react_trace": [],
            },
            config=config,
            stream_mode="updates",
        ):
            for node_name, node_output in update.items():
                message = NODE_PROGRESS_MESSAGES.get(node_name, "처리하고 있어요...")

                if node_name == FINALIZE_NODE:
                    yield message, node_output["result"]
                else:
                    yield message, None

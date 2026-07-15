# app/agents/coordinator.py

from typing import Any, Dict, Iterator, Optional, Tuple

from app.graph.workflow import run_trip_route_workflow, stream_trip_route_workflow


def run_triproute_coordinator(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Dict[str, Any]:
    """
    TripRoute 전체 Workflow를 제어하는 Coordinator.

    실제 단계 조립은 LangGraph 기반 app.graph.workflow에서 수행한다:
    parse_trip_request -> route_planner -> financial -> finalize.

    previous_condition_summary를 넘기면 직전 턴의 조건을 이어받아 후속 대화
    ("카페 말고 맛집 위주로 바꿔줘" 등)로 처리하고, previous_result(직전 턴 전체 결과)를
    함께 넘기면 기간 연장 후속 요청("3일로 늘려줘")에서 기존 일정을 유지한 채 늘어난
    날짜만 새로 채운다. thread_id는 LangGraph 체크포인터가 켜져 있을 때 State 스냅샷을
    구분하는 단위(보통 대화 세션 id)다.
    """

    return run_trip_route_workflow(
        user_input=user_input,
        transport_mode=transport_mode,
        people_count=people_count,
        previous_condition_summary=previous_condition_summary,
        previous_result=previous_result,
        thread_id=thread_id,
    )


def stream_triproute_coordinator(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Iterator[Tuple[str, Optional[Dict[str, Any]]]]:
    """
    run_triproute_coordinator와 동일하지만, 노드가 끝날 때마다 (진행 메시지, 결과 or None)을
    yield한다 — Gradio가 단계별 진행 상황을 실시간으로 보여줄 수 있게 하기 위한 스트리밍 버전.
    """

    yield from stream_trip_route_workflow(
        user_input=user_input,
        transport_mode=transport_mode,
        people_count=people_count,
        previous_condition_summary=previous_condition_summary,
        previous_result=previous_result,
        thread_id=thread_id,
    )

# app/agents/react_loop.py

from typing import Any, Dict, Iterator, Optional, Tuple

from app.agents.coordinator import run_triproute_coordinator, stream_triproute_coordinator


def run_triproute_react_loop(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Dict[str, Any]:
    """
    기존 호환성을 위한 wrapper.
    실제 Workflow는 coordinator.py에서 수행한다.
    """

    return run_triproute_coordinator(
        user_input=user_input,
        transport_mode=transport_mode,
        people_count=people_count,
        previous_condition_summary=previous_condition_summary,
        previous_result=previous_result,
        thread_id=thread_id,
    )


def stream_triproute_react_loop(
    user_input: str,
    transport_mode: str = "대중교통",
    people_count: int = 2,
    previous_condition_summary: Dict[str, Any] | None = None,
    previous_result: Dict[str, Any] | None = None,
    thread_id: str | None = None,
) -> Iterator[Tuple[str, Optional[Dict[str, Any]]]]:
    """
    run_triproute_react_loop의 스트리밍 버전. 노드가 끝날 때마다 (진행 메시지, 결과 or None)을
    yield해서, Gradio가 "관광지 찾는 중...", "비용 계산 중..." 같은 단계별 상태를 실시간으로
    보여줄 수 있게 한다.
    """

    yield from stream_triproute_coordinator(
        user_input=user_input,
        transport_mode=transport_mode,
        people_count=people_count,
        previous_condition_summary=previous_condition_summary,
        previous_result=previous_result,
        thread_id=thread_id,
    )
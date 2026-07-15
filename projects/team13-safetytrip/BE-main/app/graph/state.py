"""
LangGraph 파이프라인 전체에서 공유하는 상태 스키마.
"""
from typing import TypedDict, Optional, List, Dict, Any


class AgentState(TypedDict, total=False):
    # 입력
    user_query: str

    # parse 노드 결과
    region_sido: Optional[str]
    region_sigungu: Optional[str]
    month: Optional[int]
    intent: Optional[str]          # "prevention" | "reactive"
    disaster_type: Optional[str]   # reactive일 때 명시된 재난유형
    has_vulnerable: bool
    parse_failed: bool

    # stats/retrieve 노드 결과
    stats_result: Optional[Any]           # DisasterStatsResult
    retrieved_guidelines: List[Dict]

    # gate 노드 결과
    should_escalate: bool
    escalate_reason: Optional[str]

    # 최종 (non-streaming 경로에서만 채워짐; SSE는 별도로 스트리밍)
    final_answer: Optional[str]
    escalate_contact: Optional[Dict]
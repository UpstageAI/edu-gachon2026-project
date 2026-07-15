# app/graph/edges.py

from app.graph.nodes import (
    FINALIZE_NODE,
    FINANCIAL_NODE,
    PARSE_NODE,
    ROUTE_PLANNER_NODE,
)

# TripRoute Workflow는 분기 없는 선형 파이프라인이다:
# 입력 파싱 -> 경로/일정 생성 -> 비용 계산 -> 최종 응답 조립
LINEAR_EDGES = [
    (PARSE_NODE, ROUTE_PLANNER_NODE),
    (ROUTE_PLANNER_NODE, FINANCIAL_NODE),
    (FINANCIAL_NODE, FINALIZE_NODE),
]

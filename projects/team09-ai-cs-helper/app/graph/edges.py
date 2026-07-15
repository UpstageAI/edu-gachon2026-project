"""
LangGraph 조건부 엣지(conditional edge) 라우팅 함수 모음.
"""

import logging

from app.graph.nodes import MAX_RETRY
from app.graph.state import InquiryState

logger = logging.getLogger(__name__)


def route_after_router(state: InquiryState) -> str:
    """ROUTER: 답변 가능/불가능 판단 이후 분기.

    가능(AI_generate) -> 평가 노드로.
    불가능(to_human) -> 바로 DB 저장으로.
    """
    if state["intent"] == "AI_generate":
        logger.info("route_after_router: AI_generate -> review")
        return "review"
    logger.info("route_after_router: to_human -> save_to_db (AI 답변 없이 상담원 이관)")
    return "save_to_db"


def route_after_review(state: InquiryState) -> str:
    """ROUTER: 평가 및 재시도 이후 분기.

    통과했거나 3번 연속 실패 -> DB 저장으로.
    실패(재시도 여력 있음) -> 다시 router 노드로 (답변 재생성).
    """
    if state["answer_review"] == "pass":
        logger.info("route_after_review: pass -> save_to_db")
        return "save_to_db"
    if state["retry_count"] >= MAX_RETRY:
        logger.warning(
            "route_after_review: 최대 재시도(%d) 도달 -> 검수 미통과본으로 강제 저장", MAX_RETRY
        )
        return "save_to_db"
    logger.info("route_after_review: fail -> router (재생성, retry_count=%d)", state["retry_count"])
    return "router"

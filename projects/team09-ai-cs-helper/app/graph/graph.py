import logging

from langgraph.graph import END, START, StateGraph

from app.graph.edges import route_after_review, route_after_router
from app.graph.nodes import (
    mask_personal_info_node,
    rag_search_node,
    review_node,
    router_node,
    save_to_db_node,
)
from app.graph.state import InquiryState

logger = logging.getLogger(__name__)


def build_graph():
    workflow = StateGraph(InquiryState)

    # 최초 INSERT는 그래프 실행 전 main.py의 start_inquiry에서 수행한다.
    # 그래프는 마스킹부터 시작해 마지막에 결과를 UPDATE(final_save)한다.
    workflow.add_node("mask_personal_info", mask_personal_info_node)
    workflow.add_node("rag_search", rag_search_node)
    workflow.add_node("router", router_node)
    workflow.add_node("review", review_node)
    workflow.add_node("final_save", save_to_db_node)

    workflow.add_edge(START, "mask_personal_info")
    workflow.add_edge("mask_personal_info", "rag_search")
    workflow.add_edge("rag_search", "router")

    workflow.add_conditional_edges(
        "router",
        route_after_router,
        {"review": "review", "save_to_db": "final_save"},
    )
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {"router": "router", "save_to_db": "final_save"},
    )

    workflow.add_edge("final_save", END)

    return workflow.compile()


graph = build_graph()
logger.info("LangGraph 컴파일 완료")

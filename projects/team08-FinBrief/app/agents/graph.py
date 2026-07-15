"""FinBrief · 메인 생성 그래프 조립.
START → ingest_news → collect_topics → collect_indicators → build_report_image → load_cached_cards
      → retrieve_evidence → [dispatch: Send FanOut] → build_card(병렬)
      → persist_cards → aggregate_cards → deliver → END

collect_topics를 collect_indicators 앞으로 옮겨 구독 토픽 기반 지표 실수집이 가능하고,
retrieve_evidence에서 캐시 미스 토픽에 대해 Supabase RAG(match_news) 근거를 선조회한다."""
from __future__ import annotations

from langgraph.graph import StateGraph, START, END

from .state import BriefState
from . import nodes as N


def build_graph():
    g = StateGraph(BriefState)
    g.add_node("ingest_news", N.ingest_news)
    g.add_node("collect_topics", N.collect_topics)
    g.add_node("collect_indicators", N.collect_indicators)
    g.add_node("build_report_image", N.build_report_image)
    g.add_node("load_cached_cards", N.load_cached_cards)
    g.add_node("retrieve_evidence", N.retrieve_evidence)
    g.add_node("build_card", N.build_card)
    g.add_node("persist_cards", N.persist_cards)
    g.add_node("aggregate_cards", N.aggregate_cards)
    g.add_node("deliver", N.deliver)

    g.add_edge(START, "ingest_news")
    g.add_edge("ingest_news", "collect_topics")
    g.add_edge("collect_topics", "collect_indicators")
    g.add_edge("collect_indicators", "build_report_image")
    g.add_edge("build_report_image", "load_cached_cards")
    g.add_edge("load_cached_cards", "retrieve_evidence")
    g.add_conditional_edges("retrieve_evidence", N.dispatch, ["build_card", "aggregate_cards"])
    g.add_edge("build_card", "persist_cards")
    g.add_edge("persist_cards", "aggregate_cards")
    g.add_edge("aggregate_cards", "deliver")
    g.add_edge("deliver", END)
    return g.compile()


graph = build_graph()

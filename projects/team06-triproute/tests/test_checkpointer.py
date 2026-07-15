from langgraph.checkpoint.memory import MemorySaver

import app.agents.route_planner as route_planner
from app.graph.checkpointer import get_checkpointer
from app.graph.workflow import build_trip_route_graph


def test_get_checkpointer_returns_none_without_supabase_db_url(monkeypatch):
    # SUPABASE_DB_URL이 없으면(로컬 개발/CI 기본값) psycopg 연결을 시도하지 않고 그냥
    # None을 반환해서, 체크포인터 없이 기존과 동일하게 그래프가 컴파일돼야 한다.
    from app.core.config import settings

    monkeypatch.setattr(settings, "SUPABASE_DB_URL", None)
    # 모듈 전역 캐시(_checkpointer/_connection_failed)가 이전 테스트나 실제 .env 설정
    # 때문에 채워져 있을 수 있으니 초기화한다.
    monkeypatch.setattr("app.graph.checkpointer._checkpointer", None)
    monkeypatch.setattr("app.graph.checkpointer._connection_failed", False)

    assert get_checkpointer() is None


def _force_mock_route_planner(monkeypatch):
    # 실제 TourAPI/RAG 호출 없이 Mock fallback 경로로 빠지게 한다
    # (test_react_loop.py와 동일한 패턴).
    def raise_tour_api_error(*args, **kwargs):
        raise RuntimeError("테스트용 TourAPI 실패")

    monkeypatch.setattr(route_planner, "retrieve_places_by_taste", lambda *args, **kwargs: [])
    monkeypatch.setattr(route_planner, "search_keyword", raise_tour_api_error)


def test_checkpointer_records_state_snapshots_per_thread(monkeypatch):
    _force_mock_route_planner(monkeypatch)

    checkpointer = MemorySaver()
    graph = build_trip_route_graph(checkpointer=checkpointer)
    config = {"configurable": {"thread_id": "test-thread-1"}}

    final_state = graph.invoke(
        {
            "user_input": "강릉으로 1박 2일 여행 가고 싶어. 바다랑 감성 카페, 먹거리를 좋아해.",
            "transport_mode": "대중교통",
            "people_count": 2,
            "warnings": [],
            "react_trace": [],
        },
        config=config,
    )

    assert final_state["result"]["condition_summary"]["city"] == "강릉"

    # 체크포인터가 thread_id 기준으로 실행 중 State 스냅샷을 실제로 저장했는지 확인한다
    # (노드 4개 + 시작 지점만큼 최소 여러 개의 체크포인트가 쌓여야 함).
    checkpoints = list(checkpointer.list(config))
    assert len(checkpoints) >= 4

    # 같은 thread_id로 그래프의 최신 체크포인트를 다시 조회할 수 있어야 한다(재개 가능성 확인).
    latest = checkpointer.get(config)
    assert latest is not None


def test_checkpointer_isolates_different_threads(monkeypatch):
    _force_mock_route_planner(monkeypatch)

    checkpointer = MemorySaver()
    graph = build_trip_route_graph(checkpointer=checkpointer)

    graph.invoke(
        {
            "user_input": "강릉으로 1박 2일 여행 가고 싶어.",
            "transport_mode": "대중교통",
            "people_count": 2,
            "warnings": [],
            "react_trace": [],
        },
        config={"configurable": {"thread_id": "thread-a"}},
    )
    graph.invoke(
        {
            "user_input": "부산으로 2박 3일 여행 가고 싶어.",
            "transport_mode": "대중교통",
            "people_count": 2,
            "warnings": [],
            "react_trace": [],
        },
        config={"configurable": {"thread_id": "thread-b"}},
    )

    checkpoints_a = list(checkpointer.list({"configurable": {"thread_id": "thread-a"}}))
    checkpoints_b = list(checkpointer.list({"configurable": {"thread_id": "thread-b"}}))

    # 서로 다른 thread_id의 체크포인트는 섞이지 않고 각자 독립적으로 쌓여야 한다.
    assert checkpoints_a
    assert checkpoints_b
    assert checkpoints_a[0].config["configurable"]["thread_id"] == "thread-a"
    assert checkpoints_b[0].config["configurable"]["thread_id"] == "thread-b"

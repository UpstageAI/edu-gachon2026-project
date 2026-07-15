import app.agents.route_planner as route_planner
from app.agents.react_loop import run_triproute_react_loop
from app.core.config import settings


def test_react_loop_gangneung_mock_scenario(monkeypatch):
    # RAG 검색과 TourAPI 호출을 모두 실패하게 만들어 Mock fallback을 검증
    # (RAG가 우선 시도되므로, RAG까지 같이 막아야 TourAPI 실패 경로로 넘어감)
    def raise_tour_api_error(*args, **kwargs):
        raise RuntimeError("테스트용 TourAPI 실패")

    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        route_planner,
        "search_keyword",
        raise_tour_api_error,
    )

    result = run_triproute_react_loop(
        user_input=(
            "강릉으로 1박 2일 여행 가고 싶어. "
            "바다랑 감성 카페, 먹거리를 좋아해."
        ),
        transport_mode="대중교통",
        people_count=2,
    )

    assert result["condition_summary"]["city"] == "강릉"
    assert result["condition_summary"]["transport_mode"] == "대중교통"
    assert result["condition_summary"]["people_count"] == 2

    assert len(result["daily_schedule"]) >= 1
    assert result["daily_schedule"][0]["place"] == "안목해변"

    assert len(result["route_summary"]) >= 1
    assert result["cost_summary"]["total"] > 0
    # LangGraph 실제 실행 노드 수(parse -> route_planner -> financial -> finalize)만큼 트레이스가 남는다
    assert len(result["react_trace"]) == 4
    assert [entry["action"] for entry in result["react_trace"]] == [
        "parse_trip_request",
        "build_route_plan",
        "build_financial_summary",
        "finalize_response",
    ]


def test_react_loop_threads_previous_condition_summary(monkeypatch):
    # previous_condition_summary가 coordinator -> graph -> parse_node까지 에러 없이
    # 전달되고, mock fallback 경로에서는 맥락 유실 경고가 남는지 확인
    monkeypatch.setattr(settings, "UPSTAGE_API_KEY", "", raising=False)
    monkeypatch.setattr(
        route_planner,
        "retrieve_places_by_taste",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        route_planner,
        "search_keyword",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("테스트용 실패")),
    )

    result = run_triproute_react_loop(
        user_input="카페 말고 맛집 위주로 바꿔줘.",
        transport_mode="대중교통",
        people_count=2,
        previous_condition_summary={
            "user_input": "강릉으로 1박 2일 여행 가고 싶어. 바다랑 감성 카페를 좋아해.",
            "city": "강릉",
            "season": "여름",
            "duration": "1박 2일",
            "travel_style": ["바다", "감성 카페"],
            "schedule_intensity": "여유로운 일정",
            "prefer_local": False,
            "prefer_budget": False,
            "is_peak_season": False,
        },
    )

    assert result["condition_summary"]["city"] == "강릉"
    assert any(
        "이전 대화 맥락을 반영하지 못했습니다" in warning
        for warning in result["warnings"]
    )
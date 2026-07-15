# app/graph/nodes.py

from typing import Any, Dict, List

from langfuse import observe

from app.agents.financial import build_financial_summary
from app.agents.route_planner import (
    _parse_travel_days,
    build_incremental_route_plan,
    build_named_place_insertion_route_plan,
    build_place_move_route_plan,
    build_route_plan,
    build_slot_replacement_route_plan,
)
from app.core.state import TripRouteState
from app.services.solar import parse_trip_request
from app.utils.cost_rules import build_cost_summary

PARSE_NODE = "parse_trip_request"
ROUTE_PLANNER_NODE = "route_planner"
FINANCIAL_NODE = "financial"
FINALIZE_NODE = "finalize"


def _trace_entry(step: int, action: str, description: str, **extra: Any) -> Dict[str, Any]:
    entry: Dict[str, Any] = {"step": step, "action": action, "description": description}
    entry.update(extra)
    return entry


@observe(name=PARSE_NODE)
def parse_node(state: TripRouteState) -> Dict[str, Any]:
    """1단계: Solar API(또는 Mock parser)로 사용자 입력을 여행 조건으로 구조화한다."""
    parsed, parse_warnings = parse_trip_request(
        state["user_input"],
        state.get("previous_condition_summary"),
    )
    parser = parsed.get("_parser", "unknown")

    return {
        "city": parsed.get("city"),
        "season": parsed.get("season"),
        "duration": parsed.get("duration"),
        "travel_style": parsed.get("travel_style", []),
        "must_include_places": parsed.get("must_include_places", []),
        "schedule_intensity": parsed.get("schedule_intensity"),
        "prefer_local": parsed.get("prefer_local", False),
        "prefer_budget": parsed.get("prefer_budget", False),
        "is_peak_season": parsed.get("is_peak_season", False),
        "target_day": parsed.get("target_day"),
        "target_time_slot": parsed.get("target_time_slot"),
        "move_source_day": parsed.get("move_source_day"),
        "move_source_time_slot": parsed.get("move_source_time_slot"),
        "move_source_place_name": parsed.get("move_source_place_name"),
        "move_destination_day": parsed.get("move_destination_day"),
        "move_destination_time_slot": parsed.get("move_destination_time_slot"),
        "add_place_name": parsed.get("add_place_name"),
        "add_place_day": parsed.get("add_place_day"),
        "daily_preferences": parsed.get("daily_preferences", []),
        "parser": parser,
        "warnings": list(parse_warnings),
        "react_trace": [
            _trace_entry(
                1,
                "parse_trip_request",
                "Solar API 또는 Mock parser로 사용자 입력을 여행 조건으로 구조화",
                parser=parser,
            )
        ],
    }


@observe(name=ROUTE_PLANNER_NODE)
def route_planner_node(state: TripRouteState) -> Dict[str, Any]:
    """
    2단계: Route Planner Agent가 관광지 후보/연관 장소/동선/일정을 만든다.

    같은 도시에 대한 기간 연장 후속 요청("3일로 늘려줘")이면 build_incremental_route_plan으로
    기존 Day 일정은 유지한 채 늘어난 날짜만 새로 채우고, 장소 이동 후속 요청("2일차 관광지를
    1일차로 옮겨줘" 또는 원본 날짜 없이 이름만 말한 "안목해변을 3일차로 옮겨줘")이면
    build_place_move_route_plan으로 그 장소를 목적지로 옮기고(목적지에 있던 기존 장소는
    빠짐) 비게 된 원래 자리는 새로 검색한 장소로 채우며, 날짜 지정 장소 추가 후속 요청
    ("2일차에 국립경주박물관 꼭 추가해줘")이면 build_named_place_insertion_route_plan으로
    기존 일정은 그대로 두고 그 날짜 끝에 새 장소를 하나 끼워 넣으며, 슬롯 교체 후속 요청
    ("2일차 점심만 바꿔줘")이면 build_slot_replacement_route_plan으로 그 슬롯 하나만
    새 장소로 바꾼다. 넷 다 아니면 처음부터 다시 계획한다.
    """
    parsed = {
        "city": state.get("city"),
        "season": state.get("season"),
        "duration": state.get("duration"),
        "travel_style": state.get("travel_style", []),
        "must_include_places": state.get("must_include_places", []),
        "schedule_intensity": state.get("schedule_intensity"),
        "prefer_local": state.get("prefer_local", False),
        "prefer_budget": state.get("prefer_budget", False),
        "is_peak_season": state.get("is_peak_season", False),
        # daily_preferences는 처음 계획(전체 재계획 경로)에서만 쓰인다 — 기간연장/장소이동/
        # 슬롯교체는 이미 확정된 일정을 다루는 후속 요청이라 이 필드를 보지 않는다.
        "daily_preferences": state.get("daily_preferences", []),
    }

    previous_condition = state.get("previous_condition_summary")
    previous_result = state.get("previous_result")

    is_duration_extension = False
    previous_days = 0

    if previous_condition and previous_result:
        previous_city = previous_condition.get("city")
        previous_duration = str(previous_condition.get("duration") or "")
        new_duration = str(state.get("duration") or "")

        if previous_city and previous_city == state.get("city") and previous_duration:
            previous_days = _parse_travel_days(previous_duration)
            new_days = _parse_travel_days(new_duration) if new_duration else 0
            is_duration_extension = new_days > previous_days

    target_day = state.get("target_day")
    target_time_slot = state.get("target_time_slot")
    is_slot_replacement = (
        not is_duration_extension
        and previous_result is not None
        and target_day is not None
        and target_time_slot is not None
    )

    move_source_day = state.get("move_source_day")
    move_source_place_name = state.get("move_source_place_name")
    move_destination_day = state.get("move_destination_day")
    is_place_move = (
        not is_duration_extension
        and previous_result is not None
        and (move_source_day is not None or move_source_place_name)
        and move_destination_day is not None
    )

    add_place_name = state.get("add_place_name")
    add_place_day = state.get("add_place_day")
    is_named_insertion = (
        not is_duration_extension
        and not is_place_move
        and previous_result is not None
        and add_place_name
        and add_place_day is not None
    )

    if is_duration_extension:
        route_plan = build_incremental_route_plan(
            parsed=parsed,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
            previous_result=previous_result,
            previous_days=previous_days,
        )
    elif is_place_move:
        route_plan = build_place_move_route_plan(
            parsed=parsed,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
            previous_result=previous_result,
            source_day=move_source_day,
            source_time_slot=state.get("move_source_time_slot"),
            source_place_name=move_source_place_name,
            destination_day=move_destination_day,
            destination_time_slot=state.get("move_destination_time_slot"),
        )
    elif is_named_insertion:
        route_plan = build_named_place_insertion_route_plan(
            parsed=parsed,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
            previous_result=previous_result,
            place_name=add_place_name,
            target_day=add_place_day,
        )
    elif is_slot_replacement:
        route_plan = build_slot_replacement_route_plan(
            parsed=parsed,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
            previous_result=previous_result,
            target_day=target_day,
            target_time_slot=target_time_slot,
        )
    else:
        route_plan = build_route_plan(
            parsed=parsed,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
        )

    return {
        "candidate_places": route_plan.get("candidate_places", []),
        "rag_ranked_places": route_plan.get("rag_ranked_places", []),
        "related_places": route_plan.get("related_places", []),
        "selected_places": route_plan.get("selected_places", []),
        "route_summary": route_plan.get("route_summary", []),
        "daily_schedule": route_plan.get("daily_schedule", []),
        "lodging_place": route_plan.get("lodging_place"),
        "data_source": route_plan.get("data_source", "mock"),
        "warnings": list(route_plan.get("warnings", [])),
        "react_trace": [
            _trace_entry(
                2,
                "build_route_plan",
                "관광지 후보 검색부터 연관 장소·이동 동선·일정 배정까지 "
                "Route Planner Agent가 처리",
            )
        ],
    }


def _build_fallback_cost_summary(
    daily_schedule: List[Dict[str, Any]],
    people_count: int,
) -> Dict[str, Any]:
    """
    Financial Agent 계산이 예외로 실패했을 때 쓰는 최소 추정치 fallback.
    실측 API 호출 없이 build_cost_summary의 고정 단가 기본값만으로 총액을 계산해서,
    이미 계산된 route_summary/daily_schedule을 버리지 않고 finalize_node까지 도달하게 한다.
    """
    travel_days = max(1, len({entry.get("day") for entry in daily_schedule if entry.get("day")}))
    nights = max(0, travel_days - 1)

    cost_summary = build_cost_summary(
        transport_cost=0,
        people_count=people_count,
        days=travel_days,
        nights=nights,
    )

    return {
        "total": cost_summary["total"],
        "transport_cost": cost_summary["transport"],
        "food_cost": cost_summary["food"],
        "cafe_cost": cost_summary["cafe"],
        "admission_cost": cost_summary["admission"],
        "lodging_cost": cost_summary["lodging"],
        "total_cost": cost_summary["total"],
        "currency": cost_summary["currency"],
        "is_estimated": True,
    }


@observe(name=FINANCIAL_NODE)
def financial_node(state: TripRouteState) -> Dict[str, Any]:
    """3단계: Financial Agent가 교통비/식비/입장료/숙박비 등 예상 비용을 계산한다."""
    route_plan = {
        "route_summary": state.get("route_summary", []),
        "daily_schedule": state.get("daily_schedule", []),
        "selected_places": state.get("selected_places", []),
        "lodging_place": state.get("lodging_place"),
        "is_peak_season": state.get("is_peak_season", False),
    }

    warnings: List[str] = []
    try:
        cost_summary = build_financial_summary(
            route_plan=route_plan,
            transport_mode=state["transport_mode"],
            people_count=state["people_count"],
        )
    except Exception:
        # build_financial_summary 내부에서 방어하지 못한 예외(dict 형태 불일치, 알려지지
        # 않은 네트워크 예외 등)가 나면 그래프 전체를 무너뜨리는 대신 최소 추정치로
        # 대체하고, 이미 계산된 route_summary/daily_schedule은 그대로 유지한다.
        cost_summary = _build_fallback_cost_summary(
            daily_schedule=route_plan["daily_schedule"],
            people_count=state["people_count"],
        )
        warnings.append(
            "예상 비용 계산 중 오류가 발생해 최소 추정치로 대체했습니다. "
            "일정/동선 결과는 정상적으로 유지됩니다."
        )

    return {
        "cost_summary": cost_summary,
        "warnings": warnings,
        "react_trace": [
            _trace_entry(
                3,
                "build_financial_summary",
                "교통비·식비·입장료·숙박비 등 예상 비용을 Financial Agent가 계산",
            )
        ],
    }


@observe(name=FINALIZE_NODE)
def finalize_node(state: TripRouteState) -> Dict[str, Any]:
    """4단계: 각 Agent 결과를 최종 응답 형태로 조립한다."""
    existing_warnings = list(state.get("warnings", []))
    new_warnings: List[str] = []

    if state.get("data_source", "mock") == "mock":
        new_warnings.append(
            "실제 관광 API 호출 실패 또는 미연결 상태로 "
            "Mock fallback 데이터를 사용했습니다."
        )

    if state.get("transport_mode") == "대중교통":
        new_warnings.append(
            "대중교통 시간과 비용은 자동차 경로 기반 참고용 추정치입니다."
        )

    warnings = existing_warnings + new_warnings

    finalize_entry = _trace_entry(
        4,
        "finalize_response",
        "Coordinator가 각 Agent 결과를 최종 응답으로 조립",
    )
    # finalize 노드 자신의 트레이스는 이 시점엔 아직 state에 병합되지 않았으므로,
    # 최종 응답에 넣을 react_trace에는 직접 이어붙여야 4단계가 전부 담긴다.
    full_react_trace = list(state.get("react_trace", [])) + [finalize_entry]

    result = {
        "condition_summary": {
            "user_input": state.get("user_input"),
            "city": state.get("city"),
            "season": state.get("season"),
            "duration": state.get("duration"),
            "travel_style": state.get("travel_style", []),
            "must_include_places": state.get("must_include_places", []),
            "schedule_intensity": state.get("schedule_intensity"),
            "prefer_local": state.get("prefer_local", False),
            "prefer_budget": state.get("prefer_budget", False),
            "is_peak_season": state.get("is_peak_season", False),
            "transport_mode": state.get("transport_mode"),
            "people_count": state.get("people_count"),
            "parser": state.get("parser", "unknown"),
            "data_source": state.get("data_source", "mock"),
        },
        "daily_schedule": state.get("daily_schedule", []),
        "route_summary": state.get("route_summary", []),
        "cost_summary": state.get("cost_summary", {}),
        "warnings": warnings,
        "react_trace": full_react_trace,
    }

    return {
        "react_trace": [finalize_entry],
        # warnings는 operator.add로 누적되므로, 이미 state에 쌓여 있는 existing_warnings는
        # 다시 담지 않고 finalize_node가 새로 추가한 경고만 반환해야 중복 없이 합쳐진다.
        "warnings": new_warnings,
        "result": result,
    }

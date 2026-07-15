from typing import Any, Dict, List

from app.tools.schemas import ToolResult


def search_places_tool(city: str, travel_style: List[str]) -> ToolResult:
    """
    Mock 관광지 검색 Tool입니다.
    실제 구현에서는 TourAPI + RAG 검색 결과로 대체합니다.
    """

    places = [
        {
            "name": "안목해변",
            "category": "바다",
            "address": "강원특별자치도 강릉시 창해로14번길",
            "description": "강릉의 대표적인 바다 관광지입니다.",
        },
        {
            "name": "강릉 중앙시장",
            "category": "먹거리",
            "address": "강원특별자치도 강릉시 금성로",
            "description": "먹거리 여행에 적합한 전통시장입니다.",
        },
        {
            "name": "안목 커피거리",
            "category": "감성 카페",
            "address": "강원특별자치도 강릉시 창해로",
            "description": "바다를 보며 카페를 즐길 수 있는 거리입니다.",
        },
        {
            "name": "오죽헌",
            "category": "역사문화",
            "address": "강원특별자치도 강릉시 율곡로3139번길",
            "description": "강릉의 대표 역사문화 관광지입니다.",
        },
    ]

    return ToolResult(
        tool_name="search_places",
        observation={
            "city": city,
            "travel_style": travel_style,
            "places": places,
        },
    )


def get_related_places_tool(places: List[Dict[str, Any]]) -> ToolResult:
    """
    Mock 연관 관광지 Tool입니다.
    실제 구현에서는 한국관광공사 관광지별 연관 관광지 정보 API 결과로 대체합니다.
    """

    related_places = [
        {
            "base_place": "안목해변",
            "related_place": "안목 커피거리",
            "relation_reason": "바다 관광 후 카페 방문 동선이 자연스럽습니다.",
            "rank": 1,
        },
        {
            "base_place": "강릉 중앙시장",
            "related_place": "오죽헌",
            "relation_reason": "시내권 이동 후 역사문화 코스로 연결할 수 있습니다.",
            "rank": 2,
        },
    ]

    return ToolResult(
        tool_name="get_related_places",
        observation={
            "related_places": related_places,
        },
    )


def get_route_info_tool(
    places: List[Dict[str, Any]],
    transport_mode: str,
) -> ToolResult:
    """
    Mock 이동정보 Tool입니다.
    실제 구현에서는 카카오모빌리티 API 결과로 대체합니다.
    """

    route_segments = [
        {
            "from": "안목해변",
            "to": "강릉 중앙시장",
            "distance_km": 6.2,
            "estimated_time": "약 20분",
            "transport_mode": transport_mode,
            "taxi_fare": 11000,
            "memo": "바다 일정 후 먹거리 코스로 이동합니다.",
        },
        {
            "from": "강릉 중앙시장",
            "to": "안목 커피거리",
            "distance_km": 5.8,
            "estimated_time": "약 25분",
            "transport_mode": transport_mode,
            "taxi_fare": 10000,
            "memo": "식사 후 감성 카페 코스로 이동합니다.",
        },
    ]

    return ToolResult(
        tool_name="get_route_info",
        observation={
            "route_segments": route_segments,
        },
    )


def estimate_cost_tool(
    route_segments: List[Dict[str, Any]],
    people_count: int,
    transport_mode: str,
) -> ToolResult:
    """
    Mock 비용 계산 Tool입니다.
    실제 구현에서는 이동수단별 교통비, 입장료, 식비, 숙박비 계산 로직으로 대체합니다.
    """

    if transport_mode == "택시":
        transport_cost = sum(segment["taxi_fare"] for segment in route_segments)
    elif transport_mode == "대중교통":
        transport_cost = 6000 * people_count
    else:
        transport_cost = 15000

    food_cost = 30000 * people_count
    cafe_cost = 15000 * people_count
    lodging_cost = 50000 * people_count

    total = transport_cost + food_cost + cafe_cost + lodging_cost

    return ToolResult(
        tool_name="estimate_cost",
        observation={
            "cost_summary": {
                "transport": transport_cost,
                "food": food_cost,
                "cafe": cafe_cost,
                "lodging": lodging_cost,
                "total": total,
                "currency": "KRW",
            }
        },
    )


def run_tool(tool_name: str, tool_input: Dict[str, Any]) -> ToolResult:
    """
    ReAct Loop에서 Tool 이름을 기준으로 Mock Tool을 실행합니다.
    """

    if tool_name == "search_places":
        return search_places_tool(
            city=tool_input["city"],
            travel_style=tool_input["travel_style"],
        )

    if tool_name == "get_related_places":
        return get_related_places_tool(
            places=tool_input["places"],
        )

    if tool_name == "get_route_info":
        return get_route_info_tool(
            places=tool_input["places"],
            transport_mode=tool_input["transport_mode"],
        )

    if tool_name == "estimate_cost":
        return estimate_cost_tool(
            route_segments=tool_input["route_segments"],
            people_count=tool_input["people_count"],
            transport_mode=tool_input["transport_mode"],
        )

    raise ValueError(f"Unknown tool name: {tool_name}")
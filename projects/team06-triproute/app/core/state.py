import operator
from typing import Annotated, Any, Dict, List, Optional, TypedDict


class TripRouteState(TypedDict, total=False):
    """
    TripRoute LangGraph Workflow에서 사용하는 공통 State입니다.

    각 노드(Agent)는 이 State를 읽고, 자신이 갱신할 필드만 담은 dict를 반환합니다.
    warnings/react_trace는 노드마다 새로 만든 리스트가 기존 값 뒤에 이어 붙도록
    (operator.add) 선언되어 있고, 나머지 필드는 마지막으로 쓴 값으로 교체됩니다.
    """

    # 사용자 입력
    user_input: str
    transport_mode: str
    people_count: int

    # 직전 턴의 condition_summary (후속 대화 맥락 이어가기용, 없으면 None)
    previous_condition_summary: Optional[Dict[str, Any]]
    # 직전 턴의 전체 결과(daily_schedule/route_summary 포함, finalize_node의 result와 동일 형태).
    # 기간 연장("3일로 늘려줘")/슬롯 교체("2일차 점심만 바꿔줘") 후속 요청에서 이미
    # 확정된 일정을 그대로 이어붙이거나 일부만 바꾸는 데 쓴다.
    previous_result: Optional[Dict[str, Any]]

    # Solar 파싱 결과 (parse_trip_request)
    city: str
    season: str
    duration: str
    travel_style: List[str]
    schedule_intensity: str
    prefer_local: bool
    prefer_budget: bool
    is_peak_season: bool
    must_include_places: List[str]
    parser: str
    # "2일차 점심만 바꿔줘" 같은 슬롯 교체 후속 요청에서만 채워짐(없으면 None)
    target_day: Optional[int]
    target_time_slot: Optional[str]
    # "2일차 관광지를 1일차로 옮겨줘" 같은 장소 이동/맞바꾸기 후속 요청에서만 채워짐
    move_source_day: Optional[int]
    move_source_time_slot: Optional[str]
    # 원본을 며칠차 대신 장소 이름으로 지칭하는 후속 요청("안목해변을 3일차로 옮겨줘")에서만 채워짐
    move_source_place_name: Optional[str]
    move_destination_day: Optional[int]
    move_destination_time_slot: Optional[str]
    # 날짜를 지목해 새 장소를 추가하는 후속 요청("2일차에 OO 추가해줘")에서만 채워짐
    add_place_name: Optional[str]
    add_place_day: Optional[int]
    # "1일차는 바다/카페, 2일차는 액티비티" 처럼 처음 계획할 때만 지원되는 일차별 취향/
    # 일정 강도 오버라이드. 언급 안 된 날짜는 여기 없고, 그런 날짜는 전체 공통값을 따른다.
    daily_preferences: List[Dict[str, Any]]

    # Route Planner 결과 (build_route_plan)
    candidate_places: List[Dict[str, Any]]
    rag_ranked_places: List[Dict[str, Any]]
    related_places: List[Dict[str, Any]]
    selected_places: List[Dict[str, Any]]
    route_summary: List[Dict[str, Any]]
    daily_schedule: List[Dict[str, Any]]
    lodging_place: Optional[Dict[str, Any]]
    data_source: str

    # Financial 결과 (build_financial_summary)
    cost_summary: Dict[str, Any]

    # 공통 누적 필드 (노드마다 이어 붙음)
    warnings: Annotated[List[str], operator.add]
    react_trace: Annotated[List[Dict[str, Any]], operator.add]

    # 최종 조립 결과 (finalize 노드에서 채움)
    result: Dict[str, Any]

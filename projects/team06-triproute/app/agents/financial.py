# app/agents/financial.py

from typing import Any, Dict, List, Optional

from app.rag.vector_store import CONTENT_TYPE_ID_TO_CATEGORY
from app.services.google_places_api import GooglePlacesAPIError, get_price_level
from app.services.tour_api import TourAPIError, get_detail_info, get_detail_intro
from app.services.upstage_client import parse_usefee_amount
from app.utils.cache import cached_call
from app.utils.cost_rules import build_cost_summary, estimate_lodging_fee_per_night
from app.utils.transport_rules import estimate_rental_car_cost, estimate_transport_cost

CATEGORY_TO_CONTENT_TYPE_ID = {
    category: content_type_id
    for content_type_id, category in CONTENT_TYPE_ID_TO_CATEGORY.items()
}

LODGING_CONTENT_TYPE_ID = "32"
RESTAURANT_CONTENT_TYPE_ID = "39"

# TourAPI는 카페를 "음식점"(39)과 같은 content_type_id로 묶어서 내려주기 때문에
# 카페/음식점을 나눌 구조화된 필드가 없다. 이름에 카페 관련 키워드가 있으면 카페로
# 간주하는 휴리스틱으로 대체한다(예산 감지에 쓰는 upstage_client의 키워드 매칭과 같은 방식).
CAFE_KEYWORDS = ("카페", "커피", "cafe", "coffee")

# CAFE_KEYWORDS로 못 잡는(이름에 "카페/커피" 등 키워드가 없는) 국내 주요 카페 브랜드.
# 이런 곳들은 실제로는 카페인데 키워드 매칭만으로는 음식점(meal_places)으로 잘못
# 분류되어 식비 단가로 계산되는 문제가 있었음.
KNOWN_CAFE_BRANDS = (
    "스타벅스",
    "starbucks",
    "빽다방",
    "투썸플레이스",
    "할리스",
    "엔제리너스",
    "탐앤탐스",
    "파스쿠찌",
)


def _resolve_content_type_id(place: Dict[str, Any]) -> Optional[str]:
    # TourAPI 실시간 검색(_normalize_tour_place) 결과는 content_type_id를 직접 갖고 있고,
    # RAG 결과(_normalize_rag_place)는 category 문자열만 있어서 역매핑이 필요함.
    content_type_id = place.get("content_type_id")
    if content_type_id:
        return str(content_type_id)

    category = place.get("category")
    if category:
        return CATEGORY_TO_CONTENT_TYPE_ID.get(category)

    return None


def _is_cafe_place(place: Dict[str, Any]) -> bool:
    title = (place.get("title") or "").lower()
    if any(keyword in title for keyword in CAFE_KEYWORDS):
        return True
    return any(brand.lower() in title for brand in KNOWN_CAFE_BRANDS)


def _fetch_admission_fee(place: Dict[str, Any]) -> Optional[int]:
    """
    장소의 TourAPI usefee(비정형 이용요금 텍스트)를 가져와 Upstage로 성인 1인 기준 금액을
    추출한다. content_id/content_type_id를 모르거나, usefee 필드 자체가 없거나(무료라서
    없는 게 아니라 그 콘텐츠 타입엔 필드가 없는 경우), 파싱에 실패하면 None을 반환해서
    호출부(cost_rules)가 기본 추정치로 대체하게 한다.
    """

    content_id = place.get("content_id")
    content_type_id = _resolve_content_type_id(place)

    if not content_id or not content_type_id:
        return None

    try:
        intro = cached_call(
            namespace="detail_intro_usefee",
            params={"content_id": content_id, "content_type_id": content_type_id},
            fetch_fn=lambda: get_detail_intro(content_id, content_type_id),
            ttl_seconds=60 * 60 * 24,
        )
    except TourAPIError:
        return None

    usefee_text = (intro.get("usefee") or "").strip()
    if not usefee_text:
        return None

    return parse_usefee_amount(usefee_text)


def _fetch_price_level(place: Dict[str, Any]) -> Optional[str]:
    """
    음식점의 Google Places priceLevel(가격대)을 가져온다. 이름만으로는 오매칭 위험이
    있어 find_place와 동일하게 좌표(TourAPI mapx/mapy)를 같이 넘긴다. 매칭 실패/이름이
    없으면 None을 반환해서 호출부(cost_rules)가 기본 추정치로 대체하게 한다.
    """

    title = place.get("title")
    if not title:
        return None

    try:
        return cached_call(
            namespace="google_places_price_level",
            params={
                "title": title,
                "address": place.get("address"),
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
            },
            fetch_fn=lambda: get_price_level(
                title,
                address=place.get("address"),
                lat=place.get("latitude"),
                lng=place.get("longitude"),
            ),
            ttl_seconds=60 * 60 * 24,
        )
    except GooglePlacesAPIError:
        return None


def _fetch_lodging_fee_per_night(
    place: Dict[str, Any],
    people_count: int,
    use_peak_season: bool = False,
) -> Optional[int]:
    """
    숙박 장소의 TourAPI detailInfo2(객실 목록)를 가져와서 실제 1박 요금을 추정한다.
    계산 로직 자체는 cost_rules.estimate_lodging_fee_per_night에 있음(Route Planner의
    숙박 후보 선택 단계에서도 같은 로직을 재사용해서 일관성을 맞춤).
    """

    content_id = place.get("content_id")
    if not content_id:
        return None

    try:
        rooms = cached_call(
            namespace="detail_info_lodging",
            params={"content_id": content_id, "content_type_id": LODGING_CONTENT_TYPE_ID},
            fetch_fn=lambda: get_detail_info(content_id, LODGING_CONTENT_TYPE_ID),
            ttl_seconds=60 * 60 * 24,
        )
    except TourAPIError:
        return None

    return estimate_lodging_fee_per_night(rooms, people_count, use_peak_season)


def _count_travel_days(daily_schedule: List[Dict[str, Any]]) -> int:
    days = {entry.get("day") for entry in daily_schedule if entry.get("day")}
    return max(1, len(days))


def build_financial_summary(
    route_plan: Dict[str, Any],
    transport_mode: str,
    people_count: int,
) -> Dict[str, Any]:
    """
    교통비, 식비, 카페비, 입장료, 숙박비, 총액을 계산한다.
    """

    route_summary = route_plan.get("route_summary", [])
    daily_schedule = route_plan.get("daily_schedule", [])

    travel_days = _count_travel_days(daily_schedule)
    nights = max(0, travel_days - 1)

    if transport_mode == "렌터카":
        # 렌터카는 이동 거리(leg)와 무관하게 여행 전체에 대해 한 번만 빌리는 비용이므로,
        # route_summary의 leg마다 반복 계산하면 leg 개수만큼 중복 청구된다.
        rental_info = estimate_rental_car_cost(
            people_count=people_count,
            travel_days=travel_days,
        )
        transport_cost = rental_info["rental_cost"]
    else:
        transport_cost = 0
        for route in route_summary:
            result = estimate_transport_cost(
                distance_km=route.get("distance_km", 0),
                car_minutes=route.get("car_minutes", 0),
                transport_mode=transport_mode,
                people_count=people_count,
                travel_days=travel_days,
                taxi_fare=route.get("taxi_fare"),
            )
            transport_cost += result.get("estimated_cost", 0)

    selected_places = route_plan.get("selected_places", [])
    is_peak_season = bool(route_plan.get("is_peak_season", False))

    restaurant_type_places = [
        place for place in selected_places
        if _resolve_content_type_id(place) == RESTAURANT_CONTENT_TYPE_ID
    ]
    # restaurant_type_places(식사/카페)는 meal_places/cafe_places 쪽에서 별도 단가로
    # 계산하므로, 여기서 또 입장료(place_fees) 대상에 넣으면 이중 과금된다.
    non_lodging_places = [
        place for place in selected_places
        if _resolve_content_type_id(place) not in (LODGING_CONTENT_TYPE_ID, RESTAURANT_CONTENT_TYPE_ID)
    ]
    place_fees = [_fetch_admission_fee(place) for place in non_lodging_places]

    meal_places = [place for place in restaurant_type_places if not _is_cafe_place(place)]
    cafe_places = [place for place in restaurant_type_places if _is_cafe_place(place)]
    meal_price_levels = [_fetch_price_level(place) for place in meal_places]
    cafe_price_levels = [_fetch_price_level(place) for place in cafe_places]

    # Route Planner가 1박 이상이면 lodging_place를 명시적으로 골라서 넘겨준다(보장된 경로).
    # 혹시 없으면(Mock fallback 등) selected_places에 우연히 섞인 숙박 장소를 대신 찾는다.
    lodging_candidates = [route_plan["lodging_place"]] if route_plan.get("lodging_place") else [
        place for place in selected_places
        if _resolve_content_type_id(place) == LODGING_CONTENT_TYPE_ID
    ]

    lodging_fee_per_night = None
    for lodging_place in lodging_candidates:
        fee = _fetch_lodging_fee_per_night(lodging_place, people_count, is_peak_season)
        if fee is not None:
            lodging_fee_per_night = fee
            break

    lodging_override = (
        lodging_fee_per_night * nights if lodging_fee_per_night is not None else None
    )

    cost_summary = build_cost_summary(
        transport_cost=transport_cost,
        people_count=people_count,
        days=travel_days,
        nights=nights,
        place_fees=place_fees,
        lodging_override=lodging_override,
        meal_price_levels=meal_price_levels,
        cafe_price_levels=cafe_price_levels,
    )

    return {
        # 기존 테스트 호환용
        "total": cost_summary["total"],
        # Step 6 출력 포맷용
        "transport_cost": cost_summary["transport"],
        "food_cost": cost_summary["food"],
        "cafe_cost": cost_summary["cafe"],
        "admission_cost": cost_summary["admission"],
        "lodging_cost": cost_summary["lodging"],
        "total_cost": cost_summary["total"],
        "currency": cost_summary["currency"],
        "is_estimated": True,
    }
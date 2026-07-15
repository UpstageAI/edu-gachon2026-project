import math
from typing import Any, Dict, List, Optional

DEFAULT_ADMISSION_FEE_PER_PERSON = 5000


def to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None


def to_positive_int(value: Any) -> Optional[int]:
    """
    0 이하 값은 실제 요금이 아니라 데이터 미기재로 간주해서 None 취급한다 — TourAPI에
    숙박 요금 필드가 "0"으로 등록된(실제 무료가 아니라 등록 누락으로 보이는) 곳이 실제로
    있어서, 이를 "0원짜리 방"으로 잘못 인정하는 걸 막기 위함.
    """

    parsed = to_int(value)
    if parsed is None or parsed <= 0:
        return None
    return parsed


def room_fee_at_occupancy(
    room: Dict[str, Any],
    occupancy: int,
    use_peak_season: bool = False,
) -> Optional[int]:
    """
    객실 하나를 occupancy명이 쓸 때의 요금을 반환한다(TourAPI detailInfo2 숙박 객실 항목
    기준). 기준 인원(roombasecount)을 넘으면 초과 인원 요금(*minfee2), 안 넘으면 기본
    요금(*minfee1). use_peak_season이면 성수기 요금(roompeakseasonminfee*)을 우선 쓰고,
    등록이 안 돼있으면 비성수기 요금으로 대체한다(전부 성수기 요금까지 등록해두진 않음).
    """

    base_count = to_int(room.get("roombasecount"))
    use_extra_fee = base_count is not None and occupancy > base_count

    if use_peak_season:
        peak_key = "roompeakseasonminfee2" if use_extra_fee else "roompeakseasonminfee1"
        peak_fee = to_positive_int(room.get(peak_key)) or to_positive_int(room.get("roompeakseasonminfee1"))
        if peak_fee is not None:
            return peak_fee

    off_key = "roomoffseasonminfee2" if use_extra_fee else "roomoffseasonminfee1"
    return to_positive_int(room.get(off_key)) or to_positive_int(room.get("roomoffseasonminfee1"))


def estimate_multi_room_fee(
    rooms: List[Dict[str, Any]],
    people_count: int,
    use_peak_season: bool = False,
) -> Optional[int]:
    """
    people_count를 한 객실로 못 채울 때, 같은 타입 객실을 여러 개 빌리는 것으로 근사한다.
    객실 타입별로 ceil(people_count / roommaxcount)개를 빌린다고 가정하고, 그중 총액이
    가장 저렴한 타입을 고른다 (서로 다른 타입을 섞어 쓰는 조합까지는 계산하지 않는 근사치).
    """

    best_total: Optional[int] = None

    for room in rooms:
        max_count = to_int(room.get("roommaxcount"))
        if not max_count or max_count <= 0:
            continue

        fee_per_room = room_fee_at_occupancy(room, max_count, use_peak_season)
        if fee_per_room is None:
            continue

        rooms_needed = math.ceil(people_count / max_count)
        total = fee_per_room * rooms_needed

        if best_total is None or total < best_total:
            best_total = total

    return best_total


def estimate_lodging_fee_per_night(
    rooms: List[Dict[str, Any]],
    people_count: int,
    use_peak_season: bool = False,
) -> Optional[int]:
    """
    TourAPI detailInfo2(객실 목록)에서 1박 요금을 추정한다.
    1순위: 단일 객실로 people_count를 수용 가능한 곳(roommaxcount 기준) 중 최저가.
    2순위: 딱 맞는 단일 객실이 없으면, 같은 타입 객실을 여러 개 빌리는 것으로 근사.
    등록된 요금 정보 자체가 없으면 None을 반환해서 호출부가 기본 추정치로 대체하게 한다.
    """

    single_room_fees = [
        fee
        for room in rooms
        if (max_count := to_int(room.get("roommaxcount"))) is not None
        and max_count >= people_count
        and (fee := room_fee_at_occupancy(room, people_count, use_peak_season)) is not None
    ]

    if single_room_fees:
        return min(single_room_fees)

    return estimate_multi_room_fee(rooms, people_count, use_peak_season)


def estimate_food_cost(people_count: int, days: int = 2) -> int:
    return 30000 * people_count * days


# Google Places(New) priceLevel enum -> 1인당 한 끼 식사비(KRW) 추정치.
GOOGLE_PRICE_LEVEL_TO_KRW_PER_PERSON = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 10000,
    "PRICE_LEVEL_MODERATE": 20000,
    "PRICE_LEVEL_EXPENSIVE": 35000,
    "PRICE_LEVEL_VERY_EXPENSIVE": 60000,
}
# priceLevel을 못 구한 끼니에 쓰는 폴백 — 기존 고정 단가(1인당 30000원/일 = 점심·저녁
# 2끼, route_planner의 MEAL_TIME_SLOTS 기준)와 맞춘 값이라 데이터가 전혀 없을 때는
# 이전 추정치와 동일한 총액이 나온다.
DEFAULT_MEAL_FEE_PER_PERSON = 15000


def estimate_food_cost_from_places(
    people_count: int,
    price_levels: List[Optional[str]],
) -> int:
    """
    실제 식사 장소(음식점)별 Google Places priceLevel로 식비를 추정합니다.
    priceLevel을 못 구한 장소(매칭 실패/데이터 미등록)는 DEFAULT_MEAL_FEE_PER_PERSON으로
    대체합니다 — admission fee의 place_fees 하이브리드 방식과 동일한 패턴입니다.
    """

    total = 0
    for level in price_levels:
        per_person = GOOGLE_PRICE_LEVEL_TO_KRW_PER_PERSON.get(level, DEFAULT_MEAL_FEE_PER_PERSON)
        total += per_person * people_count

    return total


def estimate_cafe_cost(people_count: int, cafe_visits: int = 1) -> int:
    return 15000 * people_count * cafe_visits


# Google Places(New) priceLevel enum -> 1인당 카페 방문 1회 비용(KRW) 추정치.
# 식사(GOOGLE_PRICE_LEVEL_TO_KRW_PER_PERSON)보다 낮게 잡음 — 같은 priceLevel이라도
# 카페 방문은 보통 음료/디저트 한두 개라 식사 한 끼보다 단가가 낮다.
GOOGLE_PRICE_LEVEL_TO_CAFE_KRW_PER_PERSON = {
    "PRICE_LEVEL_FREE": 0,
    "PRICE_LEVEL_INEXPENSIVE": 6000,
    "PRICE_LEVEL_MODERATE": 10000,
    "PRICE_LEVEL_EXPENSIVE": 18000,
    "PRICE_LEVEL_VERY_EXPENSIVE": 30000,
}
# priceLevel을 못 구한 카페 방문에 쓰는 폴백 — 기존 고정 단가(1인당 15000원 × 방문 1회)와
# 맞춘 값이라 데이터가 전혀 없을 때는 이전 추정치와 동일한 총액이 나온다.
DEFAULT_CAFE_FEE_PER_PERSON = 15000


def estimate_cafe_cost_from_places(
    people_count: int,
    price_levels: List[Optional[str]],
) -> int:
    """
    실제 카페 장소별 Google Places priceLevel로 카페비를 추정합니다. estimate_food_cost_from_places
    와 동일한 하이브리드 패턴이며, priceLevel을 못 구한 곳은 DEFAULT_CAFE_FEE_PER_PERSON으로 대체합니다.
    """

    total = 0
    for level in price_levels:
        per_person = GOOGLE_PRICE_LEVEL_TO_CAFE_KRW_PER_PERSON.get(level, DEFAULT_CAFE_FEE_PER_PERSON)
        total += per_person * people_count

    return total


def estimate_lodging_cost(people_count: int, nights: int = 1) -> int:
    return 50000 * people_count * nights


def estimate_admission_cost(
    people_count: int,
    place_fees: Optional[List[Optional[int]]] = None,
    default_fee_per_person: int = DEFAULT_ADMISSION_FEE_PER_PERSON,
) -> int:
    """
    place_fees(장소별 실제 이용요금, TourAPI usefee를 Upstage로 파싱한 결과)가 있으면
    그 값을 쓰고, 특정 장소의 요금을 못 구했으면(None) default_fee_per_person으로 대체합니다.
    place_fees 자체를 안 넘기면(예: 후보 목록이 없는 경우) 기본값 1곳 기준으로 계산합니다.
    """

    if not place_fees:
        return default_fee_per_person * people_count

    total = 0
    for fee in place_fees:
        per_person = fee if fee is not None else default_fee_per_person
        total += per_person * people_count

    return total


def build_cost_summary(
    transport_cost: int,
    people_count: int,
    days: int = 2,
    nights: int = 1,
    cafe_visits: int = 1,
    place_fees: Optional[List[Optional[int]]] = None,
    lodging_override: Optional[int] = None,
    meal_price_levels: Optional[List[Optional[str]]] = None,
    cafe_price_levels: Optional[List[Optional[str]]] = None,
) -> dict:
    """
    lodging_override(실제 숙박 후보의 detailInfo2 객실 요금 × 박수)가 있으면 그 값을 쓰고,
    없으면(숙박 후보가 없거나 요금 정보를 못 구함) 인원수·박수 기반 기본 추정치를 씁니다.
    meal_price_levels/cafe_price_levels(실제 식사·카페 장소별 Google Places priceLevel)가
    있으면 그걸로 식비/카페비를 계산하고, 없으면(후보가 없는 경우) 고정 단가를 씁니다.
    """

    food = (
        estimate_food_cost_from_places(people_count, meal_price_levels)
        if meal_price_levels
        else estimate_food_cost(people_count, days)
    )
    cafe = (
        estimate_cafe_cost_from_places(people_count, cafe_price_levels)
        if cafe_price_levels
        else estimate_cafe_cost(people_count, cafe_visits)
    )
    lodging = (
        lodging_override
        if lodging_override is not None
        else estimate_lodging_cost(people_count, nights)
    )
    admission = estimate_admission_cost(people_count, place_fees)

    total = transport_cost + food + cafe + lodging + admission

    return {
        "transport": transport_cost,
        "food": food,
        "cafe": cafe,
        "lodging": lodging,
        "admission": admission,
        "total": total,
        "currency": "KRW",
    }
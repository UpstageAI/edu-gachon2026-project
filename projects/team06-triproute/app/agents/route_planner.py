from __future__ import annotations

import math
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Tuple

from app.rag.retriever import retrieve_places_by_taste
from app.rag.vector_store import content_type_id_to_category, is_in_expected_region
from app.services.kakao_mobility import get_route, summarize_route
from app.services.supabase_client import get_course_content_ids
from app.services.tour_api import (
    TourAPIError,
    get_detail_common,
    get_detail_info,
    search_keyword,
)
from app.tools.mock_tools import run_tool
from app.utils.cache import cached_call
from app.utils.cost_rules import estimate_lodging_fee_per_night
from app.utils.transport_rules import estimate_public_transport_time

COURSE_CONTENT_TYPE_ID = "25"
# 코스 하위 장소는 "몇 일차"인지 구분이 없어서, 매칭된 장소 기준 코스 내 순서(subnum)로
# 이 범위 안에 있는 것만 연관 장소로 추천함 (며칠짜리 코스든 상관없이 먼 구간이 섞이는 것 방지)
COURSE_NEARBY_WINDOW = 2

LODGING_CATEGORY = "숙박"
LODGING_CONTENT_TYPE_ID = "32"

# TourAPI가 카라반/글램핑/캠핑장을 "숙박"(32)이 아니라 "레포츠"(28)로 등록해둔 경우가
# 실제로 있어서(예: "강릉 금진리321카라반", "OO글램핑" 등 category='레포츠'로 확인됨),
# category만으로 숙박 여부를 판단하면 실제로는 밤에 묵는 곳인데 오전/오후 같은 일반
# 관광 슬롯에 들어가 버린다. 이름에 이 키워드가 있으면 category와 무관하게 숙박으로 취급한다.
LODGING_NAME_KEYWORDS = ("카라반", "글램핑", "캠핑장", "캠핑리조트")


def _is_lodging_by_name(name: str) -> bool:
    return any(keyword in name for keyword in LODGING_NAME_KEYWORDS)


# 공항은 TourAPI에 "관광지"/"문화시설"로 등록돼 있어서(전망대·홍보관 등이 있다는 이유로)
# 취향 유사도나 리뷰수만 보면 순위가 높게 나오지만, 실제 여행 일정에서 "방문할 관광지"로
# 추천하기엔 부적절하다(그냥 오가는 경유지일 뿐). 이름에 "공항"이 들어가면 일반 후보군/
# 연관 장소 추천에서 제외한다.
NON_DESTINATION_NAME_KEYWORDS = ("공항",)


def _is_non_destination_by_name(name: str) -> bool:
    return any(keyword in name for keyword in NON_DESTINATION_NAME_KEYWORDS)


# TourAPI 여행코스(contentTypeId=25) 하위 장소 목록에는 실제 등록된 장소가 아니라
# "점심식사(용산회 식당)"처럼 코스 중 식사 시간을 나타내는 안내문 성격의 항목이 섞여
# 있는 경우가 실제로 있다(경주 코스에서 확인됨). 이런 항목은 content_id가 있어도
# 독립된 관광지가 아니라서 detailCommon2로 category를 못 채우고 None으로 남는데,
# 기존 숙박/음식점/쇼핑 제외 필터는 전부 "!= 카테고리" 비교라 None은 그대로 통과해서
# 오전 같은 일반 시간대에 식사 안내문이 관광지인 것처럼 배정되는 문제가 있었다.
MEAL_PLACEHOLDER_NAME_KEYWORDS = ("점심식사", "저녁식사", "아침식사", "조식", "중식", "석식")


def _is_meal_placeholder_by_name(name: str) -> bool:
    return any(keyword in name for keyword in MEAL_PLACEHOLDER_NAME_KEYWORDS)


RESTAURANT_CATEGORY = "음식점"
RESTAURANT_CONTENT_TYPE_ID = "39"
MEAL_TIME_SLOTS = {"점심", "저녁"}

# TourAPI의 "쇼핑"(38) 카테고리에는 재래시장("강릉 중앙시장")뿐 아니라 개별 브랜드
# 매장/아울렛("게스 제주점", "신세계사이먼프리미엄아울렛 OO점", "내셔널지오그래픽 제주점" 등)
# 까지 전부 섞여 있다. 후자는 사용자가 쇼핑을 요청하지 않는 한 관광 일정에 들어갈 이유가
# 없고(같은 브랜드가 지점만 다르게 여러 건 등록돼 후보를 도배하기도 함), 리뷰수가 높은
# 경우도 많아 일반 관광지 후보군에 자주 섞여 들어온다. 숙박/음식점과 같은 이유로 제외한다.
SHOPPING_CATEGORY = "쇼핑"

# 다만 재래시장은 쇼핑 카테고리로 등록돼 있어도 실제로는 관광객이 즐겨 찾는 명소(먹거리·
# 구경거리 위주)라 아울렛/브랜드 매장과 동일하게 취급하면 안 된다. 이름에 "시장"이 들어가면
# category가 "쇼핑"이어도 제외 대상에서 뺀다.
MARKET_NAME_KEYWORDS = ("시장",)


def _is_market_by_name(name: str) -> bool:
    return any(keyword in name for keyword in MARKET_NAME_KEYWORDS)


def _is_excluded_shopping(place: Place) -> bool:
    return place.get("category") == SHOPPING_CATEGORY and not _is_market_by_name(_get_place_name(place))

EARTH_RADIUS_KM = 6371.0
# RAG는 취향 유사도만 보고 거리는 전혀 고려하지 않아서, 취향 1등이 해변이고 2등이 반대편
# 산간 지역이면 그대로 비효율적인 동선이 짜일 수 있음. 이미 선택된 후보들로부터 이 거리
# 이내인 곳만 다음 후보로 인정해서 지리적으로 뭉치게 만든다.
MAX_CANDIDATE_DISTANCE_KM = 15.0


Place = Dict[str, Any]
RouteSegment = Dict[str, Any]


def _get_observation(tool_result: Any) -> Any:
    if isinstance(tool_result, dict):
        return (
            tool_result.get("observation")
            or tool_result.get("output")
            or tool_result
        )

    if hasattr(tool_result, "observation"):
        return tool_result.observation

    if hasattr(tool_result, "output"):
        return tool_result.output

    return tool_result


def _extract_list(tool_result: Any, *keys: str) -> List[Dict[str, Any]]:
    observation = _get_observation(tool_result)

    if isinstance(observation, list):
        return observation

    if isinstance(observation, dict):
        for key in keys:
            value = observation.get(key)
            if isinstance(value, list):
                return value

        for value in observation.values():
            if isinstance(value, list):
                return value

    return []


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad, lon1_rad, lat2_rad, lon2_rad = map(math.radians, (lat1, lon1, lat2, lon2))
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _filter_places_within_radius(
    places: List[Place],
    max_distance_km: float = MAX_CANDIDATE_DISTANCE_KM,
    anchor_places: List[Place] | None = None,
) -> List[Place]:
    """
    이미 선택된 장소들 중 하나에라도 max_distance_km 이내인 후보만 순서대로 추가한다
    (순차적 지리 군집화). RAG는 취향 유사도로만 순위를 매기고 거리는 안 보기 때문에,
    이 필터 없이는 취향 1등이 해변이고 2등이 반대편 산간 지역이어도 그대로 동선에
    들어가는 문제가 있었음.

    anchor_places를 넘기면 그 목록을 이미 확정된 군집 기준으로 삼아 places를 거르고
    (연관 관광지가 후보 군집과 동떨어지지 않게 하는 용도), 안 넘기면 places[0]을
    시작점으로 순차 군집을 새로 만든다(기존 RAG 후보 필터링 동작).

    좌표가 없는 장소(아직 _fill_missing_place_details 전이거나 조회 실패)는 거리
    판단이 불가능하므로 일단 포함시킨다 — 나중에 좌표가 채워지면 그 다음 판단에 반영됨.
    """

    if not places:
        return []

    if anchor_places is not None:
        selected: List[Place] = list(anchor_places)
        remaining = places
    else:
        selected = [places[0]]
        remaining = places[1:]

    for place in remaining:
        lat, lng = place.get("latitude"), place.get("longitude")

        if lat is None or lng is None:
            selected.append(place)
            continue

        located_selected = [
            s for s in selected
            if s.get("latitude") is not None and s.get("longitude") is not None
        ]

        if not located_selected:
            # 아직 좌표를 아는 후보가 하나도 없으면 거리 비교 자체가 불가능하니 통과시킨다
            selected.append(place)
            continue

        is_close_to_any = any(
            _haversine_km(lat, lng, s["latitude"], s["longitude"]) <= max_distance_km
            for s in located_selected
        )
        if is_close_to_any:
            selected.append(place)

    if anchor_places is not None:
        # anchor_places는 이미 확정된 목록이니, 그중에서 새로 통과한 것만 돌려준다
        return selected[len(anchor_places):]

    return selected


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_place_name(place: Place) -> str:
    return str(
        place.get("name")
        or place.get("place_name")
        or place.get("title")
        or place.get("related_place")
        or place.get("base_place")
        or "장소명 없음"
    ).strip()


def _format_place_signal(rating: Any, review_count: Any) -> str:
    """평점/리뷰수를 추천 이유 앞에 붙일 문장 조각으로 만든다. 둘 다 없으면 빈 문자열."""
    rating_value = _to_float(rating)

    if rating_value is not None and review_count is not None:
        return f"리뷰 {int(review_count):,}개, 평점 {rating_value:g}의 "
    if review_count is not None:
        return f"리뷰 {int(review_count):,}개의 "
    if rating_value is not None:
        return f"평점 {rating_value:g}의 "
    return ""


# 이 리뷰수 이상이면 추천 이유에 "인기"를 붙인다 (임의 기준 — 별도 통계적 근거는 없음)
POPULAR_REVIEW_COUNT_THRESHOLD = 300

OVERVIEW_SNIPPET_MAX_LENGTH = 60


# "OO는 경상북도 경주시 황남동에 위치한 생선구이 전문점이다"처럼 이름·주소·업종만
# 반복하는 문장에 흔히 나오는 표현. 주소는 이미 다른 필드로 따로 보여주므로, 추천
# 이유에서는 이런 문장을 건너뛰고 대표 메뉴·분위기·역사 등 실제 특징이 담긴 문장을 쓴다.
_LOCATION_BOILERPLATE_PATTERN = re.compile(r"위치한|위치해|자리하|자리잡|소재하")


def _extract_overview_snippet(overview: str | None, max_length: int = OVERVIEW_SNIPPET_MAX_LENGTH) -> str:
    """
    TourAPI overview(개요) 원문에서 추천 이유에 붙일 짧은 설명 한 조각을 뽑아낸다.

    overview는 보통 "(출처: OO)" 같은 출처 표기나 개행으로 문단이 나뉜 긴 소개문이라,
    그대로 붙이면 너무 길고 장황해진다. 위치 안내 문장은 건너뛰고, 실제 특징이 담긴
    문장(또는 max_length자)만 잘라 쓴다. 모든 문장이 위치 안내뿐이면 빈 문자열을 반환해
    "리뷰 OO개, 평점 OO의 맛집입니다."만으로 끝나게 한다.
    """
    if not overview:
        return ""

    text = overview.split("(출처")[0].replace("\n", " ").strip()
    if not text:
        return ""

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    sentence = next(
        (s for s in sentences if not _LOCATION_BOILERPLATE_PATTERN.search(s)),
        "",
    )
    if not sentence:
        return ""

    if len(sentence) > max_length:
        sentence = sentence[:max_length].rstrip() + "..."
    return sentence


# overview가 없을 때(TourAPI 실시간 검색 결과는 개요를 안 주는 searchKeyword2만 거쳐서
# overview가 비어 있는 경우가 많음) 쓰는 대체 문구. 장소별로 문구 자체가 똑같이 반복되는
# 느낌을 줄이려고 이름 해시로 그때그때 다른 표현을 고른다(같은 장소는 항상 같은 문구).
GENERIC_REASON_TEMPLATES = [
    "{category_text}인 곳으로, {style_text} 취향에 잘 맞습니다.",
    "{style_text} 취향이라면 가볼 만한 {category_text}입니다.",
    "{style_text} 취향에 어울리는 {category_text}로 추천드립니다.",
]


def _build_place_reason(
    category: str | None,
    rating: Any,
    review_count: Any,
    travel_style: List[str],
    prefer_local: bool = False,
    overview: str | None = None,
    name: str = "",
) -> str:
    """
    장소의 카테고리·평점·리뷰수·개요(overview)를 반영해 추천 이유를 장소별로 다르게 만든다.
    (기존에는 카테고리·취향만으로 만든 고정 템플릿이라, travel_style이 같으면 문장 뒷부분이
    모든 장소에서 토씨 하나 안 틀리고 똑같이 나왔음 — 사용자가 "다 똑같은 형식"이라고
    느낀 원인. overview가 있으면 그 장소만의 실제 소개 문구를 붙여서 실감나게 만든다.)

    숙박/음식점은 "OO 취향에 잘 맞습니다"라고 하면 사용자가 말한 취향과 억지로
    끼워맞춘 것처럼 읽혀서, 대신 평점·리뷰수만으로 그 장소가 어떤 곳인지 자연스럽게
    설명한다(예: "리뷰 686개, 평점 4.2의 맛집입니다", "편하게 쉬기 좋은 숙소입니다").

    prefer_local(로컬/한적한 곳 선호)이 켜져 있고 이 장소가 숨은 맛집 기준(평점
    HIDDEN_GEM_MIN_RATING 이상)을 만족하면, 리뷰수가 POPULAR_REVIEW_COUNT_THRESHOLD를
    넘더라도 "인기"를 붙이지 않는다 — prefer_local로 선택된 장소를 "인기 맛집"이라고
    설명하면 선택 이유와 문구가 서로 모순되기 때문이다.
    """
    category_text = category or "관광지"
    style_text = ", ".join(travel_style) if travel_style else "여행"
    signal = _format_place_signal(rating, review_count)
    snippet = _extract_overview_snippet(overview)

    review_count_value = review_count if isinstance(review_count, (int, float)) else 0
    rating_value = _to_float(rating)
    is_hidden_gem = prefer_local and rating_value is not None and rating_value >= HIDDEN_GEM_MIN_RATING
    popularity_prefix = (
        "인기 " if review_count_value >= POPULAR_REVIEW_COUNT_THRESHOLD and not is_hidden_gem else ""
    )

    if category == RESTAURANT_CATEGORY:
        base = f"{signal}{popularity_prefix}맛집입니다."
        return f"{base} {snippet}" if snippet else base

    if category == LODGING_CATEGORY:
        base = f"{signal}편하게 쉬기 좋은 숙소입니다."
        return f"{base} {snippet}" if snippet else base

    if snippet:
        return f"{signal}{snippet}"

    # 내장 hash()는 문자열의 경우 프로세스마다 랜덤 시드가 섞여 재현이 안 되므로,
    # 문자 코드 합으로 직접 안정적인 인덱스를 만든다(같은 이름은 항상 같은 문구).
    template_index = sum(ord(c) for c in name) % len(GENERIC_REASON_TEMPLATES)
    template = GENERIC_REASON_TEMPLATES[template_index]
    return signal + template.format(category_text=category_text, style_text=style_text)


def _normalize_tour_place(
    item: Dict[str, Any],
    source: str,
    travel_style: List[str],
) -> Place:
    """
    TourAPI searchKeyword2 결과를 Route Planner 내부 형식으로 변환한다.
    """
    title = str(item.get("title") or "장소명 없음").strip()
    category = content_type_id_to_category(item.get("contenttypeid"))

    return {
        "name": title,
        "title": title,
        "content_id": item.get("contentid"),
        "content_type_id": item.get("contenttypeid"),
        "address": item.get("addr1") or "",
        "longitude": _to_float(item.get("mapx")),
        "latitude": _to_float(item.get("mapy")),
        "area_code": item.get("lDongRegnCd") or item.get("areacode"),
        "signgu_code": (
            item.get("lDongSignguCd")
            or item.get("sigungucode")
        ),
        "image_url": item.get("firstimage") or "",
        "reason": _build_place_reason(category, None, None, travel_style, name=title),
        "source": source,
        "category": category,
        "rating": None,
        "review_count": None,
        "overview": "",
        "raw": item,
    }


def _build_taste_text(travel_style: List[str], prefer_local: bool) -> str:
    style_text = ", ".join(travel_style) if travel_style else "여행"

    if prefer_local:
        return f"{style_text}을(를) 좋아하고, 사람이 많이 몰리지 않는 로컬 분위기의 장소"

    return f"{style_text}을(를) 좋아하는 여행"


def _normalize_rag_place(
    item: Dict[str, Any], travel_style: List[str], prefer_local: bool = False
) -> Place:
    """
    match_places RPC 결과(Supabase places 테이블 행)를 Route Planner 내부 형식으로 변환한다.

    Supabase places 테이블에는 좌표(위도/경도)가 없어서 longitude/latitude는 일단 None으로
    두고, 이후 _fill_missing_place_details()에서 TourAPI로 보완한다.
    """
    title = str(item.get("title") or "장소명 없음").strip()
    category = item.get("category")
    rating = item.get("rating")
    review_count = item.get("review_count")
    overview = item.get("overview") or ""

    return {
        "name": title,
        "title": title,
        "content_id": item.get("content_id"),
        "address": item.get("address") or "",
        "longitude": _to_float(item.get("longitude")),
        "latitude": _to_float(item.get("latitude")),
        "area_code": None,
        "signgu_code": None,
        "image_url": "",
        "reason": _build_place_reason(
            category, rating, review_count, travel_style, prefer_local, overview=overview, name=title
        ),
        "source": "rag",
        "rating": rating,
        "review_count": review_count,
        "category": category,
        "similarity": item.get("similarity"),
        "overview": overview,
        "raw": item,
    }


# prefer_local일 때 "숨은 맛집"으로 인정할 평점 기준선. 이 미만이면 리뷰가 적어도
# "로컬 맛집"이 아니라 그냥 관리가 안 되거나 평판이 안 좋아서 리뷰가 적은 곳일 수 있다.
HIDDEN_GEM_MIN_RATING = 4.0


def _sort_by_prefer_local(places: List[Place], prefer_local: bool) -> List[Place]:
    """
    prefer_local이 켜져 있으면 "평점 HIDDEN_GEM_MIN_RATING 이상 + 리뷰 수 적음"(숨은 맛집)
    곳을 최우선으로 하고, 그 다음은 나머지를 review_count 적은 순으로 둔다. 그냥
    review_count만 오름차순으로 보면 평점도 낮은(관리가 안 되거나 평판이 나빠서 리뷰가
    적을 뿐인) 곳까지 "로컬 맛집"으로 뽑히는 문제가 있어서, 평점을 먼저 걸러 판단한다.

    prefer_local이 꺼져 있으면 기존과 동일하게 review_count가 많은(유명한) 곳을 우선한다.
    review_count가 없는(Google Places 매칭 실패) 곳은 정보 없음으로 취급해 배제하지
    않고 맨 뒤에 배치한다.
    """

    def sort_key(place: Place) -> Tuple[int, int]:
        review_count = place.get("review_count")
        if review_count is None:
            return (2, 0)

        if not prefer_local:
            return (0, -review_count)

        rating = _to_float(place.get("rating"))
        is_hidden_gem = rating is not None and rating >= HIDDEN_GEM_MIN_RATING
        return (0 if is_hidden_gem else 1, review_count)

    return sorted(places, key=sort_key)


# 좌표/카테고리는 한 번 조회하면 거의 안 바뀌는 데이터라 길게(7일) 캐싱한다 —
# 코스 캐시(course_detail_info)와 동일한 TTL을 씀.
DETAIL_COMMON_CACHE_TTL_SECONDS = 60 * 60 * 24 * 7

# get_detail_common 동시 호출 상한. TourAPI는 대량 동시 호출 시 429가 실제로 발생한
# 이력이 있어(docs/api_notes.md 참고) 무제한 병렬은 위험하고, 적당히 제한된 스레드풀로만
# 병렬화한다(순차 호출은 후보가 많으면 개당 ~2초씩 누적돼 한 번의 계획 생성에 1분 이상
# 걸리는 원인이었음 — 네트워크 대기가 대부분이라 병렬화 효과가 큼).
MAX_CONCURRENT_DETAIL_LOOKUPS = 6


def _fetch_detail_common_cached(content_id: str) -> Dict[str, Any]:
    return cached_call(
        namespace="detail_common",
        params={"content_id": content_id},
        fetch_fn=lambda: get_detail_common(content_id),
        ttl_seconds=DETAIL_COMMON_CACHE_TTL_SECONDS,
    )


def _fill_missing_place_details(places: List[Place]) -> List[Place]:
    """
    RAG 결과는 좌표/지역코드가 없으므로, 동선 계산과 연관 관광지 조회에 필요한
    mapx/mapy(좌표)·lDongRegnCd/lDongSignguCd(지역코드)를 TourAPI로 보완한다.
    코스 하위 장소(_normalize_course_sub_place)는 category도 없어서 같이 채운다
    (Financial Agent가 카테고리로 usefee/숙박 요금 조회 대상을 판단하는 데 필요).
    """

    targets = [
        place
        for place in places
        if place.get("content_id")
        and (place.get("latitude") is None or place.get("longitude") is None)
    ]

    if not targets:
        return places

    def _apply(place: Place) -> None:
        # TourAPIError뿐 아니라 캐시 파일 손상(json.JSONDecodeError/OSError) 등 예상치
        # 못한 예외까지 여기서 넓게 잡아야 한다 — 한 장소의 상세조회 실패가
        # executor.map 밖으로 전파되면 전체 trip-plan 요청이 그대로 죽어버린다
        # (real_api 분기가 동일한 실패 종류에 mock fallback을 두는 것과 대비됨).
        # 실패 시 lat/lng은 None으로 남기고 경고만 남긴 뒤 다음 장소로 넘어간다.
        try:
            detail = _fetch_detail_common_cached(place["content_id"])

            place["latitude"] = _to_float(detail.get("mapy"))
            place["longitude"] = _to_float(detail.get("mapx"))
            place["area_code"] = detail.get("lDongRegnCd") or detail.get("areacode")
            place["signgu_code"] = (
                detail.get("lDongSignguCd") or detail.get("sigungucode")
            )
            if not place.get("address"):
                place["address"] = detail.get("addr1") or ""
            if not place.get("image_url"):
                place["image_url"] = detail.get("firstimage") or ""
            if not place.get("category"):
                place["category"] = content_type_id_to_category(detail.get("contenttypeid"))

            # TourAPI에서 좌표를 받지 못한 경우 Google Places API로 Fallback
            if place.get("latitude") is None or place.get("longitude") is None:
                try:
                    from app.services.google_places_api import get_coordinates
                    search_name = place.get("name") or ""
                    search_addr = place.get("address") or detail.get("addr1") or ""
                    coords = get_coordinates(search_name, address=search_addr)
                    if coords["latitude"] is not None and coords["longitude"] is not None:
                        place["latitude"] = coords["latitude"]
                        place["longitude"] = coords["longitude"]
                except Exception as e:
                    print(f"[경고] Google Places 좌표 보완 실패 ({place.get('name')}): {e}")

            # 여행코스 하위 장소(subcontentid)는 가끔 TourAPI에 더 이상 등록되지 않은
            # (병합/삭제된) 오래된 content_id를 가리켜서 detailCommon2가 빈 응답({})을
            # 주는 경우가 실측으로 확인됐다 — "오죽헌", "태종대 전망대"처럼 실제로는
            # 유명하고 멀쩡한 관광지인데도 이 낡은 ID 때문에 category를 못 채워서, 이후
            # 필터가 "category를 모르니 안전하게 제외"하며 정작 좋은 추천을 놓치는
            # 문제가 있었다. content_id 하나만 죽은 것뿐 장소 자체는 유효하므로, 이름으로
            # 다시 검색해 살아있는 content_id/카테고리/좌표로 갱신을 시도한다.
            if not place.get("category") and place.get("source") == "course" and place.get("name"):
                try:
                    fresh_results = search_keyword(place["name"], num_of_rows=1, page_no=1)
                except TourAPIError:
                    fresh_results = []

                if fresh_results:
                    fresh = fresh_results[0]
                    place["content_id"] = fresh.get("contentid") or place.get("content_id")
                    place["category"] = content_type_id_to_category(fresh.get("contenttypeid"))
                    if not place.get("address"):
                        place["address"] = fresh.get("addr1") or ""
                    if not place.get("image_url"):
                        place["image_url"] = fresh.get("firstimage") or ""
                    if place.get("latitude") is None or place.get("longitude") is None:
                        place["latitude"] = _to_float(fresh.get("mapy"))
                        place["longitude"] = _to_float(fresh.get("mapx"))
        except Exception as e:
            print(f"[경고] 장소 상세정보 조회 실패 ({place.get('name')}): {e}")

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DETAIL_LOOKUPS) as executor:
        list(executor.map(_apply, targets))

    return places


def _search_rag_places(
    city: str,
    travel_style: List[str],
    prefer_local: bool,
    max_places: int,
) -> List[Place]:
    """
    Supabase RAG(pgvector 유사도 검색)로 도시 내 취향 매칭 관광지를 가져온다.
    실패하거나 결과가 없으면 빈 리스트를 반환해 호출자가 TourAPI 실시간 검색으로
    넘어갈 수 있게 한다.
    """

    taste_text = _build_taste_text(travel_style, prefer_local)

    try:
        # 숙박/음식점/공항은 아래에서 걸러내는데, "로컬 맛집"처럼 travel_style이 음식
        # 위주면 유사도 검색 결과 자체가 음식점(+숙박)이 절반 이상을 차지하는 경우가
        # 실측으로 확인됨(예: match_count 40개 중 음식점 20개, 숙박 5개). max_places의
        # 3배만 가져오면 필터링 후 관광지 슬롯을 채울 곳이 모자랄 수 있어 여유 있게 6배
        # 가져온다(Supabase pgvector 조회 1회라 비용 부담은 거의 없음).
        results = retrieve_places_by_taste(
            taste_text,
            match_count=max(max_places * 6, 20),
            city=city,
        )
    except Exception:
        return []

    if not results:
        return []

    places = _deduplicate_places(
        [_normalize_rag_place(item, travel_style, prefer_local) for item in results]
    )
    # 숙박은 일반 관광지 취향 유사도로 뽑히면 안 된다 — _search_lodging_place가 따로
    # 하나만 골라서 체크인 시점에 넣으므로, 여기 섞여 들어오면 호텔이 오전/오후 같은
    # 일반 활동 슬롯에 중복으로 배정되는 문제가 생긴다. category만으로는 카라반/글램핑/
    # 캠핑장처럼 TourAPI가 "레포츠"로 잘못 등록해둔 숙박까지는 못 걸러서 이름도 같이 본다.
    # 음식점도 마찬가지 이유로 제외한다 — 점심/저녁은 _search_restaurant_places가 따로
    # 채우므로, travel_style에 "로컬 맛집"처럼 음식 관련 표현이 있으면 여기서도 취향
    # 유사도로 음식점이 잔뜩 뽑혀서 _search_restaurant_places 결과와 대거 겹치고, 그
    # 중복이 뒤에서 dedup되며 오전/오후 관광지 슬롯을 채울 곳이 모자라지는 문제가 있었다.
    places = [
        place for place in places
        if place.get("category") != "숙박"
        and place.get("category") != RESTAURANT_CATEGORY
        and not _is_excluded_shopping(place)
        and not _is_lodging_by_name(_get_place_name(place))
        and not _is_non_destination_by_name(_get_place_name(place))
    ]

    # 위에서 match_count를 넉넉히(6배) 받아오지만, 이 함수가 반환하는 후보 전부가
    # 뒤에서 _fill_missing_place_details로 TourAPI 상세조회(좌표 보완)를 거친다 —
    # 필터링 후 남은 전량을 그대로 반환하면 후보가 많을수록 상세조회 호출 수·응답
    # 시간이 그만큼 늘어난다. max_places의 2배로만 잘라서, 필터링으로 인한 부족은
    # 보완하되 상세조회 부담은 기존 수준(3배 요청 시절)과 비슷하게 유지한다.
    return _sort_by_prefer_local(places, prefer_local)[: max_places * 2]


def _sort_by_rating_desc(places: List[Place]) -> List[Place]:
    """
    rating이 높은 순으로 정렬한다. rating이 없는(Google Places 매칭 실패) 곳은
    배제하지 않고 뒤쪽에 배치한다 (_sort_by_prefer_local과 동일한 None 처리 방식).
    """

    def sort_key(place: Place) -> Tuple[int, float]:
        rating = place.get("rating")
        if rating is None:
            return (1, 0.0)
        return (0, -rating)

    return sorted(places, key=sort_key)


# must_include 장소명 검색(searchKeyword2) 결과. 이름 자체는 자주 바뀌지 않으므로
# detail_common과 동일한 TTL(7일)로 캐싱해서 동일 도시+장소 조합의 반복 요청 시 재조회를 막는다.
MUST_INCLUDE_SEARCH_CACHE_TTL_SECONDS = DETAIL_COMMON_CACHE_TTL_SECONDS


def _resolve_must_include_place(
    p_name: str,
    city: str,
    travel_style: List[str],
) -> Place | None:
    """
    필수 방문지 이름 하나를 TourAPI searchKeyword2로 조회해 Place로 변환한다.
    도시명 + 장소명 조합으로 먼저 찾고, 결과가 없으면 장소명만으로 다시 찾는다.
    """
    try:
        search_res = cached_call(
            namespace="must_include_search",
            params={"city": city, "query": f"{city} {p_name}"},
            fetch_fn=lambda: search_keyword(f"{city} {p_name}", num_of_rows=3, page_no=1),
            ttl_seconds=MUST_INCLUDE_SEARCH_CACHE_TTL_SECONDS,
        )
        if not search_res:
            search_res = cached_call(
                namespace="must_include_search",
                params={"city": "", "query": p_name},
                fetch_fn=lambda: search_keyword(p_name, num_of_rows=3, page_no=1),
                ttl_seconds=MUST_INCLUDE_SEARCH_CACHE_TTL_SECONDS,
            )

        if search_res:
            return _normalize_tour_place(search_res[0], "tour_api", travel_style)
    except Exception:
        pass

    return None


def _fetch_lodging_fee(
    content_id: str,
    people_count: int,
    use_peak_season: bool,
) -> int | None:
    """
    숙박 후보의 실제 1박 요금을 조회한다. 계산 로직(인원수/성수기 반영)은
    cost_rules.estimate_lodging_fee_per_night에 있고 — Financial Agent와 동일한
    로직을 재사용해서 선택 시점과 최종 청구 시점의 판단이 어긋나지 않게 함 —
    여기서는 TourAPI 조회 + 캐싱만 담당한다. 캐시 namespace/params를 Financial
    Agent와 동일하게 맞춰서 같은 응답을 재사용한다(중복 호출 방지).
    """

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


def _search_lodging_place(
    city: str,
    anchor_places: List[Place],
    prefer_budget: bool = False,
    people_count: int = 1,
    is_peak_season: bool = False,
    travel_style: List[str] | None = None,
) -> Place | None:
    """
    1박 이상 여행일 때 숙박 후보를 하나 골라서 반환한다. RAG로 "숙박/호텔" 관련
    장소를 검색한 뒤, 이미 선택된 관광지 군집(anchor_places)과 15km 이내인 곳들 중
    고른다 — prefer_budget(Coordinator가 "가성비" 같은 예산 중시 의도를 인식해서
    넘기는 신호)이 켜져 있으면 실제 요금이 가장 저렴한 곳을, 아니면 rating이 가장
    높은 곳을 우선한다.

    정렬 후에는 그중 **실제 요금 데이터가 있는 첫 번째 후보**를 우선 선택한다 —
    예를 들어 평점 1등이 TourAPI에 객실 요금을 등록 안 해뒀으면, 정보 없는 곳
    대신 요금 데이터가 있는 다음 순위를 골라서 Financial Agent가 추정치가 아닌
    실측값을 쓸 수 있게 한다(동점/전부 데이터 없음이면 원래 1등을 그대로 씀).
    후보가 없으면 None을 반환해 Financial Agent가 기본 추정치로 대체하게 한다.
    """

    try:
        results = retrieve_places_by_taste(
            "편안하고 접근성 좋은 숙박 시설, 호텔, 펜션, 카라반, 글램핑, 캠핑장",
            match_count=20,
            city=city,
        )
    except Exception:
        results = []

    lodging_places = _deduplicate_places(
        [
            _normalize_rag_place(item, travel_style or [])
            for item in results
            # category가 "숙박"이 아니어도, 카라반/글램핑/캠핑장처럼 TourAPI가 "레포츠"로
            # 잘못 등록해둔 숙박은 이름으로 잡아서 후보에 포함시킨다.
            if item.get("category") == LODGING_CATEGORY
            or _is_lodging_by_name(str(item.get("title") or ""))
        ]
    )

    # RAG(Supabase 코퍼스)에 이 도시의 숙박이 아예 없거나(수집이 안 된 도시) 유사도
    # 임계값에 걸러지면, _search_rag_places처럼 TourAPI 실시간 검색으로 보충한다 —
    # 이게 없으면 체크인 일정이 조용히 통째로 빠지는 문제가 있었다.
    if not lodging_places:
        try:
            tour_items = search_keyword(
                keyword=city, content_type_id=LODGING_CONTENT_TYPE_ID, num_of_rows=20, page_no=1
            )
        except TourAPIError:
            tour_items = []

        lodging_places = _deduplicate_places(
            [
                _normalize_tour_place(item, "tour_api", travel_style or [])
                for item in tour_items
                if is_in_expected_region(city, item.get("addr1"))
            ]
        )

    if not lodging_places:
        return None

    # 이름 키워드로만 숙박 판정된 곳(원본 category가 "레포츠" 등)은 _normalize_rag_place가
    # 원본 category 기준으로 reason을 만들어서 "레포츠인 곳" 같은 문구가 남아있다 —
    # 여기서부터는 숙박으로 확정됐으니 reason도 숙박 문구로 다시 만든다.
    for place in lodging_places:
        if place.get("category") != LODGING_CATEGORY:
            place["reason"] = _build_place_reason(
                LODGING_CATEGORY,
                place.get("rating"),
                place.get("review_count"),
                travel_style or [],
                overview=place.get("overview"),
                name=_get_place_name(place),
            )

    lodging_places = _fill_missing_place_details(lodging_places)
    lodging_places = _filter_places_within_radius(
        lodging_places,
        anchor_places=anchor_places,
    )
    if not lodging_places:
        return None

    # get_detail_info 조회를 후보 개수만큼 순차 호출하면 후보마다 ~수 초씩 누적된다 —
    # _fill_missing_place_details와 동일한 스레드풀 패턴으로 병렬화한다.
    priced_places = [place for place in lodging_places if place.get("content_id")]
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DETAIL_LOOKUPS) as executor:
        fees = list(
            executor.map(
                lambda place: _fetch_lodging_fee(
                    place["content_id"], people_count, is_peak_season
                ),
                priced_places,
            )
        )
    fees_by_content_id = {
        place["content_id"]: fee for place, fee in zip(priced_places, fees)
    }

    if prefer_budget:
        ranked = sorted(
            lodging_places,
            key=lambda place: (
                fee
                if (fee := fees_by_content_id.get(place.get("content_id"))) is not None
                else float("inf")
            ),
        )
    else:
        ranked = _sort_by_rating_desc(lodging_places)

    for place in ranked:
        if fees_by_content_id.get(place.get("content_id")) is not None:
            return place

    return ranked[0]


def _search_restaurant_places(
    city: str,
    anchor_places: List[Place],
    max_restaurants: int,
    travel_style: List[str],
    prefer_local: bool = False,
) -> List[Place]:
    """
    점심/저녁 시간대에 배정할 음식점 후보를 명시적으로 확보한다.

    _search_rag_places는 취향 텍스트 전체와의 유사도만으로 후보를 뽑기 때문에, 사용자가
    "먹거리"를 취향으로 꼽아도 관광지/카페 쪽 텍스트가 더 유사하면 후보 풀에 음식점이
    하나도 안 뽑힐 수 있다. _reorder_places_for_time_slots는 이미 뽑힌 후보 중에서만
    음식점을 골라 점심/저녁 슬롯에 배치하므로, 애초에 후보 풀에 음식점이 없으면 아무리
    슬롯 배정을 잘해도 식사 시간대에 관광지가 그대로 들어가는 문제가 있었다.
    (_search_lodging_place가 숙박 후보를 별도로 확보하는 것과 동일한 이유로,
    음식점도 "취향 유사도 최상위 후보"에만 의존하지 않고 카테고리로 직접 검색해서
    확보한다.)
    """
    if max_restaurants <= 0:
        return []

    taste_text = _build_taste_text(travel_style + ["맛집", "음식점"], prefer_local=False)

    try:
        results = retrieve_places_by_taste(
            taste_text,
            match_count=max(max_restaurants * 3, 10),
            city=city,
        )
    except Exception:
        results = []

    restaurant_places = _deduplicate_places(
        [
            _normalize_rag_place(item, travel_style, prefer_local)
            for item in results
            if item.get("category") == RESTAURANT_CATEGORY
        ]
    )

    # _search_lodging_place와 동일한 이유로, RAG만으로는 필요한 슬롯 수(max_restaurants)를
    # 못 채울 수 있어 TourAPI 실시간 검색으로 보충한다 — 없으면 점심/저녁 슬롯 일부가
    # 조용히 일반 관광지로 채워지거나 통째로 비는 문제가 있었다(RAG가 아예 0개를 주는
    # 경우뿐 아니라, 필요한 개수보다 적게 주는 경우도 포함).
    if len(restaurant_places) < max_restaurants:
        try:
            tour_items = search_keyword(
                keyword=city,
                content_type_id=RESTAURANT_CONTENT_TYPE_ID,
                num_of_rows=max(20, max_restaurants * 5),
                page_no=1,
            )
        except TourAPIError:
            tour_items = []

        restaurant_places = _deduplicate_places(
            restaurant_places
            + [
                _normalize_tour_place(item, "tour_api", travel_style)
                for item in tour_items
                if is_in_expected_region(city, item.get("addr1"))
            ]
        )

    if not restaurant_places:
        return []

    restaurant_places = _fill_missing_place_details(restaurant_places)
    restaurant_places = _filter_places_within_radius(
        restaurant_places,
        anchor_places=anchor_places,
    )
    if not restaurant_places:
        return []

    restaurant_places = _sort_by_prefer_local(restaurant_places, prefer_local)

    return restaurant_places[:max_restaurants]


# "강릉불고기 본점"과 "강릉불고기 초당점"처럼 같은 브랜드가 지점명만 다르게 TourAPI에
# 중복 등록된 경우가 실제로 있어서, 이름 전체가 정확히 일치할 때만 잡는 방식으로는
# 못 걸러내고 일정에 같은 곳(다른 지점)이 두 번 들어가는 문제가 있었다. 마지막 단어가
# "점"으로 끝나면 지점명으로 보고 떼어내서 브랜드명만으로 비교한다.
def _strip_branch_suffix(name: str) -> str:
    tokens = name.split()
    if len(tokens) > 1 and tokens[-1].endswith("점"):
        return " ".join(tokens[:-1])
    return name


def _normalized_place_key(name: str) -> str:
    return re.sub(r"\s+", "", _strip_branch_suffix(name)).lower()


def _deduplicate_places(places: List[Place]) -> List[Place]:
    result: List[Place] = []
    seen: set[str] = set()

    for place in places:
        key = _normalized_place_key(_get_place_name(place))

        if not key or key == "장소명없음" or key in seen:
            continue

        seen.add(key)
        result.append(place)

    return result


def _parse_travel_days(duration: str) -> int:
    if "당일" in duration:
        return 1

    day_match = re.search(r"(\d+)\s*일", duration)
    if day_match:
        return max(1, int(day_match.group(1)))

    night_match = re.search(r"(\d+)\s*박", duration)
    if night_match:
        return max(1, int(night_match.group(1)) + 1)

    return 2


def _build_time_slots(
    travel_days: int,
    schedule_intensity: str,
    season: str = "",
    day_intensity_overrides: Dict[int, str] | None = None,
) -> List[Tuple[str, str]]:
    """
    하루 일정의 시간대 슬롯을 만든다.

    관광지 슬롯(오전/오후, 빡빡한 일정은 "늦은 오후" 추가)의 개수는 일정 강도로
    정해진다 — 빡빡한 일정=3개, 그 외(보통/여유로운 일정)=2개. 점심/저녁 식당
    슬롯은 일정 강도와 무관하게 항상 포함한다(관광지 개수와 별개로 늘 챙김).

    겨울은 일조시간이 짧아 저녁 시간대 야외 일정이 부담스러우므로 저녁 슬롯을 뺀다.
    (계절이 몇 시에 해가 지는지까지 정밀 반영하긴 어려우니, "저녁 슬롯 유무"라는 단순한
    방식으로 근사함 — 봄/여름/가을은 기존과 동일)

    여행 마지막 날은 저녁 전에 귀가/이동하는 경우가 많아 저녁 슬롯을 뺀다.

    day_intensity_overrides(예: {3: "여유로운 일정"})를 넘기면 그 일차만 전체 공통
    schedule_intensity 대신 지정된 값으로 관광지 슬롯 개수를 계산한다(daily_preferences
    지원용). 안 넘기면(기본값) 기존과 완전히 동일하게 모든 날짜가 schedule_intensity
    하나만 따른다.
    """
    is_short_daylight_season = "겨울" in season
    day_intensity_overrides = day_intensity_overrides or {}

    def build_day_slots(intensity: str, include_dinner: bool) -> List[str]:
        attraction_count = 3 if "빡빡" in intensity else 2
        slots = ["오전", "점심", "오후"]
        if attraction_count >= 3:
            slots.append("늦은 오후")
        if include_dinner:
            slots.append("저녁")
        return slots

    result: List[Tuple[str, str]] = []

    for day in range(1, travel_days + 1):
        day_intensity = day_intensity_overrides.get(day, schedule_intensity)
        is_last_day = travel_days > 1 and day == travel_days
        include_dinner = not is_short_daylight_season and not is_last_day
        slots = build_day_slots(day_intensity, include_dinner)

        for time_slot in slots:
            result.append((f"Day {day}", time_slot))

    return result


def _search_real_places(
    city: str,
    max_places: int,
    travel_style: List[str],
) -> List[Place]:
    items = search_keyword(
        keyword=city,
        num_of_rows=max(10, max_places * 2),
        page_no=1,
    )

    places = _deduplicate_places(
        [
            _normalize_tour_place(
                item=item,
                source="tour_api",
                travel_style=travel_style,
            )
            for item in items
        ]
    )
    # _search_rag_places와 동일한 이유로 숙박/음식점/쇼핑/공항은 일반 후보에서 제외한다.
    # searchKeyword2는 전국 대상 키워드 검색이라 "부산" 검색에 충북 옥천의 "부산식당" 같은
    # 동명 상호가 섞여 들어온다(ingest_city가 오프라인 수집 시 걸러내는 것과 동일한 문제) —
    # is_in_expected_region으로 주소가 실제 그 도시/지역 소속인지 확인해서 걸러낸다.
    return [
        place for place in places
        if place.get("category") != "숙박"
        and place.get("category") != RESTAURANT_CATEGORY
        and not _is_excluded_shopping(place)
        and not _is_lodging_by_name(_get_place_name(place))
        and not _is_non_destination_by_name(_get_place_name(place))
        and is_in_expected_region(city, place.get("address"))
    ]


def _normalize_course_sub_place(sub_item: Dict[str, Any], base_name: str) -> Place:
    """
    detailInfo2(여행코스 하위 장소 목록) 응답 항목을 Route Planner 내부 형식으로 변환한다.
    """
    title = str(sub_item.get("subname") or "장소명 없음").strip()

    return {
        "name": title,
        "title": title,
        "content_id": sub_item.get("subcontentid"),
        "address": "",
        "longitude": None,
        "latitude": None,
        "area_code": None,
        "signgu_code": None,
        "image_url": sub_item.get("subdetailimg") or "",
        "reason": f"{base_name}과(와) 같은 여행 코스에 포함된 연관 관광지입니다.",
        "source": "course",
        "rating": None,
        "review_count": None,
        "category": None,
        "raw": sub_item,
    }


def _search_course_related_places(
    candidate_places: List[Place],
    city: str,
    max_related_places: int,
) -> Tuple[List[Place], List[str]]:
    """
    선택된 관광지 후보가 TourAPI 여행코스(contentTypeId=25)의 하위 장소로 포함돼 있으면,
    같은 코스의 다른 장소들을 연관 관광지로 추천한다.

    (T맵 내비게이션 기반 "관광지별 연관 관광지" API는 제공 기간이 2025년 4월까지로 만료돼
    더 이상 데이터가 없어서, 대신 관광공사가 직접 큐레이션한 여행코스 데이터를 활용한다.)
    """

    related_places: List[Place] = []
    warnings: List[str] = []

    try:
        course_content_ids = get_course_content_ids(city)
    except Exception as exc:
        warnings.append(f"{city}: 여행코스 목록 조회 실패 ({exc})")
        return [], warnings

    if not course_content_ids:
        return [], warnings

    candidate_ids = {
        str(place["content_id"])
        for place in candidate_places
        if place.get("content_id")
    }

    # 순차 조회 + 조기 종료(매칭되면 바로 break) 방식이다. 코스 목록 앞쪽에서 매칭이
    # 나오는 경우가 흔해 대부분 한두 번의 호출로 끝나므로, get_detail_info를 전부
    # 미리 병렬로 당겨오는 것보다 불필요한 API 호출을 줄이는 이 방식을 택했다.
    # 다만 매칭이 늦게(또는 전혀) 나오는 최악의 경우엔 최대 20회의 콜드캐시 순차
    # 호출이 쌓일 수 있음 — 관광지 상세조회(_fill_missing_place_details)처럼
    # 병렬화하지 않은 트레이드오프를 여기 명시해 둔다.
    for course_id in course_content_ids:
        if len(related_places) >= max_related_places:
            break

        try:
            # 코스 구성은 관광공사가 큐레이션한 데이터라 자주 안 바뀌므로,
            # 요청마다 매번 재조회하지 않도록 길게(7일) 캐싱한다.
            sub_items = cached_call(
                namespace="course_detail_info",
                params={"content_id": course_id, "content_type_id": COURSE_CONTENT_TYPE_ID},
                fetch_fn=lambda cid=course_id: get_detail_info(cid, COURSE_CONTENT_TYPE_ID),
                ttl_seconds=60 * 60 * 24 * 7,
            )
        except TourAPIError as exc:
            warnings.append(f"여행코스 {course_id} 조회 실패: {exc}")
            continue

        matched_index = next(
            (
                i
                for i, item in enumerate(sub_items)
                if str(item.get("subcontentid")) in candidate_ids
            ),
            None,
        )
        if matched_index is None:
            continue

        base_name = str(sub_items[matched_index].get("subname") or "")

        # 코스 하위 장소 데이터에는 "몇 일차"인지 구분이 없고 순서(subnum)만 있어서,
        # 코스 전체를 추천하면 며칠짜리 코스든 상관없이 뒤쪽(다른 날짜용) 장소까지 섞여
        # 들어올 수 있음. 매칭된 장소 기준 코스 내 순서상 가까운 구간(앞뒤 COURSE_NEARBY_WINDOW개)
        # 만 근사치로 추천해서 이 문제를 줄인다.
        nearby_indexes = sorted(
            (
                i
                for i in range(len(sub_items))
                if i != matched_index
                and abs(i - matched_index) <= COURSE_NEARBY_WINDOW
            ),
            key=lambda i: abs(i - matched_index),
        )

        for i in nearby_indexes:
            if len(related_places) >= max_related_places:
                break

            sub_name = str(sub_items[i].get("subname") or "")
            if _is_non_destination_by_name(sub_name) or _is_meal_placeholder_by_name(sub_name):
                continue

            related_places.append(_normalize_course_sub_place(sub_items[i], base_name))

    return _deduplicate_places(related_places), warnings


def _unavailable_route(
    origin_name: str,
    destination_name: str,
    transport_mode: str,
) -> RouteSegment:
    return {
        "from": origin_name,
        "to": destination_name,
        "origin": origin_name,
        "destination": destination_name,
        "distance_km": 0.0,
        "car_minutes": 0,
        "estimated_time_minutes": 0,
        "estimated_time": "조회 실패",
        "transport_mode": transport_mode,
        "taxi_fare": 0,
        "toll_fare": 0,
        "is_estimated": True,
        "data_source": "unavailable",
        "memo": "이동 경로를 조회하지 못했습니다.",
    }


def _build_real_routes(
    selected_places: List[Place],
    transport_mode: str,
) -> Tuple[List[RouteSegment], List[str]]:
    routes: List[RouteSegment] = []
    warnings: List[str] = []

    for index in range(len(selected_places) - 1):
        origin = selected_places[index]
        destination = selected_places[index + 1]

        origin_name = _get_place_name(origin)
        destination_name = _get_place_name(destination)

        origin_lon = origin.get("longitude")
        origin_lat = origin.get("latitude")
        destination_lon = destination.get("longitude")
        destination_lat = destination.get("latitude")

        if None in (
            origin_lon,
            origin_lat,
            destination_lon,
            destination_lat,
        ):
            warnings.append(
                f"{origin_name} → {destination_name}: 좌표가 없습니다."
            )
            routes.append(
                _unavailable_route(
                    origin_name,
                    destination_name,
                    transport_mode,
                )
            )
            continue

        try:
            route = get_route(
                origin=(float(origin_lon), float(origin_lat)),
                destination=(
                    float(destination_lon),
                    float(destination_lat),
                ),
            )
            summary = summarize_route(route)
        except Exception as exc:
            warnings.append(
                f"{origin_name} → {destination_name}: "
                f"Kakao 경로 조회 실패 ({exc})"
            )
            routes.append(
                _unavailable_route(
                    origin_name,
                    destination_name,
                    transport_mode,
                )
            )
            continue

        car_minutes = int(summary["duration_min"])
        display_minutes = (
            estimate_public_transport_time(car_minutes)
            if transport_mode == "대중교통"
            else car_minutes
        )

        routes.append(
            {
                "from": origin_name,
                "to": destination_name,
                "origin": origin_name,
                "destination": destination_name,
                "distance_km": float(summary["distance_km"]),
                "car_minutes": car_minutes,
                "estimated_time_minutes": display_minutes,
                "estimated_time": f"약 {display_minutes}분",
                "transport_mode": transport_mode,
                "taxi_fare": int(summary["taxi_fare"]),
                "toll_fare": int(summary["toll_fare"]),
                "is_estimated": transport_mode == "대중교통",
                "data_source": "kakao_mobility",
                "memo": (
                    f"{origin_name}에서 {destination_name}까지 "
                    f"{transport_mode}으로 이동합니다."
                ),
            }
        )

    return routes, warnings


def _reorder_places_for_time_slots(
    selected_places: List[Place],
    time_slots: List[Tuple[str, str]],
) -> List[Place]:
    """
    점심/저녁 시간대에는 음식점 카테고리 장소를 우선 배정한다.
    (기존에는 selected_places를 시간대와 순서대로 그대로 zip해서, 식사 시간대에
    식당이 아니라 검색 순서상 먼저 나온 아무 장소나 배치되는 문제가 있었음)

    장소 개수와 시간대 개수가 다를 수 있어 selected_places 길이 기준으로만 슬롯을 본다
    (_build_daily_schedule도 동일하게 앞쪽 len(selected_places)개 슬롯만 사용함).
    """
    meal_indexes = [
        index
        for index, (_, time_slot) in enumerate(time_slots[: len(selected_places)])
        if time_slot in MEAL_TIME_SLOTS
    ]

    food_places = [p for p in selected_places if p.get("category") == RESTAURANT_CATEGORY]
    other_places = [p for p in selected_places if p.get("category") != RESTAURANT_CATEGORY]

    ordered: List[Place | None] = [None] * len(selected_places)
    remaining_meal_indexes = list(meal_indexes)

    for place in food_places:
        if remaining_meal_indexes:
            ordered[remaining_meal_indexes.pop(0)] = place
        else:
            # 식사 시간대가 이미 다 찼으면 나머지 일반 시간대에 배치한다
            other_places.append(place)

    empty_indexes = [index for index, place in enumerate(ordered) if place is None]
    for index, place in zip(empty_indexes, other_places):
        ordered[index] = place

    return [place for place in ordered if place is not None]


def _assemble_day_partitioned_places(
    candidate_places: List[Place],
    time_slots: List[Tuple[str, str]],
    related_places: List[Place],
    restaurant_places: List[Place],
    protected_indexes: set[int],
) -> List[Place]:
    """
    _search_day_partitioned_candidates 결과 전용 최종 배치(_reorder_places_for_time_slots
    대신 씀). candidate_places[i]가 이미 time_slots[i]에 정확히 대응되도록 날짜별로 만들어져
    있으므로, 일반 경로(_reorder_places_for_time_slots + candidate_count 절삭)를 그대로 쓰면
    뒤쪽 날짜의 후보가 절삭으로 사라지거나 다른 날짜 후보가 밀려 들어온다. 대신 인덱스를 그대로
    유지한 채 점심/저녁 자리만 식당으로 바꿔치기하고(protected_indexes에 있는 자리는 필수
    방문지가 이미 차지한 자리이므로 건너뜀), 검색이 슬롯을 다 못 채운 날짜(드문 폴백 소진
    상황)만 related_places로 뒤에서 보충한다.
    """
    max_places = len(time_slots)
    places = list(candidate_places[:max_places])

    if len(places) < max_places:
        for place in related_places:
            if len(places) >= max_places:
                break
            places.append(place)

    meal_indexes = [
        index
        for index, (_, time_slot) in enumerate(time_slots[: len(places)])
        if time_slot in MEAL_TIME_SLOTS and index not in protected_indexes
    ]
    restaurant_iter = iter(restaurant_places)
    for index in meal_indexes:
        restaurant = next(restaurant_iter, None)
        if restaurant is None:
            break
        places[index] = restaurant

    return _deduplicate_places(places)


def _build_daily_schedule(
    selected_places: List[Place],
    routes: List[RouteSegment],
    travel_days: int,
    schedule_intensity: str,
    travel_style: List[str],
    season: str = "",
    time_slots_override: List[Tuple[str, str]] | None = None,
    first_place_route_memo: str | None = None,
) -> List[Dict[str, Any]]:
    """
    time_slots_override를 넘기면 travel_days 전체를 다시 계산하지 않고 그 슬롯만 쓴다
    (기간 연장 후속 요청에서 늘어난 날짜분 슬롯만 배정할 때 사용, build_incremental_route_plan
    참고). first_place_route_memo를 넘기면 index==0 장소의 route_memo로 "여행의 첫 방문
    장소입니다" 대신 그 문구를 쓴다(늘어난 날짜의 첫 장소는 사실 전체 여행의 첫 방문이
    아니라 기존 마지막 장소에서 이어서 이동한 것이므로).
    """
    time_slots = time_slots_override or _build_time_slots(
        travel_days=travel_days,
        schedule_intensity=schedule_intensity,
        season=season,
    )

    schedule: List[Dict[str, Any]] = []

    for index, place in enumerate(selected_places[: len(time_slots)]):
        day, time_slot = time_slots[index]
        place_name = _get_place_name(place)

        if index == 0:
            route_memo = first_place_route_memo or "여행의 첫 방문 장소입니다."
        elif index - 1 < len(routes):
            route = routes[index - 1]
            route_memo = (
                f"{route['from']}에서 "
                f"{route['estimated_time']} 이동합니다."
            )
        else:
            route_memo = "이전 장소와의 동선을 고려해 배치했습니다."

        reason = place.get("reason")
        if not reason:
            reason = (
                f"{', '.join(travel_style)} 취향을 고려한 장소입니다."
                if travel_style
                else "여행 조건을 고려한 장소입니다."
            )

        schedule.append(
            {
                "day": day,
                "time_slot": time_slot,
                "place": place_name,
                "place_name": place_name,
                "reason": reason,
                "route_memo": route_memo,
                "address": place.get("address", ""),
                "image_url": place.get("image_url", ""),
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
                "content_id": place.get("content_id"),
                "source": place.get("source"),
                # 후속 요청(기간 연장/슬롯 교체)에서 previous_result만으로 이 장소의
                # 숙박/음식점 여부를 다시 판단할 수 있게 category/content_type_id도 남겨둔다
                # (Financial Agent의 _resolve_content_type_id가 이 두 필드로 판단함).
                "category": place.get("category"),
                "content_type_id": place.get("content_type_id"),
            }
        )

    return schedule


def _build_lodging_schedule_entry(
    lodging_place: Place,
    previous_place_name: str,
) -> Dict[str, Any]:
    place_name = _get_place_name(lodging_place)
    route_memo = "보통 체크인은 오후 2시경부터 가능합니다."
    if previous_place_name:
        route_memo = f"{previous_place_name}에서 이동해 체크인합니다. " + route_memo

    return {
        "day": "Day 1",
        "time_slot": "체크인",
        "place": place_name,
        "place_name": place_name,
        "reason": lodging_place.get("reason") or "숙박 체크인 장소입니다.",
        "route_memo": route_memo,
        "address": lodging_place.get("address", ""),
        "image_url": lodging_place.get("image_url", ""),
        # 카라반/글램핑/캠핑장처럼 원본 category가 "레포츠"로 잘못 등록돼 있어도, 이 함수까지
        # 왔다는 건 이미 숙박으로 확정됐다는 뜻이므로 원본 값과 무관하게 항상 "숙박"으로 남긴다
        # (후속 요청에서 previous_lodging_place를 category 기준으로 다시 찾을 때 필요).
        "category": LODGING_CATEGORY,
        "content_type_id": LODGING_CONTENT_TYPE_ID,
        "latitude": lodging_place.get("latitude"),
        "longitude": lodging_place.get("longitude"),
        "content_id": lodging_place.get("content_id"),
        "source": lodging_place.get("source"),
    }


def _insert_lodging_checkin(
    schedule: List[Dict[str, Any]],
    route_summary: List[RouteSegment],
    lodging_place: Place | None,
    transport_mode: str,
) -> Tuple[List[Dict[str, Any]], List[RouteSegment]]:
    """
    1일차 점심 슬롯 바로 뒤(보통 체크인 가능 시간인 오후 2시경)에 숙박 체크인
    일정을 한 번만 끼워 넣는다. 1일차에 점심 슬롯이 없으면(일정이 짧거나 슬롯이
    부족한 경우) 1일차의 마지막 일정 뒤에 넣는다.

    route_summary[i]는 schedule[i] -> schedule[i+1] 구간이라는 불변식을 후속 요청
    (슬롯 교체/장소 이동)이 그대로 의존하므로, schedule에 체크인 엔트리를 끼워 넣을
    때 route_summary도 같이 갱신한다 — 기존에 이 구간을 그대로 두면 체크인 지점
    이후 인덱스가 전부 하나씩 어긋나서 후속 요청이 엉뚱한 구간을 덮어쓰게 된다.
    """
    if not lodging_place:
        return schedule, route_summary

    insert_index = None
    for index, entry in enumerate(schedule):
        if entry["day"] == "Day 1" and entry["time_slot"] == "점심":
            insert_index = index + 1
            break

    if insert_index is None:
        day1_indexes = [index for index, entry in enumerate(schedule) if entry["day"] == "Day 1"]
        insert_index = (day1_indexes[-1] + 1) if day1_indexes else len(schedule)

    previous_place_name = schedule[insert_index - 1]["place_name"] if insert_index > 0 else ""
    checkin_entry = _build_lodging_schedule_entry(lodging_place, previous_place_name)
    checkin_place = _place_from_schedule_entry(checkin_entry)

    new_schedule = schedule[:insert_index] + [checkin_entry] + schedule[insert_index:]

    new_segments: List[RouteSegment] = []
    if insert_index > 0:
        prev_place = _place_from_schedule_entry(schedule[insert_index - 1])
        routes, _ = _build_real_routes(
            selected_places=[prev_place, checkin_place], transport_mode=transport_mode
        )
        new_segments.extend(routes)
    if insert_index < len(schedule):
        next_place = _place_from_schedule_entry(schedule[insert_index])
        routes, _ = _build_real_routes(
            selected_places=[checkin_place, next_place], transport_mode=transport_mode
        )
        new_segments.extend(routes)

    prefix = route_summary[: insert_index - 1] if insert_index > 0 else []
    suffix = route_summary[insert_index:]
    new_route_summary = list(prefix) + new_segments + list(suffix)

    return new_schedule, new_route_summary


# 하루 이동시간 합이 이 기준(분)을 넘으면 과밀 경고를 남긴다. "여유로운 일정"을 골랐는데
# 실제로는 이동만으로 하루가 빠듯하면 사용자 기대와 어긋나므로, 일정 강도별로 다르게 잡음.
RELAXED_DAILY_TRAVEL_LIMIT_MIN = 180
PACKED_DAILY_TRAVEL_LIMIT_MIN = 300


def _check_daily_density(
    daily_schedule: List[Dict[str, Any]],
    route_summary: List[RouteSegment],
    schedule_intensity: str,
) -> List[str]:
    """
    하루 단위로 구간 이동시간 합을 계산해서, 일정 강도 기준을 넘으면 경고를 남긴다.
    장소별 체류시간 데이터가 없어 반영은 못 하고, 구간 이동시간만으로 근사 판단한다.

    route_summary[i]는 daily_schedule[i] -> daily_schedule[i+1] 구간이므로, 그 이동을
    도착지가 속한 날짜("day")의 이동시간으로 집계한다.
    """

    limit_minutes = (
        RELAXED_DAILY_TRAVEL_LIMIT_MIN
        if "여유" in schedule_intensity
        else PACKED_DAILY_TRAVEL_LIMIT_MIN
    )

    day_to_minutes: Dict[str, int] = {}
    for index, route in enumerate(route_summary):
        if index + 1 >= len(daily_schedule):
            continue

        day = daily_schedule[index + 1].get("day", "")
        day_to_minutes[day] = day_to_minutes.get(day, 0) + int(
            route.get("estimated_time_minutes", 0)
        )

    warnings: List[str] = []
    for day, minutes in day_to_minutes.items():
        if minutes > limit_minutes:
            warnings.append(
                f"{day}: 이동시간 합이 약 {minutes}분으로 '{schedule_intensity}' 기준보다 "
                "빡빡할 수 있습니다."
            )

    return warnings


def _build_mock_fallback(
    parsed: Dict[str, Any],
    transport_mode: str,
) -> Dict[str, Any]:
    city = parsed.get("city", "강릉")
    travel_style = parsed.get("travel_style", [])

    search_result = run_tool(
        "search_places",
        {
            "city": city,
            "travel_style": travel_style,
        },
    )
    places = _extract_list(
        search_result,
        "places",
        "tourist_spots",
        "results",
    )

    related_result = run_tool(
        "get_related_places",
        {"places": places},
    )
    related_places = _extract_list(
        related_result,
        "related_places",
        "places",
        "results",
    )

    route_result = run_tool(
        "get_route_info",
        {
            "places": related_places,
            "transport_mode": transport_mode,
        },
    )
    route_summary = _extract_list(
        route_result,
        "route_segments",
        "route_summary",
        "routes",
    )

    schedule_places: List[Place] = list(places)

    for item in related_places:
        related_name = item.get("related_place")
        if related_name:
            schedule_places.append(
                {
                    "name": related_name,
                    "reason": item.get(
                        "relation_reason",
                        "연관 관광지입니다.",
                    ),
                    "source": "mock",
                }
            )

    travel_days = _parse_travel_days(
        str(parsed.get("duration") or "1박 2일")
    )
    schedule_intensity = str(
        parsed.get("schedule_intensity") or "보통"
    )
    season = str(parsed.get("season") or "")
    time_slots = _build_time_slots(
        travel_days,
        schedule_intensity,
        season=season,
    )

    daily_schedule: List[Dict[str, Any]] = []

    for index, place in enumerate(schedule_places[: len(time_slots)]):
        day, time_slot = time_slots[index]
        name = _get_place_name(place)

        daily_schedule.append(
            {
                "day": day,
                "time_slot": time_slot,
                "place": name,
                "place_name": name,
                "reason": place.get(
                    "reason",
                    "여행 조건을 고려한 장소입니다.",
                ),
                "route_memo": place.get(
                    "route_memo",
                    "이전 장소와의 동선을 고려해 배치했습니다.",
                ),
                "source": "mock",
            }
        )

    return {
        "tourist_spots": places,
        "candidate_places": places,
        "rag_ranked_places": [],
        "related_places": related_places,
        "selected_places": schedule_places,
        "route_summary": route_summary,
        "route_segments": route_summary,
        "daily_schedule": daily_schedule,
        "warnings": [
            "실제 TourAPI 호출 실패 또는 검색 결과 없음으로 "
            "Mock 데이터를 사용했습니다."
        ],
        "data_source": "mock",
    }


def _search_day_partitioned_candidates(
    city: str,
    time_slots: List[Tuple[str, str]],
    travel_style: List[str],
    prefer_local: bool,
    day_travel_style_overrides: Dict[int, List[str]],
    day_must_include_places: Dict[int, List[Place]] | None = None,
) -> Tuple[List[Place], str, set[int]]:
    """
    daily_preferences로 일차별 취향/필수 방문지가 지정된 경우("2일차는 액티비티 위주",
    "2일차에는 국립경주박물관 가고 싶어") 전용 후보 검색.

    day_travel_style_overrides에 없는 날짜는 전체 공통 travel_style을 그대로 쓴다.
    day 하나마다 그 날의 슬롯 수만큼만 별도로 취향 검색을 하고(단일 풀에서 순위대로
    나눠 갖는 기존 방식과 달리), 날짜 순서 그대로 이어붙인다 — _build_time_slots도
    Day 1, Day 2, ... 순서로 슬롯을 만들기 때문에, 이 순서를 맞춰야 뒤에서
    candidate_places[i]가 time_slots[i]에 정확히 대응된다.

    day_must_include_places에 그 날짜의 필수 방문지가 있으면 취향 검색보다 우선해서
    그 날짜 슬롯 맨 앞에 배치한다(슬롯 수를 넘으면 뒤쪽은 잘라낸다 — 날짜별 슬롯 수를
    넘겨서 다음 날짜 후보를 밀어내면 인덱스 정렬이 깨지기 때문). 나머지 슬롯만 기존과
    동일하게 취향 검색으로 채운다.

    반환값의 세 번째 원소(must_include_indexes)는 all_candidates 안에서 필수 방문지가
    자리한 절대 인덱스 집합이다 — 호출자(build_route_plan)가 나중에 점심/저녁 슬롯을
    식당으로 바꿔치기할 때, 그 자리가 이미 필수 방문지라면 덮어쓰지 않고 건너뛰는 데 쓴다
    (한 날짜에 필수 방문지를 2개 이상 지정했는데 그중 하나가 마침 점심 슬롯 위치에 오는
    경우를 보호하기 위함).

    지리적 군집화(_filter_places_within_radius)도 날짜 그룹마다 독립적으로 적용한다
    (전역 하나로 묶으면 "Day 2는 완전히 다른 지역의 액티비티"인 경우 Day 1 근처가 아니라는
    이유로 걸러질 수 있어서다). 이미 다른 날짜에서 뽑힌 장소는 중복으로 다시 안 뽑히게
    제외한다.
    """
    day_slot_counts: Dict[int, int] = {}
    day_order: List[int] = []
    for day_label, _ in time_slots:
        day = _day_number(day_label)
        if day not in day_slot_counts:
            day_order.append(day)
        day_slot_counts[day] = day_slot_counts.get(day, 0) + 1

    day_must_include_places = day_must_include_places or {}

    all_candidates: List[Place] = []
    must_include_indexes: set[int] = set()
    existing_keys: set[str] = set()
    data_sources: set[str] = set()
    # 날짜별 전용 취향으로 슬롯 수를 못 채우면(니치한 취향이라 후보가 적은 경우), 전체
    # 공통 취향으로 보충한다 — 안 그러면 이 날짜가 모자란 만큼 다음 날짜 후보가 앞으로
    # 당겨져서 daily_schedule 배정 시 날짜 정렬 자체가 깨진다(candidate_places[i]가
    # time_slots[i]에 그대로 대응되는 구조라서). 전체 공통 취향 보충분은 한 번만 조회해서
    # 재사용한다.
    fallback_candidates: List[Place] | None = None

    def _exclude_existing(places: List[Place]) -> List[Place]:
        return [p for p in places if _normalized_place_key(_get_place_name(p)) not in existing_keys]

    for day in day_order:
        slot_count = day_slot_counts[day]
        day_style = day_travel_style_overrides.get(day, travel_style)

        day_musts = _exclude_existing(day_must_include_places.get(day, []))[:slot_count]
        for place in day_musts:
            existing_keys.add(_normalized_place_key(_get_place_name(place)))

        remaining_slot_count = slot_count - len(day_musts)

        if remaining_slot_count > 0:
            rag_places = _exclude_existing(
                _search_rag_places(
                    city=city, travel_style=day_style, prefer_local=prefer_local,
                    max_places=remaining_slot_count,
                )
            )
            if rag_places:
                day_candidates = _fill_missing_place_details(rag_places)
                data_sources.add("rag")
            else:
                try:
                    day_candidates = _exclude_existing(
                        _search_real_places(
                            city=city, max_places=remaining_slot_count, travel_style=day_style
                        )
                    )
                    data_sources.add("real_api")
                except Exception:
                    day_candidates = []

            if day_candidates:
                day_candidates = _filter_places_within_radius(day_candidates)

            day_candidates = day_candidates[:remaining_slot_count]
            for place in day_candidates:
                existing_keys.add(_normalized_place_key(_get_place_name(place)))

            if len(day_candidates) < remaining_slot_count:
                if fallback_candidates is None:
                    fallback_rag = _search_rag_places(
                        city=city, travel_style=travel_style, prefer_local=prefer_local,
                        max_places=len(time_slots),
                    )
                    fallback_candidates = (
                        _fill_missing_place_details(fallback_rag) if fallback_rag else []
                    )
                    data_sources.add("rag" if fallback_rag else "real_api")

                for place in fallback_candidates:
                    if len(day_candidates) >= remaining_slot_count:
                        break
                    key = _normalized_place_key(_get_place_name(place))
                    if key in existing_keys:
                        continue
                    day_candidates.append(place)
                    existing_keys.add(key)
        else:
            day_candidates = []

        must_include_indexes.update(
            range(len(all_candidates), len(all_candidates) + len(day_musts))
        )
        all_candidates.extend(day_musts + day_candidates)

    if "rag" in data_sources:
        data_source = "rag"
    elif "real_api" in data_sources:
        data_source = "real_api"
    else:
        data_source = "mock"

    return all_candidates, data_source, must_include_indexes


def build_route_plan(
    parsed: Dict[str, Any],
    transport_mode: str,
    people_count: int,
) -> Dict[str, Any]:
    """
    Route Planner Agent.

    TourAPI 관광지 조회
    → 연관 관광지 조회
    → Kakao Mobility 경로 조회
    → 일정 생성
    → 실패 시 Mock fallback
    """

    city = str(parsed.get("city") or "강릉")
    duration = str(parsed.get("duration") or "1박 2일")
    travel_style = list(parsed.get("travel_style") or [])
    prefer_local = bool(parsed.get("prefer_local", False))
    prefer_budget = bool(parsed.get("prefer_budget", False))
    is_peak_season = bool(parsed.get("is_peak_season", False))
    schedule_intensity = str(
        parsed.get("schedule_intensity") or "보통"
    )
    season = str(parsed.get("season") or "")

    # "1일차는 바다/카페, 2일차는 액티비티, 마지막날은 여유롭게"처럼 처음 계획할 때만
    # 지원되는 일차별 오버라이드(daily_preferences). 언급 안 된 날짜는 이 두 dict에
    # 아예 없으므로, 아래에서 .get(day, 전체공통값)로 자연스럽게 전체 공통값을 따른다.
    daily_preferences = list(parsed.get("daily_preferences") or [])
    day_intensity_overrides = {
        pref["day"]: pref["schedule_intensity"]
        for pref in daily_preferences
        if pref.get("schedule_intensity")
    }
    day_travel_style_overrides = {
        pref["day"]: pref["travel_style"]
        for pref in daily_preferences
        if pref.get("travel_style")
    }
    # "2일차에는 국립경주박물관 가고 싶어"처럼 처음 계획할 때 며칠차인지와 함께 지정된
    # 필수 방문지 이름(장소 이름 자체는 아래에서 _resolve_must_include_place로 해석).
    day_must_include_names = {
        pref["day"]: list(pref["must_include_places"])
        for pref in daily_preferences
        if pref.get("must_include_places")
    }

    travel_days = _parse_travel_days(duration)
    time_slots = _build_time_slots(
        travel_days,
        schedule_intensity,
        season=season,
        day_intensity_overrides=day_intensity_overrides,
    )
    max_places = len(time_slots)

    must_include_names = list(parsed.get("must_include_places") or [])
    must_include_places_list = []

    if must_include_names:
        # 이름별로 캐싱된 검색을 병렬로 실행한다(_fill_missing_place_details와 동일한
        # 스레드풀 패턴). executor.map은 입력 순서를 보존하므로 must_include_names
        # 순서 그대로 결과가 나온다.
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DETAIL_LOOKUPS) as executor:
            resolved_places = list(
                executor.map(
                    lambda p_name: _resolve_must_include_place(p_name, city, travel_style),
                    must_include_names,
                )
            )
        must_include_places_list = [place for place in resolved_places if place is not None]

    day_must_include_places: Dict[int, List[Place]] = {}
    if day_must_include_names:
        # 날짜별 필수 방문지도 must_include_names와 동일하게 병렬로 이름을 해석한다.
        # (day, name) 쌍으로 펼쳐서 한 번에 조회하고, 결과를 다시 날짜별로 묶는다.
        flat_requests = [
            (day, p_name)
            for day, p_names in day_must_include_names.items()
            for p_name in p_names
        ]
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DETAIL_LOOKUPS) as executor:
            resolved = list(
                executor.map(
                    lambda req: _resolve_must_include_place(req[1], city, travel_style),
                    flat_requests,
                )
            )
        for (day, _p_name), place in zip(flat_requests, resolved):
            if place is not None:
                day_must_include_places.setdefault(day, []).append(place)

    is_day_partitioned = bool(day_travel_style_overrides or day_must_include_places)
    day_must_include_indexes: set[int] = set()

    if is_day_partitioned:
        # daily_preferences로 일차별 취향/필수 방문지가 지정된 경우: 날짜 그룹별로 따로
        # 검색하고 날짜 순서대로 이어붙인다. 이 경로는 그룹마다 이미 지리적 군집화가
        # 끝났으므로(아래 else 분기의) 전역 재필터링은 다시 거치지 않는다.
        candidate_places, data_source, day_must_include_indexes = _search_day_partitioned_candidates(
            city=city,
            time_slots=time_slots,
            travel_style=travel_style,
            prefer_local=prefer_local,
            day_travel_style_overrides=day_travel_style_overrides,
            day_must_include_places=day_must_include_places,
        )

        if not candidate_places:
            return _build_mock_fallback(
                parsed=parsed,
                transport_mode=transport_mode,
            )

        if must_include_places_list:
            existing_names = {p["name"] for p in candidate_places}
            for mp in reversed(must_include_places_list):
                if mp["name"] not in existing_names:
                    candidate_places.insert(0, mp)
                    existing_names.add(mp["name"])
                    # 맨 앞에 하나 꽂을 때마다 뒤 인덱스가 전부 한 칸씩 밀리므로,
                    # day_must_include_indexes로 지켜둔 위치도 같이 밀어줘야
                    # 나중에 엉뚱한 자리(다른 날짜 슬롯)를 보호하는 사고가 안 난다.
                    day_must_include_indexes = {i + 1 for i in day_must_include_indexes}

        # rag_ranked_places는 응답에 그대로 노출되는 필드라 이 경로에서도 채워야 한다 —
        # 날짜별로 여러 번 검색해서 단일 "원본 RAG 순위" 개념이 없으므로, data_source가
        # rag였을 때의 candidate_places를 그대로 대체 값으로 쓴다.
        rag_places = candidate_places if data_source == "rag" else []
    else:
        rag_places = _search_rag_places(
            city=city,
            travel_style=travel_style,
            prefer_local=prefer_local,
            max_places=max_places,
        )

        if rag_places:
            candidate_places = _fill_missing_place_details(rag_places)
            data_source = "rag"
        else:
            try:
                candidate_places = _search_real_places(
                    city=city,
                    max_places=max_places,
                    travel_style=travel_style,
                )
                data_source = "real_api"
            except Exception:
                return _build_mock_fallback(
                    parsed=parsed,
                    transport_mode=transport_mode,
                )

        # must_include 장소들을 최우선순위(맨 앞)에 추가
        if must_include_places_list:
            # 중복 방지 (이름 또는 content_id 기준)
            existing_names = {p["name"] for p in candidate_places}
            for mp in reversed(must_include_places_list):
                if mp["name"] not in existing_names:
                    candidate_places.insert(0, mp)
                    existing_names.add(mp["name"])

        # 취향 순위만으로 뽑으면 서로 멀리 떨어진 장소가 섞여 동선이 비효율적일 수 있어서,
        # 취향 1등 기준으로 지리적으로 뭉친 후보만 남긴다 (순위는 그대로 유지됨)
        # 단, must_include 장소는 무조건 유지하도록 처리

        def _filter_with_must_include(candidates: List[Place], must_includes: List[Place]) -> List[Place]:
            filtered = _filter_places_within_radius(candidates)
            # 제주도처럼 관광지가 넓게 퍼진 지역은 15km 반경 군집화를 그대로 적용하면
            # 취향 1등 근처 소수만 남고 나머지 날짜를 채울 후보가 통째로 사라진다
            # (실측: 제주 8개 후보 → 반경 필터 후 3개, 3일 일정(12슬롯)의 Day 2/3가
            # 통째로 빔). 필터링 결과가 원래 후보 수와 필요한 슬롯 수(max_places) 중
            # 작은 쪽에도 못 미치면, 지리적 군집화보다 "일정을 채우는 것"을 우선해서
            # 필터링 전 전체 후보로 되돌린다(취향 순위는 그대로 유지됨).
            if len(filtered) < min(len(candidates), max_places):
                filtered = list(candidates)
            # filtered에 필수 장소가 빠졌다면 다시 강제 추가
            filtered_names = {f["name"] for f in filtered}

            for m in must_includes:
                if m["name"] not in filtered_names:
                    filtered.insert(0, m)
                    filtered_names.add(m["name"])
            return filtered

        candidate_places = _filter_with_must_include(candidate_places, must_include_places_list)

    if not candidate_places:
        return _build_mock_fallback(
            parsed=parsed,
            transport_mode=transport_mode,
        )

    related_places, related_warnings = (
        _search_course_related_places(
            candidate_places=candidate_places,
            city=city,
            max_related_places=max(1, max_places // 3),
        )
    )
    related_places = _fill_missing_place_details(related_places)
    # 코스 하위 장소는 category가 매칭 전엔 None이라 여기서 채워지기 전까진 걸러낼 수
    # 없었다 — _search_rag_places/_search_real_places와 동일하게, 채워진 category가
    # 숙박/음식점/쇼핑인 곳은 일반 관광지 슬롯에 들어가면 안 되므로 제외한다.
    #
    # category가 detailCommon2 조회 후에도 여전히 None이면 제외한다 — 실제 사례로
    # "점심식사(용산회 식당)"처럼 코스 데이터에 실제 등록된 장소가 아니라 안내문 성격의
    # 항목이 섞여 있어서(_is_meal_placeholder_by_name으로 이름 패턴은 먼저 걸러내지만,
    # 아직 못 걸러낸 다른 패턴의 안내문 항목도 있을 수 있음) content_id가 있어도 category를
    # 못 채우는 경우가 실측으로 확인됐다. category를 못 정한 곳은 숙박/음식점인지도 알 수
    # 없어 안전하게 제외하는 편이 낫다.
    related_places = [
        place for place in related_places
        if place.get("category") is not None
        and place.get("category") != LODGING_CATEGORY
        and place.get("category") != RESTAURANT_CATEGORY
        and not _is_excluded_shopping(place)
        and not _is_lodging_by_name(_get_place_name(place))
    ]
    # 코스에서 붙는 연관 장소도 후보 군집(candidate_places)과 동떨어지지 않게 거리 필터를 통과시킨다
    related_places = _filter_places_within_radius(
        related_places,
        anchor_places=candidate_places,
    )

    # candidate_places/related_places는 취향 유사도 순위만으로 뽑혀서 음식점이 하나도
    # 안 섞여 있을 수 있다 — 점심/저녁 슬롯 수만큼 음식점 후보를 별도로 확보해서
    # _reorder_places_for_time_slots가 실제로 배정할 대상이 있게 한다.
    meal_slot_count = sum(1 for _, time_slot in time_slots if time_slot in MEAL_TIME_SLOTS)
    restaurant_places = _search_restaurant_places(
        city=city,
        anchor_places=candidate_places,
        max_restaurants=meal_slot_count,
        travel_style=travel_style,
        prefer_local=prefer_local,
    )

    if is_day_partitioned:
        # 날짜별로 그 날의 슬롯 수만큼만 뽑아 순서대로 이어붙인 리스트라
        # candidate_places[i]가 이미 time_slots[i]에 정확히 대응된다. 아래 else 분기의
        # "candidate_count만큼만 남기고 나머지는 related/restaurant로 채운다" 방식을
        # 그대로 쓰면 뒤쪽 날짜(늦은 Day)의 후보가 prefix 절삭으로 통째로 잘려나가고,
        # 그 자리를 restaurant_places가 순서 없이 메우면서 날짜 정렬 자체가 깨진다
        # (실측: "2일차에 덕수궁 가고 싶어"가 절삭으로 사라지고 1일차 후보가 2일차
        # 자리까지 밀려 들어옴). 인덱스를 그대로 유지한 채 점심/저녁 자리만 식당으로
        # 바꿔치기하고, 필수 방문지가 이미 차지한 자리(day_must_include_indexes)는
        # 보호해서 덮어쓰지 않는다.
        selected_places = _assemble_day_partitioned_places(
            candidate_places=candidate_places,
            time_slots=time_slots,
            related_places=related_places,
            restaurant_places=restaurant_places,
            protected_indexes=day_must_include_indexes,
        )
    else:
        # related_places(코스에 같이 묶여 있다는 이유만으로 뽑힌 연관 관광지)는
        # travel_style/테마 적합성을 전혀 안 보고 뽑힌다 — 예전에는 여기서 무조건
        # 자리를 마련해(candidate_count를 미리 줄여서) 끼워 넣다 보니, 취향에 맞는
        # 후보가 있는데도 밀어내고 "역사답사" 여행에 테마와 무관한 코스 동반 장소가
        # 그냥 꽂히는 문제가 있었다. restaurant_places(취향 검색을 거친 음식점)만
        # 자리를 예약하고, related_places는 뒤에 붙여서 취향 후보+식당만으로
        # max_places가 다 안 채워지는 경우에만(즉 진짜 빈자리가 남을 때만) 잘리지
        # 않고 살아남게 한다.
        candidate_count = max(1, max_places - len(restaurant_places))
        selected_places = _deduplicate_places(
            candidate_places[:candidate_count]
            + restaurant_places
            + related_places
        )[:max_places]
        selected_places = _reorder_places_for_time_slots(selected_places, time_slots)

    route_summary, route_warnings = _build_real_routes(
        selected_places=selected_places,
        transport_mode=transport_mode,
    )

    daily_schedule = _build_daily_schedule(
        selected_places=selected_places,
        routes=route_summary,
        travel_days=travel_days,
        schedule_intensity=schedule_intensity,
        travel_style=travel_style,
        season=season,
        # 위에서 이미 day_intensity_overrides까지 반영해서 만든 time_slots를 그대로 넘긴다 —
        # 안 넘기면 _build_daily_schedule이 내부적으로 전체 공통 schedule_intensity만으로
        # 슬롯을 다시 계산해버려서, 일차별 일정 강도 오버라이드가 있을 때 위에서 계산한
        # candidate 개수/슬롯 배정과 실제 daily_schedule 슬롯 구조가 어긋나게 된다.
        time_slots_override=time_slots,
    )

    density_warnings = _check_daily_density(
        daily_schedule=daily_schedule,
        route_summary=route_summary,
        schedule_intensity=schedule_intensity,
    )

    if "겨울" in season:
        density_warnings.append(
            "겨울철은 일조시간이 짧아 저녁 시간대 일정을 제외했습니다."
        )

    # 1박 이상이면 숙박 후보를 명시적으로 하나 골라둔다 (RAG가 우연히 숙박을 관광지
    # 후보로 뽑아주길 기다리지 않고, Financial Agent가 실제 요금을 조회할 대상을 보장함).
    # 실제 일정에는 관광지처럼 여러 시간대에 걸쳐 등장하면 안 되므로, 1일차 체크인
    # (보통 오후 2시경 가능) 시점에 한 번만 넣는다.
    lodging_place = (
        _search_lodging_place(
            city=city,
            anchor_places=candidate_places,
            prefer_budget=prefer_budget,
            people_count=people_count,
            is_peak_season=is_peak_season,
            travel_style=travel_style,
        )
        if travel_days > 1
        else None
    )
    daily_schedule, route_summary = _insert_lodging_checkin(
        daily_schedule, route_summary, lodging_place, transport_mode
    )

    return {
        "tourist_spots": candidate_places,
        "candidate_places": candidate_places,
        "rag_ranked_places": rag_places,
        "related_places": related_places,
        "selected_places": selected_places,
        "route_summary": route_summary,
        "route_segments": route_summary,
        "daily_schedule": daily_schedule,
        "lodging_place": lodging_place,
        "season": season,
        "is_peak_season": is_peak_season,
        "warnings": related_warnings + route_warnings + density_warnings,
        "data_source": data_source,
    }


def _day_number(day_label: str) -> int:
    match = re.search(r"(\d+)", day_label or "")
    return int(match.group(1)) if match else 0


def _place_from_schedule_entry(entry: Dict[str, Any]) -> Place:
    """
    previous_result(finalize_node 결과)의 daily_schedule 엔트리 하나를 Route Planner
    내부 Place 형식으로 되살린다. 후속 요청(기간 연장/슬롯 교체)에서 Financial Agent가
    전체 일정 기준으로 비용을 다시 계산할 수 있게 category/content_type_id까지 포함해서
    복원한다(_build_daily_schedule/_build_lodging_schedule_entry가 남겨둔 필드 기준).
    """
    return {
        "name": entry.get("place_name", ""),
        "title": entry.get("place_name", ""),
        "content_id": entry.get("content_id"),
        "address": entry.get("address", ""),
        "latitude": entry.get("latitude"),
        "longitude": entry.get("longitude"),
        "image_url": entry.get("image_url", ""),
        "category": entry.get("category"),
        "content_type_id": entry.get("content_type_id"),
        "source": entry.get("source"),
    }


def build_incremental_route_plan(
    parsed: Dict[str, Any],
    transport_mode: str,
    people_count: int,
    previous_result: Dict[str, Any],
    previous_days: int,
) -> Dict[str, Any]:
    """
    기간 연장("3일로 늘려줘") 후속 요청 전용 Route Planner.

    build_route_plan을 처음부터 다시 돌리면 이미 확정된 Day 1..previous_days의 장소까지
    통째로 다른 곳으로 바뀌는 문제가 있었다. 대신 기존 daily_schedule/route_summary는
    그대로 두고, 늘어난 날짜만큼의 시간대 슬롯만 새로 채워서 뒤에 이어붙인다.

    새 날짜 후보에 필요한 정보(좌표 기반 지리적 군집, 기존 장소와의 중복 제외)는 previous_result
    (finalize_node가 만든 결과 형태: daily_schedule/route_summary만 있고 selected_places/
    lodging_place는 없음)의 daily_schedule 엔트리에서 재구성한다.
    """
    previous_daily_schedule = list(previous_result.get("daily_schedule") or [])
    previous_route_summary = list(previous_result.get("route_summary") or [])

    if not previous_daily_schedule:
        return build_route_plan(
            parsed=parsed, transport_mode=transport_mode, people_count=people_count
        )

    city = str(parsed.get("city") or "강릉")
    duration = str(parsed.get("duration") or "1박 2일")
    travel_style = list(parsed.get("travel_style") or [])
    prefer_local = bool(parsed.get("prefer_local", False))
    schedule_intensity = str(parsed.get("schedule_intensity") or "보통")
    season = str(parsed.get("season") or "")

    total_days = _parse_travel_days(duration)
    all_time_slots = _build_time_slots(total_days, schedule_intensity, season=season)
    new_time_slots = [
        slot for slot in all_time_slots if _day_number(slot[0]) > previous_days
    ]

    if not new_time_slots:
        # 파싱 오류 등으로 실제로는 기간이 늘지 않았으면 처음부터 다시 계획해 안전하게 대체한다.
        return build_route_plan(
            parsed=parsed, transport_mode=transport_mode, people_count=people_count
        )

    max_new_places = len(new_time_slots)

    # 좌표가 있는 기존 확정 장소만 새 후보의 지리적 군집 기준점으로 쓴다.
    anchor_places = [
        entry
        for entry in previous_daily_schedule
        if entry.get("latitude") is not None and entry.get("longitude") is not None
    ]
    last_existing_entry = previous_daily_schedule[-1]
    existing_keys = {
        _normalized_place_key(entry.get("place_name") or "")
        for entry in previous_daily_schedule
    }

    def _exclude_existing(places: List[Place]) -> List[Place]:
        return [p for p in places if _normalized_place_key(_get_place_name(p)) not in existing_keys]

    rag_places = _exclude_existing(
        _search_rag_places(
            city=city,
            travel_style=travel_style,
            prefer_local=prefer_local,
            max_places=max_new_places,
        )
    )

    if rag_places:
        candidate_places = _fill_missing_place_details(rag_places)
        data_source = previous_result.get("condition_summary", {}).get("data_source", "rag")
    else:
        try:
            candidate_places = _exclude_existing(
                _search_real_places(city=city, max_places=max_new_places, travel_style=travel_style)
            )
            data_source = "real_api"
        except Exception:
            candidate_places = []
            data_source = "mock"

    if candidate_places:
        candidate_places = _filter_places_within_radius(
            candidate_places, anchor_places=anchor_places
        )

    meal_slot_count = sum(1 for _, time_slot in new_time_slots if time_slot in MEAL_TIME_SLOTS)
    restaurant_places = _exclude_existing(
        _search_restaurant_places(
            city=city,
            anchor_places=anchor_places,
            max_restaurants=meal_slot_count,
            travel_style=travel_style,
            prefer_local=prefer_local,
        )
    )

    candidate_count = max(0, max_new_places - len(restaurant_places))
    new_selected_places = _deduplicate_places(
        candidate_places[:candidate_count] + restaurant_places
    )[:max_new_places]
    new_selected_places = _reorder_places_for_time_slots(new_selected_places, new_time_slots)

    if not new_selected_places:
        # 새 날짜를 채울 후보를 하나도 못 찾으면 기존 일정은 그대로 두고 경고만 남긴다.
        return {
            "candidate_places": [],
            "rag_ranked_places": [],
            "related_places": [],
            "selected_places": [],
            "route_summary": previous_route_summary,
            "daily_schedule": previous_daily_schedule,
            "lodging_place": None,
            "data_source": data_source,
            "warnings": [
                f"Day {previous_days + 1} 이후 일정을 채울 장소를 찾지 못해 "
                "기존 일정만 유지했습니다."
            ],
        }

    connector_place: Place = {
        "name": last_existing_entry.get("place_name", ""),
        "latitude": last_existing_entry.get("latitude"),
        "longitude": last_existing_entry.get("longitude"),
    }
    routes_with_connector, route_warnings = _build_real_routes(
        selected_places=[connector_place] + new_selected_places,
        transport_mode=transport_mode,
    )
    connector_route = routes_with_connector[0] if routes_with_connector else None
    new_route_segments = routes_with_connector[1:] if routes_with_connector else []

    first_place_route_memo = (
        f"{connector_route['from']}에서 {connector_route['estimated_time']} 이동합니다."
        if connector_route
        else None
    )

    new_daily_schedule = _build_daily_schedule(
        selected_places=new_selected_places,
        routes=new_route_segments,
        travel_days=total_days,
        schedule_intensity=schedule_intensity,
        travel_style=travel_style,
        season=season,
        time_slots_override=new_time_slots,
        first_place_route_memo=first_place_route_memo,
    )

    density_warnings = _check_daily_density(
        daily_schedule=new_daily_schedule,
        route_summary=new_route_segments,
        schedule_intensity=schedule_intensity,
    )

    merged_daily_schedule = previous_daily_schedule + new_daily_schedule
    merged_route_summary = (
        previous_route_summary
        + ([connector_route] if connector_route else [])
        + new_route_segments
    )

    # Financial Agent는 selected_places 전체(숙박/음식점 카테고리 구분 포함)로 식비/카페비/
    # 입장료/숙박비를 다시 계산하므로, 새 날짜 장소만 넘기면 기존 Day의 비용이 총액에서
    # 통째로 빠진다. previous_daily_schedule 엔트리(category/content_type_id 포함, 위
    # _build_daily_schedule/_build_lodging_schedule_entry에서 남겨둠)로 옛 장소를 되살려
    # new_selected_places와 합쳐서 넘긴다.
    reconstructed_old_places: List[Place] = [
        _place_from_schedule_entry(entry) for entry in previous_daily_schedule
    ]
    previous_lodging_place = next(
        (place for place in reconstructed_old_places if place.get("category") == LODGING_CATEGORY),
        None,
    )
    merged_selected_places = reconstructed_old_places + new_selected_places

    return {
        "candidate_places": candidate_places,
        "rag_ranked_places": rag_places,
        "related_places": [],
        "selected_places": merged_selected_places,
        "route_summary": merged_route_summary,
        "daily_schedule": merged_daily_schedule,
        # 같은 숙소에 그대로 머무는 것으로 간주해 기존 숙박 장소를 재사용한다 — 늘어난
        # 박수(nights)만큼 Financial Agent가 같은 1박 요금으로 다시 곱해서 계산한다.
        "lodging_place": previous_lodging_place,
        "data_source": data_source,
        "warnings": route_warnings + density_warnings,
    }


def build_slot_replacement_route_plan(
    parsed: Dict[str, Any],
    transport_mode: str,
    people_count: int,
    previous_result: Dict[str, Any],
    target_day: int,
    target_time_slot: str,
) -> Dict[str, Any]:
    """
    슬롯 교체("2일차 점심만 바꿔줘") 후속 요청 전용 Route Planner.

    build_incremental_route_plan(기간 연장)과 같은 문제의식 — 처음부터 다시 계획하면
    지목하지 않은 다른 날짜/시간대까지 통째로 바뀐다 — 에서 출발하되, 여긴 반대로
    "딱 하나의 슬롯"만 바꾸고 나머지는 전부 그대로 둔다. 바뀐 슬롯의 앞/뒤 동선
    (route_summary)만 다시 계산하고, 다른 구간은 손대지 않는다.
    """
    previous_daily_schedule = list(previous_result.get("daily_schedule") or [])
    previous_route_summary = list(previous_result.get("route_summary") or [])

    def _unchanged(extra_warning: str) -> Dict[str, Any]:
        return {
            "candidate_places": [],
            "rag_ranked_places": [],
            "related_places": [],
            "selected_places": [_place_from_schedule_entry(e) for e in previous_daily_schedule],
            "route_summary": previous_route_summary,
            "daily_schedule": previous_daily_schedule,
            "lodging_place": next(
                (
                    _place_from_schedule_entry(e)
                    for e in previous_daily_schedule
                    if e.get("category") == LODGING_CATEGORY
                ),
                None,
            ),
            "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
            "warnings": [extra_warning],
        }

    if not previous_daily_schedule:
        return build_route_plan(
            parsed=parsed, transport_mode=transport_mode, people_count=people_count
        )

    target_day_label = f"Day {target_day}"
    target_index = next(
        (
            index
            for index, entry in enumerate(previous_daily_schedule)
            if entry.get("day") == target_day_label and entry.get("time_slot") == target_time_slot
        ),
        None,
    )

    if target_index is None:
        return _unchanged(
            f"{target_day_label} {target_time_slot} 일정을 찾지 못해 기존 일정을 그대로 유지했습니다."
        )

    target_entry = previous_daily_schedule[target_index]

    if target_entry.get("time_slot") == "체크인":
        # 숙박 교체는 요금 재조회·박수 계산 등 별도 로직이 필요해 이번 범위에서는 지원하지 않는다.
        return _unchanged(
            "숙박(체크인) 일정 교체는 아직 지원하지 않아 기존 일정을 그대로 유지했습니다."
        )

    city = str(parsed.get("city") or "강릉")
    travel_style = list(parsed.get("travel_style") or [])
    prefer_local = bool(parsed.get("prefer_local", False))
    is_meal_slot = target_time_slot in MEAL_TIME_SLOTS

    other_entries = [entry for i, entry in enumerate(previous_daily_schedule) if i != target_index]
    existing_keys = {_normalized_place_key(entry.get("place_name") or "") for entry in other_entries}
    anchor_places = [
        entry
        for entry in other_entries
        if entry.get("latitude") is not None and entry.get("longitude") is not None
    ]

    def _exclude_existing(places: List[Place]) -> List[Place]:
        return [p for p in places if _normalized_place_key(_get_place_name(p)) not in existing_keys]

    if is_meal_slot:
        candidates = _exclude_existing(
            _search_restaurant_places(
                city=city,
                anchor_places=anchor_places,
                max_restaurants=5,
                travel_style=travel_style,
                prefer_local=prefer_local,
            )
        )
    else:
        candidates = _exclude_existing(
            _search_rag_places(
                city=city, travel_style=travel_style, prefer_local=prefer_local, max_places=5
            )
        )
        if candidates:
            candidates = _fill_missing_place_details(candidates)
        else:
            try:
                candidates = _exclude_existing(
                    _search_real_places(city=city, max_places=5, travel_style=travel_style)
                )
            except Exception:
                candidates = []
        # 식사 시간대가 아닌 슬롯을 음식점으로 대체하면 그날 식사 슬롯과 헷갈리니 제외한다.
        candidates = [c for c in candidates if c.get("category") != RESTAURANT_CATEGORY]

    if candidates:
        candidates = _filter_places_within_radius(candidates, anchor_places=anchor_places)

    if not candidates:
        return _unchanged(
            f"{target_day_label} {target_time_slot}을(를) 대체할 장소를 찾지 못해 "
            "기존 일정을 그대로 유지했습니다."
        )

    new_place = candidates[0]
    new_place_name = _get_place_name(new_place)

    prev_entry = previous_daily_schedule[target_index - 1] if target_index > 0 else None
    next_entry = (
        previous_daily_schedule[target_index + 1]
        if target_index + 1 < len(previous_daily_schedule)
        else None
    )

    warnings: List[str] = []

    new_prev_route = None
    if prev_entry is not None:
        routes, route_warnings = _build_real_routes(
            selected_places=[_place_from_schedule_entry(prev_entry), new_place],
            transport_mode=transport_mode,
        )
        new_prev_route = routes[0] if routes else None
        warnings += route_warnings

    new_next_route = None
    if next_entry is not None:
        routes, route_warnings = _build_real_routes(
            selected_places=[new_place, _place_from_schedule_entry(next_entry)],
            transport_mode=transport_mode,
        )
        new_next_route = routes[0] if routes else None
        warnings += route_warnings

    if prev_entry is None:
        route_memo = "여행의 첫 방문 장소입니다."
    elif new_prev_route:
        route_memo = f"{new_prev_route['from']}에서 {new_prev_route['estimated_time']} 이동합니다."
    else:
        route_memo = "이전 장소와의 동선을 고려해 배치했습니다."

    reason = new_place.get("reason") or (
        f"{', '.join(travel_style)} 취향을 고려한 장소입니다."
        if travel_style
        else "여행 조건을 고려한 장소입니다."
    )

    new_entry = {
        "day": target_day_label,
        "time_slot": target_time_slot,
        "place": new_place_name,
        "place_name": new_place_name,
        "reason": reason,
        "route_memo": route_memo,
        "address": new_place.get("address", ""),
        "image_url": new_place.get("image_url", ""),
        "latitude": new_place.get("latitude"),
        "longitude": new_place.get("longitude"),
        "content_id": new_place.get("content_id"),
        "source": new_place.get("source"),
        "category": new_place.get("category"),
        "content_type_id": new_place.get("content_type_id"),
    }

    merged_daily_schedule = list(previous_daily_schedule)
    merged_daily_schedule[target_index] = new_entry

    if next_entry is not None:
        next_route_memo = (
            f"{new_place_name}에서 {new_next_route['estimated_time']} 이동합니다."
            if new_next_route
            else next_entry.get("route_memo")
        )
        merged_daily_schedule[target_index + 1] = {**next_entry, "route_memo": next_route_memo}

    # route_summary[i]는 daily_schedule[i] -> daily_schedule[i+1] 구간이므로, 바뀐 슬롯으로
    # 들어오는 구간(target_index-1)과 나가는 구간(target_index)만 교체하면 된다.
    merged_route_summary = list(previous_route_summary)
    if new_prev_route is not None and 0 <= target_index - 1 < len(merged_route_summary):
        merged_route_summary[target_index - 1] = new_prev_route
    if new_next_route is not None and 0 <= target_index < len(merged_route_summary):
        merged_route_summary[target_index] = new_next_route

    merged_selected_places = [_place_from_schedule_entry(entry) for entry in merged_daily_schedule]
    lodging_place = next(
        (place for place in merged_selected_places if place.get("category") == LODGING_CATEGORY),
        None,
    )

    return {
        "candidate_places": candidates,
        "rag_ranked_places": [] if is_meal_slot else candidates,
        "related_places": [],
        "selected_places": merged_selected_places,
        "route_summary": merged_route_summary,
        "daily_schedule": merged_daily_schedule,
        "lodging_place": lodging_place,
        "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
        "warnings": warnings + [
            f"{target_day_label} {target_time_slot} 일정을 '{new_place_name}'(으)로 교체했습니다."
        ],
    }


def build_place_move_route_plan(
    parsed: Dict[str, Any],
    transport_mode: str,
    people_count: int,
    previous_result: Dict[str, Any],
    source_day: int | None,
    source_time_slot: str | None,
    destination_day: int,
    destination_time_slot: str | None,
    source_place_name: str | None = None,
) -> Dict[str, Any]:
    """
    장소 이동("2일차 관광지를 1일차로 옮겨줘") 후속 요청 전용 Route Planner.

    맞바꾸기가 아니라 "그 장소를 목적지로 옮기고, 그 자리를 위해 목적지에 있던 기존
    장소는 빠지고, 대신 원래 있던 자리(source)는 새 장소로 자동 채운다"는 방식이다:
    - destination 슬롯: 원래 있던 장소는 제외되고, source에서 옮겨온 장소가 들어간다.
    - source 슬롯: 비게 된 자리를 build_slot_replacement_route_plan과 같은 방식으로
      새로 검색한 장소로 채운다(카테고리 인식: 식사 시간대면 음식점, 아니면 일반 관광지).
    - 두 슬롯의 앞뒤 동선만 다시 계산하고, 나머지 슬롯/동선은 손대지 않는다.

    시간대가 지정 안 됐으면(자연어에 "2일차 관광지"처럼 시간대 없이 날짜만 언급된 경우)
    그 날짜의 첫 번째 이동 가능한(체크인 아닌) 슬롯을 대상으로 삼는다. source에 채울
    새 장소를 못 찾으면(후보 없음) 이동 자체를 취소하고 기존 일정을 그대로 유지한다
    (destination만 바뀌고 source는 빈 채로 남는 반쪽짜리 상태를 피하기 위함).

    source_day가 없고 source_place_name만 있으면("안목해변을 3일차로 옮겨줘"처럼 원본
    날짜를 안 말한 경우) 직전 일정(previous_daily_schedule)에서 그 이름과 일치하는
    항목을 찾아 day/time_slot을 역으로 알아낸다. 못 찾으면 이동 없이 기존 일정을 유지한다.
    """
    previous_daily_schedule = list(previous_result.get("daily_schedule") or [])
    previous_route_summary = list(previous_result.get("route_summary") or [])

    def _unchanged(extra_warning: str) -> Dict[str, Any]:
        reconstructed = [_place_from_schedule_entry(e) for e in previous_daily_schedule]
        return {
            "candidate_places": [],
            "rag_ranked_places": [],
            "related_places": [],
            "selected_places": reconstructed,
            "route_summary": previous_route_summary,
            "daily_schedule": previous_daily_schedule,
            "lodging_place": next(
                (p for p in reconstructed if p.get("category") == LODGING_CATEGORY), None
            ),
            "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
            "warnings": [extra_warning],
        }

    if not previous_daily_schedule:
        return build_route_plan(
            parsed=parsed, transport_mode=transport_mode, people_count=people_count
        )

    if source_day is None and source_place_name:
        normalized_target = _normalized_place_key(source_place_name)
        resolved_index = next(
            (
                i
                for i, entry in enumerate(previous_daily_schedule)
                if _normalized_place_key(entry.get("place_name") or "") == normalized_target
            ),
            None,
        )
        if resolved_index is None:
            return _unchanged(
                f"'{source_place_name}'을(를) 현재 일정에서 찾지 못해 "
                "이동 없이 기존 일정을 그대로 유지했습니다."
            )

        resolved_entry = previous_daily_schedule[resolved_index]
        resolved_day = _day_number(str(resolved_entry.get("day") or ""))
        if not resolved_day:
            return _unchanged(
                f"'{source_place_name}'의 날짜 정보를 확인하지 못해 "
                "이동 없이 기존 일정을 그대로 유지했습니다."
            )

        source_day = resolved_day
        if source_time_slot is None:
            source_time_slot = resolved_entry.get("time_slot")

    if source_day is None:
        return _unchanged(
            "이동할 장소의 원본 날짜를 확인하지 못해 기존 일정을 그대로 유지했습니다."
        )

    def _find_index(day: int, time_slot: str | None) -> int | None:
        day_label = f"Day {day}"
        movable_indexes = [
            i
            for i, entry in enumerate(previous_daily_schedule)
            if entry.get("day") == day_label and entry.get("time_slot") != "체크인"
        ]
        if not movable_indexes:
            return None
        if time_slot is None:
            return movable_indexes[0]
        for index in movable_indexes:
            if previous_daily_schedule[index].get("time_slot") == time_slot:
                return index
        return None

    source_index = _find_index(source_day, source_time_slot)
    destination_index = _find_index(destination_day, destination_time_slot)

    if source_index is None or destination_index is None:
        return _unchanged(
            f"Day {source_day} 또는 Day {destination_day}에서 옮길 일정을 찾지 못해 "
            "기존 일정을 그대로 유지했습니다."
        )

    if source_index == destination_index:
        return _unchanged("같은 슬롯으로는 옮길 수 없어 기존 일정을 그대로 유지했습니다.")

    moving_place = _place_from_schedule_entry(previous_daily_schedule[source_index])
    original_destination_name = previous_daily_schedule[destination_index].get("place_name", "")

    # "체크인"은 _find_index가 애초에 movable_indexes에서 빼놓아 source/destination 어느
    # 쪽으로도 선택될 수 없지만, "점심"/"저녁"(식사 슬롯)은 그런 보호가 없다 — 목적지
    # 슬롯이 식사 시간대인데 옮겨오는 장소가 음식점이 아니거나(또는 그 반대), 그대로
    # 밀어넣으면 시간대 라벨과 실제 장소 종류가 어긋난 일정이 만들어진다. 목적지 시간대를
    # 사용자가 명시적으로 식사 시간대로 지목했을 때만 실제로 발생하는 경우다(시간대
    # 미지정 시 기본으로 고르는 "그 날짜 첫 슬롯"은 슬롯 순서상 항상 식사가 아닌 슬롯이라
    # 문제되지 않음).
    destination_slot_label = previous_daily_schedule[destination_index]["time_slot"]
    destination_is_meal_slot = destination_slot_label in MEAL_TIME_SLOTS
    moving_place_is_restaurant = moving_place.get("category") == RESTAURANT_CATEGORY

    if destination_is_meal_slot != moving_place_is_restaurant:
        return _unchanged(
            f"Day {destination_day} {destination_slot_label}은(는) "
            + ("식사 시간대라 음식점만" if destination_is_meal_slot else "식사 시간대가 아니라 음식점이 아닌 장소만")
            + f" 옮길 수 있어, '{_get_place_name(moving_place)}'을(를) 옮기지 못하고 "
            "기존 일정을 그대로 유지했습니다."
        )

    # source 자리를 채울 새 후보를 build_slot_replacement_route_plan과 동일한 방식으로 찾는다
    # — 이동/목적지 두 슬롯을 제외한 나머지 일정을 "이미 있는 장소"로 보고 중복을 피한다.
    other_entries = [
        entry
        for i, entry in enumerate(previous_daily_schedule)
        if i not in (source_index, destination_index)
    ]
    existing_keys = {_normalized_place_key(entry.get("place_name") or "") for entry in other_entries}
    # moving_place 자신은 이제 destination 자리로 옮겨가므로, source 빈 자리를 채울
    # 백필 후보로 자기 자신이 재선택되지 않게 제외한다(그렇지 않으면 취향 유사도
    # 1순위였던 곳이 두 슬롯에 중복으로 배정될 수 있다).
    existing_keys.add(_normalized_place_key(_get_place_name(moving_place)))
    anchor_places = [
        entry
        for entry in other_entries
        if entry.get("latitude") is not None and entry.get("longitude") is not None
    ]

    def _exclude_existing(places: List[Place]) -> List[Place]:
        return [p for p in places if _normalized_place_key(_get_place_name(p)) not in existing_keys]

    city = str(parsed.get("city") or "강릉")
    travel_style = list(parsed.get("travel_style") or [])
    prefer_local = bool(parsed.get("prefer_local", False))
    source_slot_label = previous_daily_schedule[source_index]["time_slot"]
    is_meal_slot = source_slot_label in MEAL_TIME_SLOTS

    if is_meal_slot:
        backfill_candidates = _exclude_existing(
            _search_restaurant_places(
                city=city,
                anchor_places=anchor_places,
                max_restaurants=5,
                travel_style=travel_style,
                prefer_local=prefer_local,
            )
        )
    else:
        backfill_candidates = _exclude_existing(
            _search_rag_places(
                city=city, travel_style=travel_style, prefer_local=prefer_local, max_places=5
            )
        )
        if backfill_candidates:
            backfill_candidates = _fill_missing_place_details(backfill_candidates)
        else:
            try:
                backfill_candidates = _exclude_existing(
                    _search_real_places(city=city, max_places=5, travel_style=travel_style)
                )
            except Exception:
                backfill_candidates = []
        backfill_candidates = [
            c for c in backfill_candidates if c.get("category") != RESTAURANT_CATEGORY
        ]

    if backfill_candidates:
        backfill_candidates = _filter_places_within_radius(
            backfill_candidates, anchor_places=anchor_places
        )

    if not backfill_candidates:
        return _unchanged(
            f"Day {source_day} {source_slot_label}에 새로 채울 장소를 찾지 못해 "
            "이동 없이 기존 일정을 그대로 유지했습니다."
        )

    backfill_place = backfill_candidates[0]
    backfill_name = _get_place_name(backfill_place)

    merged_daily_schedule = [dict(entry) for entry in previous_daily_schedule]

    place_fields = (
        "place", "place_name", "reason", "address", "image_url",
        "latitude", "longitude", "content_id", "source", "category", "content_type_id",
    )

    destination_entry = merged_daily_schedule[destination_index]
    destination_entry["place"] = _get_place_name(moving_place)
    destination_entry["place_name"] = _get_place_name(moving_place)
    destination_entry["reason"] = moving_place.get("reason") or "다른 날짜에서 옮겨온 장소입니다."
    for field in place_fields[2:]:
        destination_entry[field] = moving_place.get(field)

    source_entry = merged_daily_schedule[source_index]
    source_entry["place"] = backfill_name
    source_entry["place_name"] = backfill_name
    source_entry["reason"] = backfill_place.get("reason") or (
        f"{', '.join(travel_style)} 취향을 고려한 장소입니다."
        if travel_style
        else "여행 조건을 고려한 장소입니다."
    )
    for field in place_fields[2:]:
        source_entry[field] = backfill_place.get(field)

    warnings = []
    merged_route_summary = list(previous_route_summary)

    def _refresh_route_memo_around(index: int) -> None:
        """index 슬롯의 앞뒤 동선을 다시 계산하고, 그 결과로 route_memo도 갱신한다."""
        if index > 0:
            prev_place = _place_from_schedule_entry(merged_daily_schedule[index - 1])
            this_place = _place_from_schedule_entry(merged_daily_schedule[index])
            routes, route_warnings = _build_real_routes(
                selected_places=[prev_place, this_place], transport_mode=transport_mode
            )
            warnings.extend(route_warnings)
            if routes and (index - 1) < len(merged_route_summary):
                merged_route_summary[index - 1] = routes[0]
                merged_daily_schedule[index]["route_memo"] = (
                    f"{routes[0]['from']}에서 {routes[0]['estimated_time']} 이동합니다."
                )
        else:
            merged_daily_schedule[index]["route_memo"] = "여행의 첫 방문 장소입니다."

        if index + 1 < len(merged_daily_schedule):
            this_place = _place_from_schedule_entry(merged_daily_schedule[index])
            next_place = _place_from_schedule_entry(merged_daily_schedule[index + 1])
            routes, route_warnings = _build_real_routes(
                selected_places=[this_place, next_place], transport_mode=transport_mode
            )
            warnings.extend(route_warnings)
            if routes and index < len(merged_route_summary):
                merged_route_summary[index] = routes[0]
                merged_daily_schedule[index + 1]["route_memo"] = (
                    f"{merged_daily_schedule[index]['place_name']}에서 "
                    f"{routes[0]['estimated_time']} 이동합니다."
                )

    # 두 인덱스가 서로 이웃이면 그 사이 구간이 두 번 계산될 수 있지만(순서대로 처리),
    # 이미 내용이 확정된 동일한 daily_schedule 상태를 기준으로 계산하므로 결과는 같다.
    for index in sorted({source_index, destination_index}):
        _refresh_route_memo_around(index)

    reconstructed_places = [_place_from_schedule_entry(entry) for entry in merged_daily_schedule]
    lodging_place = next(
        (place for place in reconstructed_places if place.get("category") == LODGING_CATEGORY),
        None,
    )

    return {
        "candidate_places": backfill_candidates,
        "rag_ranked_places": [] if is_meal_slot else backfill_candidates,
        "related_places": [],
        "selected_places": reconstructed_places,
        "route_summary": merged_route_summary,
        "daily_schedule": merged_daily_schedule,
        "lodging_place": lodging_place,
        "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
        "warnings": warnings + [
            f"Day {source_day}의 '{_get_place_name(moving_place)}'을(를) Day {destination_day}로 "
            f"옮겼습니다(Day {destination_day}에 있던 '{original_destination_name}'은 제외됨). "
            f"Day {source_day}의 빈 자리는 '{backfill_name}'(으)로 새로 채웠습니다."
        ],
    }


# 신규 삽입 슬롯에 붙일 시간대 후보 순서. 이미 쓰인 시간대는 건너뛰고, 이 중 첫 번째로
# 비어있는 것을 쓴다 — 음식점이면 식사 시간대(점심/저녁)를 우선한다.
_GENERAL_SLOT_ORDER = ("오후", "늦은 오후", "오전", "저녁", "점심")
_MEAL_SLOT_ORDER = ("점심", "저녁", "오후", "늦은 오후", "오전")


def build_named_place_insertion_route_plan(
    parsed: Dict[str, Any],
    transport_mode: str,
    people_count: int,
    previous_result: Dict[str, Any],
    place_name: str,
    target_day: int,
) -> Dict[str, Any]:
    """
    특정 날짜에 이름으로 지정한 장소를 반드시 추가하는 후속 요청
    ("2일차에는 국립경주박물관을 꼭 추가해줘") 전용 Route Planner.

    기존 일정은 그대로 두고, target_day의 마지막 슬롯 뒤에 새 장소를 하나 끼워 넣는다.
    시간대는 명시되지 않으므로 카테고리(음식점 여부)와 그 날짜에 이미 쓰인 시간대를
    보고 자동으로 고른다. target_day 자체가 일정에 없으면(예: 1박 2일인데 3일차를
    지정) 추가하지 않고 기존 일정을 그대로 유지한다.
    """
    previous_daily_schedule = list(previous_result.get("daily_schedule") or [])
    previous_route_summary = list(previous_result.get("route_summary") or [])

    def _unchanged(extra_warning: str) -> Dict[str, Any]:
        reconstructed = [_place_from_schedule_entry(e) for e in previous_daily_schedule]
        return {
            "candidate_places": [],
            "rag_ranked_places": [],
            "related_places": [],
            "selected_places": reconstructed,
            "route_summary": previous_route_summary,
            "daily_schedule": previous_daily_schedule,
            "lodging_place": next(
                (p for p in reconstructed if p.get("category") == LODGING_CATEGORY), None
            ),
            "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
            "warnings": [extra_warning],
        }

    if not previous_daily_schedule:
        return build_route_plan(
            parsed=parsed, transport_mode=transport_mode, people_count=people_count
        )

    city = str(parsed.get("city") or "강릉")
    travel_style = list(parsed.get("travel_style") or [])

    existing_keys = {
        _normalized_place_key(entry.get("place_name") or "") for entry in previous_daily_schedule
    }
    if _normalized_place_key(place_name) in existing_keys:
        return _unchanged(
            f"'{place_name}'은(는) 이미 일정에 포함되어 있어 추가하지 않았습니다."
        )

    resolved_place = _resolve_must_include_place(place_name, city, travel_style)
    if resolved_place is None:
        return _unchanged(
            f"'{place_name}'을(를) 찾지 못해 일정에 추가하지 못했습니다."
        )

    target_day_label = f"Day {target_day}"
    day_indexes = [
        i for i, entry in enumerate(previous_daily_schedule) if entry.get("day") == target_day_label
    ]
    if not day_indexes:
        return _unchanged(
            f"{target_day_label} 일정이 없어 '{place_name}'을(를) 추가하지 못했습니다."
        )

    insert_index = day_indexes[-1] + 1

    used_slots = {previous_daily_schedule[i].get("time_slot") for i in day_indexes}
    is_restaurant = resolved_place.get("category") == RESTAURANT_CATEGORY
    slot_order = _MEAL_SLOT_ORDER if is_restaurant else _GENERAL_SLOT_ORDER
    new_time_slot = next(
        (slot for slot in slot_order if slot not in used_slots),
        slot_order[0],
    )

    new_place_name = _get_place_name(resolved_place)
    new_entry = {
        "day": target_day_label,
        "time_slot": new_time_slot,
        "place": new_place_name,
        "place_name": new_place_name,
        "reason": resolved_place.get("reason") or "사용자가 요청한 필수 방문 장소입니다.",
        "route_memo": "이전 장소와의 동선을 고려해 배치했습니다.",
        "address": resolved_place.get("address", ""),
        "image_url": resolved_place.get("image_url", ""),
        "latitude": resolved_place.get("latitude"),
        "longitude": resolved_place.get("longitude"),
        "content_id": resolved_place.get("content_id"),
        "source": resolved_place.get("source"),
        "category": resolved_place.get("category"),
        "content_type_id": resolved_place.get("content_type_id"),
    }

    new_schedule = (
        previous_daily_schedule[:insert_index]
        + [new_entry]
        + previous_daily_schedule[insert_index:]
    )

    warnings: List[str] = []
    new_segments: List[RouteSegment] = []
    new_place = _place_from_schedule_entry(new_entry)

    if insert_index > 0:
        prev_place = _place_from_schedule_entry(previous_daily_schedule[insert_index - 1])
        routes, route_warnings = _build_real_routes(
            selected_places=[prev_place, new_place], transport_mode=transport_mode
        )
        warnings.extend(route_warnings)
        if routes:
            new_segments.extend(routes)
            new_entry["route_memo"] = (
                f"{routes[0]['from']}에서 {routes[0]['estimated_time']} 이동합니다."
            )
    else:
        new_entry["route_memo"] = "여행의 첫 방문 장소입니다."

    if insert_index < len(previous_daily_schedule):
        next_place = _place_from_schedule_entry(previous_daily_schedule[insert_index])
        routes, route_warnings = _build_real_routes(
            selected_places=[new_place, next_place], transport_mode=transport_mode
        )
        warnings.extend(route_warnings)
        if routes:
            new_segments.extend(routes)

    prefix = previous_route_summary[: insert_index - 1] if insert_index > 0 else []
    suffix = previous_route_summary[insert_index:]
    new_route_summary = list(prefix) + new_segments + list(suffix)

    reconstructed_places = [_place_from_schedule_entry(entry) for entry in new_schedule]
    lodging_place = next(
        (p for p in reconstructed_places if p.get("category") == LODGING_CATEGORY), None
    )

    return {
        "candidate_places": [resolved_place],
        "rag_ranked_places": [],
        "related_places": [],
        "selected_places": reconstructed_places,
        "route_summary": new_route_summary,
        "daily_schedule": new_schedule,
        "lodging_place": lodging_place,
        "data_source": previous_result.get("condition_summary", {}).get("data_source", "rag"),
        "warnings": warnings + [
            f"{target_day_label} {new_time_slot}에 '{new_place_name}'을(를) 새로 추가했습니다."
        ],
    }
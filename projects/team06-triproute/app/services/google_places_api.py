import time
from typing import Any, Dict, Optional

import requests

from app.core.config import settings

# Places API (Legacy)는 2025년 3월부로 동결되어 신규 프로젝트에서 활성화 자체가 안 되므로
# Places API (New)를 사용한다.
BASE_URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = "places.id,places.displayName,places.rating,places.userRatingCount,places.formattedAddress,places.location,places.priceLevel"

DEFAULT_RADIUS_M = 500.0

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class GooglePlacesAPIError(Exception):
    pass


def find_place(
    name: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    radius_m: float = DEFAULT_RADIUS_M,
) -> Optional[Dict[str, Any]]:
    """
    장소 이름(+주소)으로 Google Places(New)를 검색해서 가장 유력한 후보 1건을 가져옵니다.

    이름 텍스트 검색만으로는 이름이 일부만 겹쳐도 완전 무관한 곳(예: 다른 지역의 법무법인)이
    매칭되는 사고가 실제로 발생함 (예: "존재하지않는가상의장소" 검색에 서울의 한 법무법인이
    매칭됨 - 상호명에 "존재"가 들어있었을 뿐임). 주소 문자열 비교로는 안목해변처럼 formattedAddress에
    시/군 표기가 아예 없는 자연 명소를 오히려 걸러내는 부작용이 있어서 채택하지 않았다.

    대신 lat/lng(TourAPI의 mapx/mapy)로 좁은 반경(radius_m, 기본 500m) locationBias를 걸어
    검증한다 — 실측 결과 이 방식이 오매칭을 확실히 걸러냄. **lat/lng 없이 이름만으로 부르면
    오매칭 위험이 남으니, 가능하면 항상 좌표를 같이 넘길 것.**
    """

    query = f"{name} {address}" if address else name
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": settings.GOOGLE_PLACES_API_KEY,
        "X-Goog-FieldMask": FIELD_MASK,
    }
    body: Dict[str, Any] = {"textQuery": query, "languageCode": "ko"}
    if lat is not None and lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": radius_m,
            }
        }

    # 429(RESOURCE_EXHAUSTED, QPS 초과)는 backfill처럼 대량 호출 시 실제로 발생함.
    # 다른 4xx/5xx는 재시도해도 소용없는 경우가 많아 바로 에러 처리하고, 429만 backoff 후 재시도한다.
    last_error = None
    for attempt in range(MAX_RETRIES):
        response = requests.post(BASE_URL, json=body, headers=headers, timeout=10)
        if response.status_code == 429:
            last_error = f"429 Too Many Requests: {response.text}"
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
                continue
            raise GooglePlacesAPIError(last_error)
        if not response.ok:
            raise GooglePlacesAPIError(f"searchText 실패: {response.status_code} {response.text}")

        places = response.json().get("places", [])
        return places[0] if places else None

    raise GooglePlacesAPIError(last_error)


def get_rating_and_review_count(
    name: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> Dict[str, Optional[Any]]:
    """
    장소의 평점(rating)과 리뷰 수(review_count)만 뽑아서 반환합니다.
    매칭 실패 시 둘 다 None입니다.
    """

    place = find_place(name, address, lat=lat, lng=lng)
    if not place:
        return {"rating": None, "review_count": None}

    return {
        "rating": place.get("rating"),
        "review_count": place.get("userRatingCount"),
    }


def get_price_level(
    name: str,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> Optional[str]:
    """
    장소의 가격대(priceLevel)를 가져옵니다. 매칭 실패거나 해당 장소에 가격대 정보가
    없으면(예: 데이터 미등록) None을 반환합니다.

    반환값은 Google Places(New)의 priceLevel enum 문자열 그대로입니다
    (PRICE_LEVEL_FREE / INEXPENSIVE / MODERATE / EXPENSIVE / VERY_EXPENSIVE).
    """

    place = find_place(name, address, lat=lat, lng=lng)
    if not place:
        return None

    return place.get("priceLevel")


def get_coordinates(
    name: str,
    address: Optional[str] = None,
) -> Dict[str, Optional[float]]:
    """
    장소 이름과 주소로 평점/리뷰 대신 위도, 경도를 뽑아서 반환합니다.
    매칭 실패 시 둘 다 None입니다.
    """
    place = find_place(name, address=address)
    if not place or "location" not in place:
        return {"latitude": None, "longitude": None}

    location = place["location"]
    return {
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
    }

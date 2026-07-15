import time
from typing import Any, Dict, List, Optional

import requests

from app.core.config import settings

BASE_URL = "https://apis.data.go.kr/B551011/KorService2"

MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 2


class TourAPIError(Exception):
    pass


def _request(operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
    query = {
        "serviceKey": settings.TOUR_API_KEY,
        "MobileOS": "ETC",
        "MobileApp": "TripRoute",
        "_type": "json",
        **params,
    }

    # TourAPI가 가끔 응답이 느려서 타임아웃/커넥션 에러가 나는 경우가 있어 재시도함.
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(f"{BASE_URL}/{operation}", params=query, timeout=20)
            response.raise_for_status()
            body = response.json()
            break
        except (requests.exceptions.RequestException, ValueError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    else:
        raise TourAPIError(f"{operation} 요청 실패 ({MAX_RETRIES}회 재시도): {last_error}")

    # 정상 응답은 response.header 안에 resultCode가 있고,
    # 게이트웨이 레벨 오류(파라미터 오류 등)는 최상위에 바로 resultCode가 온다.
    header = body.get("response", {}).get("header") or body
    if header.get("resultCode") != "0000":
        raise TourAPIError(f"{operation} 실패: {header.get('resultCode')} {header.get('resultMsg')}")

    return body["response"]["body"]


def _extract_items(body: Dict[str, Any]) -> List[Dict[str, Any]]:
    # 결과가 0건이면 게이트웨이가 items를 {}가 아니라 ""(빈 문자열)로 내려줄 때가 있어 방어적으로 처리
    items_field = body.get("items")
    if not isinstance(items_field, dict):
        return []
    items = items_field.get("item", [])
    return items if isinstance(items, list) else [items] if items else []


def search_keyword(
    keyword: str,
    content_type_id: Optional[str] = None,
    num_of_rows: int = 20,
    page_no: int = 1,
) -> List[Dict[str, Any]]:
    """
    키워드(도시명 등)로 관광지를 검색합니다.
    """

    params: Dict[str, Any] = {
        "keyword": keyword,
        "numOfRows": num_of_rows,
        "pageNo": page_no,
    }
    if content_type_id:
        params["contentTypeId"] = content_type_id

    body = _request("searchKeyword2", params)
    return _extract_items(body)


def get_detail_common(content_id: str) -> Dict[str, Any]:
    """
    관광지 상세 공통정보(주소, 좌표, 개요 등)를 조회합니다.

    이 API는 contentId 외의 조회 옵션 파라미터(overviewYN 등)를 지원하지 않으며,
    기본 응답에 주소·좌표·개요가 이미 포함되어 있다.
    """

    params = {"contentId": content_id}

    body = _request("detailCommon2", params)
    items = _extract_items(body)
    return items[0] if items else {}


def get_detail_intro(content_id: str, content_type_id: str) -> Dict[str, Any]:
    """
    관광지 상세 소개정보(운영시간, 쉬는날, 이용요금 등)를 조회합니다.

    detailCommon2와 달리 contentTypeId가 필수이며, 반환 필드는 콘텐츠 타입마다 다르다.
    예) 관광지(12): usetime, restdate, parking / 문화시설(14): usefee, usetimeculture 등
    usefee는 관광지(12) 타입에는 존재하지 않고 유료 시설 타입(14, 28 등)에만 있다.
    """

    params = {
        "contentId": content_id,
        "contentTypeId": content_type_id,
    }

    body = _request("detailIntro2", params)
    items = _extract_items(body)
    return items[0] if items else {}


def get_detail_info(content_id: str, content_type_id: str) -> List[Dict[str, Any]]:
    """
    반복정보(하위 목록)를 조회합니다. 콘텐츠 타입마다 반환 항목이 다르다.
    예) 여행코스(25): 코스를 구성하는 하위 장소 목록(subcontentid/subname/subdetailoverview 등)
        숙박(32): 객실별 요금 정보(roomtitle/roomoffseasonminfee1 등)
    detailIntro2와 달리 결과가 여러 건(리스트)으로 온다.
    """

    params = {
        "contentId": content_id,
        "contentTypeId": content_type_id,
    }

    body = _request("detailInfo2", params)
    return _extract_items(body)

import time
from typing import Any, Dict, Tuple

import requests

from app.core.config import settings
from app.utils.cache import cached_call

BASE_URL = "https://apis-navi.kakaomobility.com/v1/directions"

# TourAPI(app/services/tour_api.py)와 동일한 이유로 재시도한다 — 카카오모빌리티도
# 가끔 타임아웃/일시적 오류가 나는데, 재시도 없이 바로 실패 처리하면(과거 실제로
# 그랬음) 정상적인 좌표인데도 그 요청 시점의 일시적 문제 때문에 "조회 실패"가
# 그대로 최종 일정에 박혀버린다.
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 1


class KakaoMobilityError(Exception):
    pass


def get_route(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    priority: str = "RECOMMEND",
) -> Dict[str, Any]:
    """
    두 좌표 간 자동차 기준 경로를 조회합니다.

    origin/destination은 (경도, 위도) 순서의 튜플입니다.
    (TourAPI의 mapx=경도, mapy=위도와 순서가 같음)
    같은 출발지-도착지 조합은 하루 동안 캐시된 응답을 재사용합니다 (교통 상황이 실시간 반영되는
    API가 아니라 매번 다시 부를 필요가 없음 — 호출 비용/속도 절약).
    """

    cache_params = {"origin": origin, "destination": destination, "priority": priority}
    return cached_call("kakao_route", cache_params, lambda: _fetch_route(origin, destination, priority))


def _fetch_route(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    priority: str,
) -> Dict[str, Any]:
    headers = {"Authorization": f"KakaoAK {settings.KAKAO_MOBILITY_API_KEY}"}
    params = {
        "origin": f"{origin[0]},{origin[1]}",
        "destination": f"{destination[0]},{destination[1]}",
        "priority": priority,
    }

    # 네트워크 타임아웃/일시적 오류(RequestException)만 재시도한다. result_code != 0
    # (아래에서 raise하는 KakaoMobilityError)은 좌표 자체의 길찾기 실패라 재시도해도
    # 똑같이 실패하므로 재시도 대상이 아니다.
    last_error: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(BASE_URL, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            body = response.json()
            break
        except (requests.exceptions.RequestException, ValueError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_SECONDS * (attempt + 1))
    else:
        raise KakaoMobilityError(f"길찾기 요청 실패 ({MAX_RETRIES}회 재시도): {last_error}")

    routes = body.get("routes", [])
    if not routes or routes[0].get("result_code") != 0:
        route = routes[0] if routes else {}
        raise KakaoMobilityError(f"길찾기 실패: {route.get('result_code')} {route.get('result_msg')}")

    return routes[0]


def summarize_route(route: Dict[str, Any]) -> Dict[str, Any]:
    """
    get_route()의 결과에서 동선 계산에 필요한 값만 추려냅니다.
    """

    summary = route["summary"]
    return {
        "distance_km": round(summary["distance"] / 1000, 1),
        "duration_min": round(summary["duration"] / 60),
        "taxi_fare": summary["fare"]["taxi"],
        "toll_fare": summary["fare"]["toll"],
    }

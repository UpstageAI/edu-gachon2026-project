from typing import Any, Dict, List, Optional

from supabase import Client, create_client

from app.core.config import settings


def get_client() -> Client:
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


def get_service_client() -> Client:
    """
    RLS를 우회하는 service_role 클라이언트. chat_store처럼 백엔드가 소유권을
    직접 검증하는 테이블 전용 — SUPABASE_SERVICE_KEY가 없으면 즉시 실패한다
    (anon 키로 조용히 폴백하면 RLS에 막혀 매번 실패하는 걸 다시 놓치게 된다).
    """
    if not settings.SUPABASE_SERVICE_KEY:
        raise RuntimeError(
            "SUPABASE_SERVICE_KEY가 설정되지 않았습니다. "
            "Supabase 프로젝트 설정 > API에서 service_role 키를 .env에 추가하세요."
        )
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


def insert_place(
    content_id: str,
    title: str,
    overview: str,
    embedding: List[float],
    address: Optional[str] = None,
    category: Optional[str] = None,
    event_start_date: Optional[str] = None,
    event_end_date: Optional[str] = None,
    rating: Optional[float] = None,
    review_count: Optional[int] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Dict[str, Any]:
    """
    관광지 정보와 임베딩을 places 테이블에 저장합니다.
    content_id가 이미 있으면 덮어씁니다(upsert).
    event_start_date/event_end_date는 축제(축제공연행사) 개최기간용이며, 해당 없는 장소는 None으로 저장됩니다.
    rating/review_count는 Google Places 매칭 결과이며, 매칭 실패 시 None으로 저장됩니다.
    latitude/longitude는 TourAPI detailCommon2(mapy/mapx) 결과로, 수집 시점에 이미 조회한
    값을 그대로 저장한다 — 이걸 저장해두면 나중에 Route Planner가 같은 장소의 좌표를
    다시 TourAPI로 조회할 필요가 없어진다(match_places 검색 결과에 바로 포함됨).
    """

    row = {
        "content_id": content_id,
        "title": title,
        "overview": overview,
        "address": address,
        "category": category,
        "embedding": embedding,
        "event_start_date": event_start_date,
        "event_end_date": event_end_date,
        "rating": rating,
        "review_count": review_count,
        "latitude": latitude,
        "longitude": longitude,
    }

    response = get_client().table("places").upsert(row, on_conflict="content_id").execute()
    return response.data


def get_festivals_missing_event_dates(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    category가 '축제공연행사'인데 event_start_date가 비어있는 행을 가져옵니다 (백필 대상 조회용).
    """

    response = (
        get_client()
        .table("places")
        .select("content_id")
        .eq("category", "축제공연행사")
        .is_("event_start_date", "null")
        .limit(limit)
        .execute()
    )
    return response.data


def update_place_event_dates(content_id: str, event_start_date: Optional[str], event_end_date: Optional[str]) -> Dict[str, Any]:
    """
    특정 content_id 행의 개최기간(event_start_date/event_end_date)만 갱신합니다.
    """

    response = (
        get_client()
        .table("places")
        .update({"event_start_date": event_start_date, "event_end_date": event_end_date})
        .eq("content_id", content_id)
        .execute()
    )
    return response.data


def get_places_missing_rating(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    rating이 비어있는 관광지 행을 가져옵니다 (백필 대상 조회용).
    """

    response = (
        get_client()
        .table("places")
        .select("content_id, title")
        .is_("rating", "null")
        .limit(limit)
        .execute()
    )
    return response.data


def update_place_rating(content_id: str, rating: Optional[float], review_count: Optional[int]) -> Dict[str, Any]:
    """
    특정 content_id 행의 rating/review_count만 갱신합니다.
    """

    response = (
        get_client()
        .table("places")
        .update({"rating": rating, "review_count": review_count})
        .eq("content_id", content_id)
        .execute()
    )
    return response.data


def get_places_missing_coordinates(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    latitude가 비어있는 관광지 행을 가져옵니다 (좌표 백필 대상 조회용).

    title/address도 같이 가져온다 — TourAPI detailCommon2가 삭제/비공개된 content_id에
    완전히 빈 응답(title도 None)을 줄 때, vector_store.backfill_coordinates의 Google
    Places 폴백 검색어로 쓸 이름이 필요하기 때문(content_id만 있으면 검색어가 없어서
    폴백 자체가 항상 실패했었음).
    """

    response = (
        get_client()
        .table("places")
        .select("content_id, title, address")
        .is_("latitude", "null")
        .limit(limit)
        .execute()
    )
    return response.data


def update_place_coordinates(content_id: str, latitude: Optional[float], longitude: Optional[float]) -> Dict[str, Any]:
    """
    특정 content_id 행의 latitude/longitude만 갱신합니다.
    """

    response = (
        get_client()
        .table("places")
        .update({"latitude": latitude, "longitude": longitude})
        .eq("content_id", content_id)
        .execute()
    )
    return response.data


def get_existing_content_ids(content_ids: List[str]) -> set:
    """
    주어진 content_id 목록 중 이미 places 테이블에 저장돼 있는 것만 반환합니다.
    (수집 재개 시 이미 저장된 곳은 TourAPI 상세조회/임베딩을 건너뛰기 위한 용도)
    """

    if not content_ids:
        return set()

    response = (
        get_client()
        .table("places")
        .select("content_id")
        .in_("content_id", content_ids)
        .execute()
    )
    return {row["content_id"] for row in response.data}


def get_places_missing_category(limit: int = 1000) -> List[Dict[str, Any]]:
    """
    category가 비어있는 관광지 행을 가져옵니다 (백필 대상 조회용).
    """

    response = (
        get_client()
        .table("places")
        .select("content_id")
        .is_("category", "null")
        .limit(limit)
        .execute()
    )
    return response.data


def update_place_category(content_id: str, category: str) -> Dict[str, Any]:
    """
    특정 content_id 행의 category만 갱신합니다.
    """

    response = (
        get_client()
        .table("places")
        .update({"category": category})
        .eq("content_id", content_id)
        .execute()
    )
    return response.data


def search_similar_places(
    query_embedding: List[float],
    match_count: int = 5,
    city: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    사용자 취향 임베딩과 가장 비슷한 관광지를 match_places RPC로 검색합니다.
    city를 넘기면 address에 해당 도시명이 포함된 행으로만 후보를 제한합니다.
    """

    response = get_client().rpc(
        "match_places",
        {
            "query_embedding": query_embedding,
            "match_count": match_count,
            "city_filter": city,
        },
    ).execute()
    return response.data


def get_course_content_ids(city: str, limit: int = 20) -> List[str]:
    """
    category가 '여행코스'인 행 중 address에 city가 포함된 것의 content_id 목록을 가져옵니다.
    (Route Planner가 여행코스의 하위 장소를 연관 관광지로 추천할 때 사용)
    """

    response = (
        get_client()
        .table("places")
        .select("content_id")
        .eq("category", "여행코스")
        .like("address", f"%{city}%")
        .limit(limit)
        .execute()
    )
    return [row["content_id"] for row in response.data]

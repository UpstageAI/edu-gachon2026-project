import time
from typing import Any, Dict, List, Optional

from app.rag.embedder import embed_place_overviews
from app.services.google_places_api import GooglePlacesAPIError, get_rating_and_review_count
from app.services.supabase_client import (
    get_existing_content_ids,
    get_festivals_missing_event_dates,
    get_places_missing_category,
    get_places_missing_coordinates,
    get_places_missing_rating,
    insert_place,
    update_place_category,
    update_place_coordinates,
    update_place_event_dates,
    update_place_rating,
)
from app.services.tour_api import TourAPIError, get_detail_common, get_detail_intro, search_keyword

FESTIVAL_CONTENT_TYPE_ID = "15"
COURSE_CONTENT_TYPE_ID = "25"

# TourAPI contentTypeId 코드: 12=관광지, 14=문화시설, 15=축제공연행사,
# 25=여행코스, 28=레포츠, 32=숙박, 38=쇼핑, 39=음식점
# 32(숙박)/38(쇼핑)이 원래 빠져있어서 대부분 도시에 숙박/쇼핑 데이터가 아예 없었음 — 추가함
DEFAULT_CONTENT_TYPE_IDS = ["12", "14", "15", "25", "28", "32", "38", "39"]

CONTENT_TYPE_ID_TO_CATEGORY = {
    "12": "관광지",
    "14": "문화시설",
    "15": "축제공연행사",
    "25": "여행코스",
    "28": "레포츠",
    "32": "숙박",
    "38": "쇼핑",
    "39": "음식점",
}


def content_type_id_to_category(content_type_id: Optional[Any]) -> Optional[str]:
    # TourAPI 게이트웨이가 이 필드를 문자열("12")이 아니라 숫자(12)로 내려줄 때가 있어 str로 정규화
    if content_type_id is None:
        return None
    return CONTENT_TYPE_ID_TO_CATEGORY.get(str(content_type_id))


# search_keyword("부산")는 전국을 대상으로 title에 "부산"이 들어간 결과를 다 돌려줘서,
# "부산식당"(충북 소재) 같은 동명 식당/상호가 섞여 들어온다. city별 실제 주소 접두사를 미리 정의해두고,
# 검색 키워드에 해당하는 시/도가 아닌 주소는 저장 전에 걸러낸다.
CITY_TO_REGION_PREFIXES = {
    "서울": ["서울"],
    "부산": ["부산"],
    "대구": ["대구"],
    "인천": ["인천"],
    "광주": ["광주", "전남광주"],
    "대전": ["대전"],
    "울산": ["울산"],
    "세종": ["세종"],
    "제주": ["제주"],
    "수원": ["경기"],
    "강릉": ["강원"],
    "춘천": ["강원"],
    "속초": ["강원"],
    "전주": ["전북", "전라북도"],
    "여수": ["전남", "전라남도"],
    "경주": ["경북", "경상북도"],
    "통영": ["경남", "경상남도"],
    "거제": ["경남", "경상남도"],
}


def _parse_tourapi_date(value: Optional[str]) -> Optional[str]:
    """
    TourAPI가 내려주는 YYYYMMDD 문자열을 Postgres date 컬럼용 YYYY-MM-DD로 변환합니다.
    """

    if not value or len(value) != 8 or not value.isdigit():
        return None
    return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"


def _to_float(value: Optional[Any]) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def is_in_expected_region(city: str, address: Optional[str]) -> bool:
    """
    address가 city에 해당하는 시/도 소속이 맞는지 확인합니다.
    city가 CITY_TO_REGION_PREFIXES에 없으면(매핑 안 된 새 도시) 필터링하지 않고 통과시킵니다.

    원래 ingest_city(오프라인 수집) 전용이었지만, route_planner.py의 TourAPI 실시간
    검색 폴백(_search_real_places/_search_restaurant_places/_search_lodging_place)에도
    동일한 "동명 상호 다른 지역 오염" 문제가 있어서 그대로 재사용한다.
    """

    prefixes = CITY_TO_REGION_PREFIXES.get(city)
    if not prefixes:
        return True
    if not address:
        return False
    return any(address.startswith(p) for p in prefixes)


def ingest_city(
    city: str,
    num_of_rows: int = 30,
    content_type_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    TourAPI에서 도시 기준으로 관광지를 검색하고, 개요를 임베딩해 Supabase places 테이블에 저장합니다.
    content_type_ids를 넘기면 카테고리별로 각각 num_of_rows만큼 검색해서 합칩니다
    (안 넘기면 DEFAULT_CONTENT_TYPE_IDS 기준으로 관광지/문화시설/축제/여행코스/레포츠/음식점을 다 조회).
    overview가 없는 항목은 건너뛰고, 이미 저장된 content_id는 upsert로 덮어씁니다.
    """

    type_ids = content_type_ids if content_type_ids is not None else DEFAULT_CONTENT_TYPE_IDS

    candidates = []
    seen_content_ids = set()
    for type_id in type_ids:
        try:
            results = search_keyword(city, content_type_id=type_id, num_of_rows=num_of_rows)
        except TourAPIError as e:
            print(f"  [경고] {city}/{type_id} 검색 실패, 건너뜀: {e}")
            continue
        for candidate in results:
            if candidate["contentid"] in seen_content_ids:
                continue
            seen_content_ids.add(candidate["contentid"])
            # detailCommon2가 contenttypeid를 안 내려줄 때를 대비해, 검색에 쓴 type_id를 같이 들고 다님
            candidate["_search_type_id"] = type_id
            candidates.append(candidate)

    existing_ids = get_existing_content_ids([c["contentid"] for c in candidates])
    if existing_ids:
        candidates = [c for c in candidates if c["contentid"] not in existing_ids]
        print(f"  {city}: 이미 저장된 {len(existing_ids)}건 스킵 (재개 시 API 호출 절약)")

    print(f"  {city}: 검색 결과 {len(candidates)}건, 상세정보 조회 중...")

    details = []
    for candidate in candidates:
        try:
            detail = get_detail_common(candidate["contentid"])
        except TourAPIError as e:
            print(f"  [경고] {city}/{candidate['contentid']} 상세조회 실패, 건너뜀: {e}")
            continue
        overview = (detail.get("overview") or "").strip()
        if not overview:
            continue

        content_type_id = str(
            detail.get("contenttypeid")
            or candidate.get("contenttypeid")
            or candidate["_search_type_id"]
        )

        if content_type_id == COURSE_CONTENT_TYPE_ID:
            # 여행코스는 여러 장소를 넘나드는 코스라 단일 addr1이 아예 없는 경우가 대부분임.
            # 개별 방문 장소가 아니라 "코스 구성 조회용"으로만 쓰므로(route_planner의
            # _search_course_related_places 참고), 주소/지역 필터 없이 검색 키워드=city를
            # 그대로 대표 주소로 남겨 나중에 도시별 조회(get_course_content_ids)에 쓴다.
            detail["addr1"] = detail.get("addr1") or city
        else:
            # 다른 콘텐츠 타입은 단일 주소가 실제 위치라 동선 계산에 필요 — 없으면 제외,
            # city 지역과 다른 주소도 제외 (동명 키워드로 엉뚱한 지역이 섞이는 문제 방지)
            if not detail.get("addr1"):
                continue
            if not is_in_expected_region(city, detail.get("addr1")):
                continue

        detail["overview"] = overview
        detail["contenttypeid"] = content_type_id
        details.append(detail)

    if not details:
        return []

    # Upstage 임베딩 API는 한 번에 너무 많은 입력을 보내면 실패할 수 있어 배치로 나눠서 호출
    BATCH_SIZE = 50
    saved = []
    for i in range(0, len(details), BATCH_SIZE):
        batch = details[i : i + BATCH_SIZE]
        embeddings = embed_place_overviews([d["overview"] for d in batch])

        for detail, embedding in zip(batch, embeddings):
            event_start_date = None
            event_end_date = None
            if str(detail.get("contenttypeid")) == FESTIVAL_CONTENT_TYPE_ID:
                try:
                    intro = get_detail_intro(detail["contentid"], FESTIVAL_CONTENT_TYPE_ID)
                    event_start_date = _parse_tourapi_date(intro.get("eventstartdate"))
                    event_end_date = _parse_tourapi_date(intro.get("eventenddate"))
                except TourAPIError as e:
                    print(f"  [경고] {city}/{detail['contentid']} 개최기간 조회 실패: {e}")

            rating = None
            review_count = None
            try:
                rating_info = get_rating_and_review_count(
                    detail.get("title", ""),
                    lat=_to_float(detail.get("mapy")),
                    lng=_to_float(detail.get("mapx")),
                )
                rating = rating_info["rating"]
                review_count = rating_info["review_count"]
            except GooglePlacesAPIError as e:
                print(f"  [경고] {city}/{detail['contentid']} 평점 조회 실패: {e}")

            insert_place(
                content_id=detail["contentid"],
                title=detail.get("title", ""),
                overview=detail["overview"],
                embedding=embedding,
                address=detail.get("addr1"),
                category=content_type_id_to_category(detail.get("contenttypeid")),
                event_start_date=event_start_date,
                event_end_date=event_end_date,
                rating=rating,
                review_count=review_count,
                # Google Places 평점 조회에 쓰려고 이미 받아온 좌표를 그대로 저장한다
                # (추가 API 호출 없음) — Route Planner가 나중에 TourAPI로 다시 조회할 필요가 없어짐.
                latitude=_to_float(detail.get("mapy")),
                longitude=_to_float(detail.get("mapx")),
            )
            saved.append({"title": detail.get("title"), "content_id": detail["contentid"]})

    return saved


def backfill_categories() -> Dict[str, int]:
    """
    category가 비어있는 기존 places 행들에 대해 TourAPI를 다시 조회해서 category를 채워넣습니다.
    """

    targets = get_places_missing_category(limit=5000)
    print(f"카테고리 백필 대상: {len(targets)}건")

    updated = 0
    failed = 0
    for i, row in enumerate(targets):
        content_id = row["content_id"]
        try:
            detail = get_detail_common(content_id)
        except TourAPIError as e:
            print(f"  [경고] {content_id} 상세조회 실패: {e}")
            failed += 1
            time.sleep(1)  # rate limit(429) 대비, 실패 시 조금 더 쉬어감
            continue

        category = content_type_id_to_category(detail.get("contenttypeid"))
        if not category:
            failed += 1
            continue

        time.sleep(0.2)  # TourAPI rate limit 방지용 호출 간 딜레이
        if (i + 1) % 100 == 0:
            print(f"  진행: {i + 1}/{len(targets)}")

        update_place_category(content_id, category)
        updated += 1

    print(f"백필 완료: {updated}건 갱신, {failed}건 실패")
    return {"updated": updated, "failed": failed}


def backfill_festival_dates() -> Dict[str, int]:
    """
    category가 '축제공연행사'인데 개최기간이 비어있는 기존 places 행에 detailIntro2를 다시 조회해서
    event_start_date/event_end_date를 채워넣습니다.
    """

    targets = get_festivals_missing_event_dates(limit=5000)
    print(f"축제 개최기간 백필 대상: {len(targets)}건")

    updated = 0
    failed = 0
    for i, row in enumerate(targets):
        content_id = row["content_id"]
        try:
            intro = get_detail_intro(content_id, FESTIVAL_CONTENT_TYPE_ID)
        except TourAPIError as e:
            print(f"  [경고] {content_id} 개최기간 조회 실패: {e}")
            failed += 1
            time.sleep(1)  # rate limit(429) 대비, 실패 시 조금 더 쉬어감
            continue

        event_start_date = _parse_tourapi_date(intro.get("eventstartdate"))
        event_end_date = _parse_tourapi_date(intro.get("eventenddate"))
        if not event_start_date:
            failed += 1
            continue

        time.sleep(0.2)  # TourAPI rate limit 방지용 호출 간 딜레이
        if (i + 1) % 100 == 0:
            print(f"  진행: {i + 1}/{len(targets)}")

        update_place_event_dates(content_id, event_start_date, event_end_date)
        updated += 1

    print(f"백필 완료: {updated}건 갱신, {failed}건 실패")
    return {"updated": updated, "failed": failed}


def backfill_ratings() -> Dict[str, int]:
    """
    rating이 비어있는 기존 places 행에 대해 TourAPI로 좌표(mapx/mapy)를 다시 조회하고,
    그 좌표로 Google Places를 검색해 rating/review_count를 채워넣습니다.
    """

    targets = get_places_missing_rating(limit=5000)
    print(f"평점 백필 대상: {len(targets)}건")

    updated = 0
    failed = 0
    for i, row in enumerate(targets):
        content_id = row["content_id"]
        try:
            detail = get_detail_common(content_id)
        except TourAPIError as e:
            print(f"  [경고] {content_id} 좌표 조회 실패: {e}")
            failed += 1
            time.sleep(1)  # rate limit(429) 대비, 실패 시 조금 더 쉬어감
            continue

        title = row.get("title") or detail.get("title", "")
        try:
            rating_info = get_rating_and_review_count(
                title,
                lat=_to_float(detail.get("mapy")),
                lng=_to_float(detail.get("mapx")),
            )
        except GooglePlacesAPIError as e:
            print(f"  [경고] {content_id} Google Places 조회 실패: {e}")
            failed += 1
            time.sleep(1)  # rate limit(429) 재시도 소진 후에도 실패하면 여기서도 쉬어감
            continue

        if rating_info["rating"] is None:
            failed += 1
            continue

        time.sleep(0.2)  # TourAPI rate limit 방지용 호출 간 딜레이
        if (i + 1) % 100 == 0:
            print(f"  진행: {i + 1}/{len(targets)}")

        update_place_rating(content_id, rating_info["rating"], rating_info["review_count"])
        updated += 1

    print(f"백필 완료: {updated}건 갱신, {failed}건 실패")
    return {"updated": updated, "failed": failed}


def backfill_coordinates() -> Dict[str, int]:
    """
    latitude/longitude가 비어있는 기존 places 행들에 대해 TourAPI를 다시 조회해서 좌표를 채워넣습니다.
    """

    targets = get_places_missing_coordinates(limit=5000)
    print(f"좌표 백필 대상: {len(targets)}건")

    updated = 0
    failed = 0
    for i, row in enumerate(targets):
        content_id = row["content_id"]
        try:
            detail = get_detail_common(content_id)
        except TourAPIError as e:
            print(f"  [경고] {content_id} 상세조회 실패: {e}")
            failed += 1
            time.sleep(1)  # rate limit(429) 대비, 실패 시 조금 더 쉬어감
            continue

        latitude = _to_float(detail.get("mapy"))
        longitude = _to_float(detail.get("mapx"))

        if latitude is None or longitude is None:
            # Fallback to Google Places API
            try:
                from app.services.google_places_api import get_coordinates
                # dict.get(key, default)는 key 자체가 없을 때만 default를 쓴다 — TourAPI가
                # 콘텐츠를 못 찾아 detail의 title/addr1이 "키는 있는데 값이 None"인 경우엔
                # default로 안 떨어지고 그대로 None이 넘어가 Google Places 검색이 항상
                # 실패했다(실제로 폐업/삭제된 content_id 3건에서 재현 확인). `or`로 교체.
                search_name = detail.get("title") or row.get("title") or ""
                search_addr = detail.get("addr1") or row.get("address") or ""
                coords = get_coordinates(search_name, address=search_addr)
                if coords["latitude"] is not None and coords["longitude"] is not None:
                    latitude = coords["latitude"]
                    longitude = coords["longitude"]
            except Exception:
                pass

        if latitude is None or longitude is None:
            failed += 1
            continue

        time.sleep(0.2)  # TourAPI rate limit 방지용 호출 간 딜레이
        if (i + 1) % 100 == 0:
            print(f"  진행: {i + 1}/{len(targets)}")

        update_place_coordinates(content_id, latitude, longitude)
        updated += 1

    print(f"백필 완료: {updated}건 갱신, {failed}건 실패")
    return {"updated": updated, "failed": failed}


def ingest_cities(
    cities: List[str],
    num_of_rows: int = 30,
    content_type_ids: Optional[List[str]] = None,
) -> Dict[str, int]:
    """
    여러 도시를 순서대로 ingest_city()에 넘겨 일괄 수집합니다.
    """

    result = {}
    for city in cities:
        print(f"[{city}] 수집 시작")
        try:
            saved = ingest_city(city, num_of_rows=num_of_rows, content_type_ids=content_type_ids)
            result[city] = len(saved)
            print(f"[{city}] 완료: {len(saved)}건 저장")
        except Exception as e:
            print(f"[{city}] 실패, 다음 도시로 넘어감: {type(e).__name__}: {e}")
            result[city] = 0
    return result

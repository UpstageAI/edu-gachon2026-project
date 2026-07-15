from typing import Any, Dict, List, Optional

from app.rag.embedder import embed_user_taste
from app.services.supabase_client import search_similar_places

# match_places는 city_filter로 좁힌 코퍼스 안에서 코사인 거리 기준 top-N을 그대로
# 반환한다 — 도시 전체가 취향과 무관한 테마로만 채워져 있어도 match_count만큼 무관한
# 장소가 그대로 반환된다는 뜻이다. similarity가 이 값 미만이면 "취향과 무관"으로 보고
# 걸러내서, 진짜 관련 있는 곳이 없을 때는 빈 리스트를 반환해 호출자가 TourAPI 실시간
# 검색으로 넘어갈 수 있게 한다.
#
# 0.5는 실측 분포와 안 맞았다 — Upstage 4096차원 임베딩은 코사인 유사도 자체가
# 압축돼 나와서, 실제로 잘 맞는 취향("바다를 좋아하고 회를 좋아하는 여행" ↔ 강릉 실제
# 회센터/맛집)도 top-5가 0.28~0.30에 그치고, 완전히 무관한 취향("우주정거장에서
# 무중력 체험")조차 0.22~0.27이 나온다(직접 질의해서 확인함). 즉 0.5 기준으로는
# 강릉/제주/경주 등 어떤 도시·취향 조합도 단 하나도 통과하지 못해서 retrieve_places_by_taste가
# 사실상 항상 빈 리스트를 반환했고, TourAPI 실시간 검색 폴백이 없는 _search_restaurant_places/
# _search_lodging_place는 매번 결과 없음으로 끝나 점심/저녁/체크인 일정이 통째로 빠지는
# 원인이었다. 관련 있는 취향과 무관한 취향의 실측 구간이 겹치는 부분(0.25~0.28) 아래인
# 0.2를 기준으로 낮춰서, 임베딩 자체가 실패한(0에 가까운) 완전 무관 매칭만 걸러내고
# 정상 범위는 통과시킨다.
MIN_SIMILARITY = 0.2


def retrieve_places_by_taste(
    taste_text: str,
    match_count: int = 10,
    city: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    사용자 취향 문장과 의미적으로 가장 비슷한 관광지를 유사도 순으로 반환합니다.
    city를 넘기면 해당 도시의 관광지로 후보를 제한합니다. similarity가 MIN_SIMILARITY
    미만인 결과는 취향과 무관하다고 보고 제외합니다.
    """

    query_embedding = embed_user_taste(taste_text)
    results = search_similar_places(query_embedding, match_count=match_count, city=city)
    return [
        item for item in results
        if item.get("similarity") is None or item.get("similarity") >= MIN_SIMILARITY
    ]

"""
프론트엔드 UI의 인용 배지(예: GUIDE-HEAT-ELDERLY-001)를 위한 ID 생성.
DB에는 이런 코드가 없어서(숫자 PK만 있음), 재난유형+카테고리 맥락 기반으로
일관되게 생성함. 실제 안전 지침 내용을 지어내는 게 아니라 "표시용 라벨"만
만드는 것이므로 안전 도메인 정확성에는 영향 없음.
"""

DISASTER_TYPE_EN = {
    "폭염": "HEAT", "호우": "RAIN", "대설": "SNOW", "한파": "COLD",
    "강풍": "WIND", "산사태": "LANDSLIDE", "홍수": "FLOOD", "태풍": "TYPHOON",
    "지진": "EARTHQUAKE", "화재": "FIRE", "산불": "WILDFIRE", "붕괴": "COLLAPSE",
    "풍랑": "SWELL", "가뭄": "DROUGHT", "지진해일": "TSUNAMI", "안개": "FOG",
    "황사": "DUST", "미세먼지": "DUST", "환경오염사고": "POLLUTION",
    "여름철물놀이": "WATER", "해양오염사고": "MARINE", "응급처치": "FIRSTAID",
}


def _infer_suffix(cate_nm3: str) -> str:
    """카테고리 세부단계 문구에서 대상/상황을 유추 (없으면 GENERAL)"""
    text = cate_nm3 or ""
    if any(kw in text for kw in ["노약자", "취약", "어린이", "고령"]):
        return "ELDERLY"
    if any(kw in text for kw in ["대피", "침수", "고립"]):
        return "EVACUATION"
    if any(kw in text for kw in ["차량", "운전"]):
        return "VEHICLE"
    return "GENERAL"


def build_citation_ids(retrieved_guidelines: list) -> list:
    """
    검색된 행동요령 리스트 -> ["GUIDE-HEAT-ELDERLY-001", ...] 형태로 변환.
    같은 (재난유형, suffix) 조합은 순번을 이어서 매김.
    """
    counters: dict = {}
    citation_ids = []

    for g in retrieved_guidelines:
        dtype = g.get("matched_disaster_type") or g.get("cate_nm2") or "기타"
        code = DISASTER_TYPE_EN.get(dtype, "SAFETY")
        suffix = _infer_suffix(g.get("cate_nm3"))

        key = f"{code}-{suffix}"
        counters[key] = counters.get(key, 0) + 1
        citation_id = f"GUIDE-{key}-{counters[key]:03d}"

        citation_ids.append(citation_id)

    return citation_ids
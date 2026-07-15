"""Detect user requirements that the current dong-level schema cannot verify.

These are not hard failures. The service can still recommend with available
signals, but the explanation must clearly separate supported evidence from
requirements that need additional/mock data.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UnsupportedRequirement:
    key: str
    label: str
    reason: str


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def detect_unsupported_requirements(text: str) -> list[UnsupportedRequirement]:
    t = text.lower()
    found: list[UnsupportedRequirement] = []

    def add(key: str, label: str, reason: str) -> None:
        if not any(item.key == key for item in found):
            found.append(UnsupportedRequirement(key=key, label=label, reason=reason))

    if _contains_any(t, ("방음", "소음", "조용")):
        add(
            "noise_soundproofing",
            "조용함/소음/방음",
            "현재 데이터에는 행정동별 소음도나 건물·호실 단위 방음 성능이 없습니다.",
        )

    rent_terms = ("월세", "전세", "보증금", "관리비", "집값", "주거비", "임대료")
    rent_need_terms = (
        "부담", "비싸", "저렴", "싼", "가격", "예산", "시세", "중위", "낮은",
        "높지", "아끼", "절약",
    )
    # "현재 주거는 전·월세예요" 같은 배경 설명은 한계로 잡지 않는다.
    if _contains_any(t, rent_terms) and _contains_any(t, rent_need_terms):
        add(
            "rent_price",
            "월세/전세/주거비",
            "현재 추천 지표에는 행정동별 월세·전세 시세나 관리비 데이터가 없습니다.",
        )

    commute_need = (
        ("회사" in t or "직장" in t or "학교" in t) and
        _contains_any(t, ("까지", "30분", "소요시간", "통근", "출퇴근"))
    )
    if commute_need or _contains_any(t, ("실제 통근시간", "도어투도어", "door-to-door")):
        add(
            "door_to_door_commute",
            "실제 목적지 기반 통근시간",
            "현재 데이터는 지하철·버스 접근성 지표이며 특정 목적지까지의 실제 소요시간은 계산하지 않습니다.",
        )

    if _contains_any(t, ("남향", "채광", "일조", "햇빛", "자연광")):
        add(
            "sunlight_direction",
            "남향/채광/일조",
            "현재 데이터는 행정동 단위라 건물·호실별 방향, 층, 일조량을 직접 평가할 수 없습니다.",
        )

    if _contains_any(t, ("반려동물", "반려견", "반려묘", "강아지", "고양이", "펫")):
        add(
            "pet_friendliness",
            "반려동물 친화도",
            "동물병원 같은 업종 수는 일부 확인 가능하지만 반려동물 친화 주거환경, 출입 제한, 산책로 품질은 별도 데이터가 필요합니다.",
        )

    if _contains_any(t, ("학군", "초등학교", "중학교", "고등학교", "어린이집", "유치원")):
        add(
            "school_childcare",
            "학군/학교/어린이집",
            "현재 지표에는 학교·어린이집 접근성이나 학군 데이터가 포함되어 있지 않습니다.",
        )

    if _contains_any(t, ("주차", "주차장", "주차공간")):
        add(
            "parking",
            "주차 편의",
            "현재 데이터에는 건물·동네별 실제 주차 가능성이나 주차장 수요 데이터가 없습니다.",
        )

    return found


def format_unsupported_requirements(items: list[UnsupportedRequirement]) -> str:
    return " / ".join(f"{item.label}: {item.reason}" for item in items)

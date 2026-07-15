"""Post-process LLM intent outputs to keep tool calls conservative.

The LLM is allowed to interpret natural language, but it must not invent
facility requirements from background facts such as occupation. This module
keeps only explicitly requested facility categories and forces clarification for
vague preference-only questions.
"""
from __future__ import annotations

import re

_FACILITY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "버거": ("버거", "햄버거"),
    "헬스장": ("헬스장", "헬스", "피트니스", "gym"),
    "카페": ("카페", "커피"),
    "수영장": ("수영장", "수영"),
    "종합 스포츠시설": ("종합 스포츠시설", "운동시설", "스포츠시설"),
    "동물병원": ("동물병원", "반려동물 병원", "반려견 병원", "반려묘 병원"),
    "치킨": ("치킨",),
    "피자": ("피자",),
}

_FACILITY_CONTEXT_WORDS = (
    "가깝", "근처", "주변", "있", "많", "인프라", "시설", "가기", "다니",
    "이용", "자주", "필요", "좋", "원해", "중요",
)

_CONCRETE_PREFERENCE_KEYWORDS = (
    "안전", "밤", "치안", "범죄", "cctv", "무서",
    "지하철", "버스", "교통", "대중교통", "출퇴근", "통근", "야근", "역",
    "병원", "대형병원", "종합병원", "마트", "편의점", "장보", "쇼핑",
    "공원", "산책", "녹지", "자연", "러닝", "헬스", "운동",
    "카페", "버거", "햄버거", "반려동물", "동물병원",
    "조용", "방음", "소음", "주거비", "예산", "저렴", "부담", "시세", "통근시간",
    "남향", "채광", "주차", "학군", "어린이집", "학교",
)

_VAGUE_PATTERNS = (
    "잘 맞는",
    "괜찮",
    "살기 좋은",
    "좋은 동네",
    "아무 데",
    "아무데",
    "마음이",
    "편해지는",
    "삭막하지",
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _category_terms(category: str) -> tuple[str, ...]:
    terms = [category]
    compact = category.replace(" ", "")
    if compact != category:
        terms.append(compact)
    terms.extend(_FACILITY_SYNONYMS.get(category, ()))
    return tuple(dict.fromkeys(term for term in terms if term))


def explicitly_requested_categories(text: str, categories: list[str]) -> list[str]:
    """Keep categories whose label/synonym is explicitly present in the text.

    Generic words such as "편의", occupation words such as "회계사", or inferred
    adjacent professions such as "세무사" must not become facility categories.
    """
    normalized_text = _normalize(text)
    kept: list[str] = []
    for category in categories:
        for term in _category_terms(category):
            if _normalize(term) in normalized_text:
                kept.append(category)
                break
    return kept


def has_explicit_facility_request(text: str, categories: list[str]) -> bool:
    if explicitly_requested_categories(text, categories):
        return True
    t = text.lower()
    return any(word in t for word in _FACILITY_CONTEXT_WORDS) and any(
        term in t for terms in _FACILITY_SYNONYMS.values() for term in terms
    )


def has_concrete_preference(text: str, categories: list[str] | None = None) -> bool:
    t = text.lower()
    if any(keyword in t for keyword in _CONCRETE_PREFERENCE_KEYWORDS):
        return True
    if categories and has_explicit_facility_request(text, categories):
        return True
    return False


def should_force_clarification(text: str, categories: list[str] | None = None) -> bool:
    if not text.strip():
        return True
    t = text.lower()
    if not any(pattern in t for pattern in _VAGUE_PATTERNS):
        return False
    return not has_concrete_preference(text, categories)

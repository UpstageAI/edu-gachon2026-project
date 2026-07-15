from __future__ import annotations

import re

_INTEREST_ALIASES = {
    "요식업": ("요식", "외식", "음식", "식품", "카페", "베이커리", "디저트", "프랜차이즈"),
    "카페": ("요식", "외식", "음식", "식품", "카페", "베이커리", "디저트", "프랜차이즈"),
    "농업": ("농업", "농식품", "농촌", "귀농", "스마트팜"),
    "it": ("it", "ict", "ai", "소프트웨어", "디지털", "데이터", "클라우드"),
    "정보기술": ("it", "ict", "ai", "소프트웨어", "디지털", "데이터", "클라우드"),
    "콘텐츠": ("콘텐츠", "미디어", "영상", "게임", "웹툰", "문화"),
    "디자인": ("디자인", "브랜딩", "시각", "제품디자인"),
    "제조업": ("제조", "공장", "생산", "스마트공장"),
}


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def interest_search_terms(interest_fields: list[str] | None) -> set[str]:
    terms: set[str] = set()
    for field in interest_fields or []:
        compact = _compact(field)
        if not compact:
            continue
        terms.add(compact)
        for key, aliases in _INTEREST_ALIASES.items():
            if key in compact or compact in key:
                terms.update(_compact(alias) for alias in aliases)
    return terms


def policy_matches_interest(
    interest_fields: list[str] | None,
    *,
    title: str = "",
    category: str = "",
    support_content: str = "",
) -> bool:
    terms = interest_search_terms(interest_fields)
    if not terms:
        return False
    haystack = _compact(f"{title} {category} {support_content}")
    return any(term in haystack for term in terms)

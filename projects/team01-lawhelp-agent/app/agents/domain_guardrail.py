import re
from dataclasses import dataclass

from app.core.routing import DomainGuardrailResult


REAL_ESTATE_CATEGORY = "real_estate_rental"
WELFARE_CATEGORY = "welfare"
MIXED_CATEGORY = "mixed"
UNKNOWN_CATEGORY = "unknown"


@dataclass(frozen=True)
class DomainGuardrailDecision:
    result: DomainGuardrailResult
    domain_category: str = UNKNOWN_CATEGORY
    reason: str = "uncertain"
    domain_keyword_hits: tuple[str, ...] = ()
    extended_domain_hits: tuple[str, ...] = ()
    context_keyword_hits: tuple[str, ...] = ()
    out_of_scope_hits: tuple[str, ...] = ()


REAL_ESTATE_STRONG_PHRASES = (
    "주택임대차",
    "임대차",
    "임대인",
    "임차인",
    "전세사기",
    "전세피해",
    "전세피해확인서",
    "전세보증금반환보증",
    "전세금",
    "전세",
    "월세",
    "보증금",
    "확정일자",
    "전입신고",
    "우선변제권",
    "임차권등기명령",
    "계약갱신",
    "중개보수",
    "중개수수료",
    "장기수선충당금",
    "등기부",
    "집주인",
    "세입자",
    "공공임대주택",
    "국민임대주택",
    "영구임대주택",
    "행복주택",
    "장기전세임대주택",
    "분양전환공공임대주택",
    "통합공공임대주택",
    "무주택세대구성원",
    "아파트분양",
    "공공분양",
    "민간분양",
    "사전청약",
    "청약저축",
    "주택청약종합저축",
    "특별공급",
    "전매제한",
    "이사업체",
    "이삿짐",
    "월세현금영수증",
    "부동산거래신고",
)

WELFARE_STRONG_PHRASES = (
    "기초생활보장",
    "기초생활수급자",
    "생계급여",
    "주거급여",
    "의료급여",
    "교육급여",
    "기준중위소득",
    "소득인정액",
    "긴급복지지원",
    "긴급복지",
    "긴급지원",
    "1인가구",
    "안심귀가",
    "병원안심동행",
    "기초연금",
    "국민연금",
    "노령연금",
    "퇴직연금",
    "농지연금",
    "노인장기요양보험",
    "장기요양보험",
    "장기요양급여",
    "장기요양등급",
    "인지지원등급",
    "재가급여",
    "시설급여",
    "요양보호사",
    "가족요양비",
    "가족돌봄",
    "노인학대",
    "성년후견",
    "자살자유족",
    "자살시도",
    "건강보험",
    "직장가입자",
    "지역가입자",
    "건강검진",
    "난임지원",
    "양육수당",
    "자립준비청년",
    "보호종료아동",
    "노인일자리",
    "노인맞춤돌봄",
)

REAL_ESTATE_EXTENDED_PHRASES = (
    "상가임대차",
    "상가보증금",
    "권리금",
    "부동산매매",
    "매매계약",
    "계약금",
    "토지경계",
    "토지",
    "재개발",
    "재건축",
    "조합원분담금",
    "건축",
    "용도변경",
    "양도소득세",
    "취득세",
    "부동산세금",
)

WELFARE_EXTENDED_PHRASES = (
    "장애인연금",
    "장애인복지",
    "한부모가족",
    "아동양육비",
    "실업급여",
    "고용보험",
    "산업재해",
    "산재보험",
    "아동수당",
    "문화누리카드",
)

OUT_OF_SCOPE_PHRASES = (
    "회사복지",
    "복지포인트",
    "사내복지",
    "클라우드",
    "서버임대",
    "장비임대",
    "자동차보험",
    "자동차보험료",
    "연금술",
    "게임",
    "회사이사",
    "이사선임",
    "주주총회",
    "노인과바다",
    "우울증약",
    "약부작용",
    "복용시간",
    "복용법",
    "부당해고",
    "임금체불",
    "노동위원회",
    "이혼",
    "재산분할",
    "양육권",
    "상속포기",
    "유류분",
    "교통사고",
    "합의금",
    "폭행",
    "절도",
    "사기죄",
    "고소장",
    "음주운전",
    "환불",
    "소비자분쟁",
    "개인정보",
    "코딩",
    "파이썬",
    "서버오류",
    "날씨",
    "요리",
    "여행",
)

REAL_ESTATE_CONTEXT_TERMS = (
    "집",
    "주택",
    "아파트",
    "부동산",
    "계약",
    "계약서",
    "사기",
    "등기",
    "경매",
    "압류",
    "저당권",
    "이사",
    "분양",
    "청약",
)

WELFARE_CONTEXT_TERMS = (
    "지원",
    "급여",
    "보험",
    "연금",
    "복지",
    "노인",
    "치매",
    "우울증",
    "돌봄",
    "간병",
    "가족",
    "어머니",
    "부모님",
    "기억",
    "검사",
    "상담",
    "병원",
    "퇴사",
    "혼자사는",
    "안부",
)

_YEAR_PAYMENT_PATTERN = re.compile(r"\d+\s*년")


def classify_domain(question: str) -> DomainGuardrailDecision:
    normalized = _normalize(question)

    real_strong = _match_phrases(normalized, REAL_ESTATE_STRONG_PHRASES)
    welfare_strong = _match_phrases(normalized, WELFARE_STRONG_PHRASES)
    real_extended = _match_phrases(normalized, REAL_ESTATE_EXTENDED_PHRASES)
    welfare_extended = _match_phrases(normalized, WELFARE_EXTENDED_PHRASES)

    domain_hits = real_strong + welfare_strong
    extended_hits = real_extended + welfare_extended
    if domain_hits or extended_hits:
        return DomainGuardrailDecision(
            result=DomainGuardrailResult.IN_SCOPE,
            domain_category=_category_for_hits(
                real_strong + real_extended,
                welfare_strong + welfare_extended,
            ),
            reason="strong_keyword" if domain_hits else "extended_domain_keyword",
            domain_keyword_hits=domain_hits,
            extended_domain_hits=extended_hits,
        )

    real_context = _match_phrases(normalized, REAL_ESTATE_CONTEXT_TERMS)
    welfare_context = _match_phrases(normalized, WELFARE_CONTEXT_TERMS)
    context_category = _valid_context_category(normalized, real_context, welfare_context)
    if context_category is not None:
        return DomainGuardrailDecision(
            result=DomainGuardrailResult.IN_SCOPE,
            domain_category=context_category,
            reason="valid_keyword_combination",
            context_keyword_hits=tuple(dict.fromkeys(real_context + welfare_context)),
        )

    out_of_scope_hits = _match_phrases(normalized, OUT_OF_SCOPE_PHRASES)
    if out_of_scope_hits:
        return DomainGuardrailDecision(
            result=DomainGuardrailResult.OUT_OF_SCOPE,
            reason="explicit_out_of_scope",
            out_of_scope_hits=out_of_scope_hits,
        )

    return DomainGuardrailDecision(result=DomainGuardrailResult.UNCERTAIN)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.casefold())


def _match_phrases(normalized_text: str, phrases: tuple[str, ...]) -> tuple[str, ...]:
    hits = []
    for phrase in sorted(phrases, key=lambda item: len(_normalize(item)), reverse=True):
        if _normalize(phrase) in normalized_text:
            hits.append(phrase)
    return tuple(dict.fromkeys(hits))


def _category_for_hits(real_hits: tuple[str, ...], welfare_hits: tuple[str, ...]) -> str:
    if real_hits and welfare_hits:
        return MIXED_CATEGORY
    if real_hits:
        return REAL_ESTATE_CATEGORY
    if welfare_hits:
        return WELFARE_CATEGORY
    return UNKNOWN_CATEGORY


def _valid_context_category(
    normalized: str,
    real_context: tuple[str, ...],
    welfare_context: tuple[str, ...],
) -> str | None:
    real_valid = _has_real_estate_context(normalized, real_context)
    welfare_valid = _has_welfare_context(normalized, welfare_context)
    if real_valid and welfare_valid:
        return MIXED_CATEGORY
    if real_valid:
        return REAL_ESTATE_CATEGORY
    if welfare_valid:
        return WELFARE_CATEGORY
    return None


def _has_real_estate_context(normalized: str, hits: tuple[str, ...]) -> bool:
    hit_set = set(hits)
    return (
        {"집", "계약"}.issubset(hit_set)
        or {"집", "사기"}.issubset(hit_set)
        or {"주택", "계약"}.issubset(hit_set)
        or {"부동산", "계약"}.issubset(hit_set)
        or {"아파트", "분양"}.issubset(hit_set)
        or {"청약", "분양"}.issubset(hit_set)
        or {"이사", "계약"}.issubset(hit_set)
    )


def _has_welfare_context(normalized: str, hits: tuple[str, ...]) -> bool:
    hit_set = set(hits)
    return (
        {"혼자사는", "안부"}.issubset(hit_set)
        or {"어머니", "안부"}.issubset(hit_set)
        or {"부모님", "기억"}.issubset(hit_set)
        or {"기억", "검사", "지원"}.issubset(hit_set)
        or {"노인", "돌봄"}.issubset(hit_set)
        or {"우울증", "상담"}.issubset(hit_set)
        or {"가족", "돌봄"}.issubset(hit_set)
        or _has_pension_context(normalized, hit_set)
    )


def _has_pension_context(normalized: str, hit_set: set[str]) -> bool:
    if "연금" not in hit_set:
        return False
    return bool(
        _YEAR_PAYMENT_PATTERN.search(normalized)
        or any(keyword in normalized for keyword in ("냈", "납부", "가입", "받", "수령", "몇살", "언제"))
    )

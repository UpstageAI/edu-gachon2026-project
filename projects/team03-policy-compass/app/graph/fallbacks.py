from __future__ import annotations

import re
from typing import Any

from app.core.prompts import POLICY_SCOPE_REPLY
from app.core.regions import user_region_reference

STARTUP_KEYWORDS = ["창업", "스타트업", "사업을 시작", "사업 시작"]
JOB_SEEKING_KEYWORDS = ["구직", "취업 준비", "미취업", "취업활동", "일자리"]
TRAINING_KEYWORDS = ["훈련", "교육", "내일배움", "국비", "강의", "과정", "수강", "배우"]
RECRUITMENT_KEYWORDS = ["채용", "채용공고", "구인공고", "공고", "인턴", "신입", "공채", "채용행사"]
EMPLOYED_KEYWORDS = ["재직", "직장인", "다니고 있"]
STUDENT_KEYWORDS = ["대학생", "재학"]
OUT_OF_SCOPE_KEYWORDS = ["세무 상담", "법률 자문", "소송", "대출 상담", "회계 처리", "변호사"]
EXPLAIN_KEYWORDS = [
    "무엇인가요",
    "뭐야",
    "뭐가 좋아",
    "좋은 점",
    "장점",
    "단점",
    "도움",
    "왜",
    "설명해",
    "어떤 내용",
    "무슨 사업",
]
ELIGIBILITY_KEYWORDS = [
    "자격 되나요",
    "자격이 되나요",
    "자격이 되는지",
    "자격은",
    "자격 조건",
    "신청 가능한가요",
    "신청 가능해",
    "받을 수 있나요",
    "받을 수 있어",
    "해당되나요",
    "해당돼",
    "조건이 따로",
    "조건은",
]
RECOMMEND_KEYWORDS = [
    "추천",
    "받을 수 있는",
    "찾아",
    "알려",
    "지원받",
    "신청 가능",
    "신청하고 싶",
    "궁금",
    "정보를 얻",
    "정보가 필요",
    "정보좀",
    "정보 좀",
    "보여",
    "조회",
    "목록",
    "뭐 있어",
    "원해",
    "원하는",
]

SUPPORTED_DOMAIN_KEYWORDS = (
    "청년",
    "정책",
    "지원사업",
    "지원금",
    "주거",
    "거주지원",
    "월세",
    "전세",
    "금융",
    "자산형성",
    "복지",
    "생활지원",
    "문화지원",
    "참여",
    "고용24",
    "고용 24",
    "온통청년",
    "온통 청년",
    *JOB_SEEKING_KEYWORDS,
    *TRAINING_KEYWORDS,
    *RECRUITMENT_KEYWORDS,
)

YOUTH_POLICY_SPECIFIC_QUERY_KEYWORDS = (
    "월세",
    "전세",
    "주거비",
    "금융",
    "자산형성",
    "문화",
    "건강",
)

_NAMED_POLICY_PATTERN = re.compile(r"([가-힣A-Za-z0-9·+-]{2,40}(?:계좌|수당|지원금|사업|정책|카드|제도))")
_OFFICIAL_LOOKUP_MARKERS = (
    "현재 조건",
    "신청 조건",
    "지원 조건",
    "자격",
    "지원 대상",
    "신청 대상",
    "마감",
    "언제까지",
    "최신",
)

INTEREST_KEYWORDS = {
    "데이터 분석": ["데이터 분석", "데이터", "분석가", "분석"],
    "클라우드 엔지니어": ["클라우드", "AWS", "Azure", "DevOps"],
    "AI": ["AI", "인공지능", "머신러닝"],
    "IT": ["IT", "개발", "프로그래밍", "소프트웨어", "앱"],
    "요식업": ["요식업", "카페", "음식점", "식당"],
    "제조업": ["제조업", "제조", "공장"],
    "디자인": ["디자인"],
    "콘텐츠": ["콘텐츠", "영상", "크리에이터"],
    "농업": ["농업", "귀농"],
}

POLICY_TOPIC_KEYWORDS = {
    "일자리": ["취업", "구직", "일자리", "일경험"],
    "주거": ["주거", "거주지원", "월세", "전세", "임대", "주거비"],
    "교육·직업·훈련": ["교육", "직업훈련", "역량", "자격증"],
    "금융·복지·문화": ["금융", "자산", "복지", "생활", "문화", "건강"],
    "참여·기반": ["참여", "권리", "청년활동", "커뮤니티"],
}

_STRONG_PENDING_CANCEL_MARKERS = (
    "취소해",
    "취소할게",
    "그만해",
    "그만할래",
    "그만할게",
    "필요없어",
    "안할래",
    "안할게",
)
_SOFT_PENDING_CANCEL_UTTERANCES = {"됐어", "그건됐어", "이건됐어"}
_REGION_UNRESTRICTED_PATTERNS = (
    re.compile(r"지역\s*(?:은\s*)?(?:상관\s*없이|무관하게|제한\s*없이)"),
    re.compile(r"(?:전국|어디든|아무\s*지역(?:이나|이든))\s*(?:으로|에서|상관없이)?"),
)

_POLICY_RESOURCE_MARKERS = (
    "정책",
    "지원사업",
    "지원 제도",
    "지원제도",
    "제도",
    "지원금",
    "수당",
    "장려금",
    "혜택",
    "자격",
    "지원 조건",
    "신청 조건",
)
_TRAINING_RESOURCE_MARKERS = (
    "훈련과정",
    "훈련 과정",
    "교육과정",
    "교육 과정",
    "국비과정",
    "국비 과정",
    "수강과정",
    "수강 과정",
    "훈련기관",
    "교육기관",
    "커리큘럼",
    "개강",
    "강의",
    "수강",
    "학원",
)
_RECRUITMENT_RESOURCE_MARKERS = (
    "채용공고",
    "채용 공고",
    "구인공고",
    "구인 공고",
    "공채속보",
    "공채 속보",
    "채용행사",
    "채용 행사",
    "채용박람회",
    "모집공고",
    "모집 공고",
    "채용 중",
)
_MIXED_REQUEST_MARKERS = ("둘 다", "두 가지", "같이", "함께", "각각", "모두")

_PENDING_SLOT_PROFILE_FIELDS = {
    "region": {"region"},
    "training_region": {"region"},
    "work_region": {"region"},
    "region_detail": {"region"},
    "age": {"age"},
    "desired_job": {"desired_job", "interest_fields"},
    "policy_topic": {"policy_topic", "preferred_support_type", "interest_fields"},
    "employment_status": {"employment_status"},
}

_BRIEF_SOCIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "greeting",
        re.compile(r"^(?:안녕(?:하세요|하십니까)?|반가워(?:요)?|반갑습니다|하이|헬로|hello|hi)$", re.IGNORECASE),
    ),
    (
        "capability",
        re.compile(r"^(?:뭐해(?:요)?|뭐하고있어(?:요)?|무엇을해(?:요)?|무슨일을해(?:요)?|잘지내(?:요)?)$"),
    ),
    (
        "thanks",
        re.compile(r"^(?:고마워(?:요)?|감사해(?:요)?|감사합니다|도움됐어(?:요)?|도움됐습니다)$"),
    ),
)


def brief_social_message_kind(text: str) -> str | None:
    """Classify only high-confidence, self-contained social utterances.

    The LLM remains the primary semantic router.  This narrow detector is used
    as a safety invariant and for a stable, friendly response after routing; it
    must not swallow a greeting that also contains a real policy question.
    """

    compact = re.sub(r"[\s.!?~,'\"…]+", "", text or "").strip()
    if not compact:
        return None
    return next((kind for kind, pattern in _BRIEF_SOCIAL_PATTERNS if pattern.fullmatch(compact)), None)


def is_brief_social_message(text: str) -> bool:
    return brief_social_message_kind(text) is not None


def is_startup_support_request(text: str) -> bool:
    """Detect startup-support requests that must use the fixed redirect path.

    Recruitment or training questions about a startup are kept in their own
    supported domains instead of being intercepted by the startup redirect.
    """

    has_startup_term = any(keyword in text for keyword in STARTUP_KEYWORDS)
    supported_training_terms = ("국비", "내일배움", "직업훈련", "훈련과정")
    has_supported_tool_intent = any(keyword in text for keyword in RECRUITMENT_KEYWORDS) or any(
        keyword in text for keyword in supported_training_terms
    )
    return has_startup_term and not has_supported_tool_intent


def _policy_topic(text: str) -> str | None:
    for topic, keywords in POLICY_TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return topic
    if any(keyword in text for keyword in ("내일배움", "국비", "훈련", "교육", "과정")):
        return "교육·직업·훈련"
    if any(keyword in text for keyword in ("채용", "공채", "구인")):
        return "일자리"
    return None


def _has_interest_field(text: str) -> bool:
    return any(keyword in text for keywords in INTEREST_KEYWORDS.values() for keyword in keywords)


def source_selection_plan(text: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    """Separate the requested information object from its overlapping topic.

    Youth Center and Work24 both cover employment/training, but they expose
    different resources: support policies versus concrete courses/postings.
    ``primary_source`` is executable in phase 1, while ``companion_sources`` is
    an explicit handoff/CTA contract and never triggers a silent second search.
    """

    normalized = " ".join((text or "").split())
    compact = re.sub(r"\s+", "", normalized).lower()
    topic = _policy_topic(normalized)

    explicit_youth = "온통청년" in compact
    explicit_work24 = "고용24" in compact or "hrdnet" in compact
    policy_resource = any(marker in normalized for marker in _POLICY_RESOURCE_MARKERS)
    training_resource = any(marker in normalized for marker in _TRAINING_RESOURCE_MARKERS)
    recruitment_resource = any(marker in normalized for marker in _RECRUITMENT_RESOURCE_MARKERS)
    mixed_requested = any(marker in normalized for marker in _MIXED_REQUEST_MARKERS)
    training_resource = training_resource or bool("과정" in normalized and ("실제" in normalized or explicit_work24))
    named_training_card = any(marker in normalized for marker in ("내일배움카드", "국민내일배움카드"))
    policy_resource = policy_resource or bool(named_training_card and not training_resource)
    recruitment_resource = recruitment_resource or bool(explicit_work24 and "공고" in normalized)

    # A region + concrete field + funded-training wording is a course discovery
    # request even if the user omits the literal word "과정".
    contextual_training_discovery = bool(
        (user_region_reference(normalized) or _has_interest_field(normalized))
        and any(marker in normalized for marker in ("국비", "내일배움", "훈련", "배우"))
        and not any(marker in normalized for marker in ("자격", "조건", "제도", "정책", "지원금"))
    )
    training_resource = training_resource or contextual_training_discovery

    companion_sources: list[str] = []
    selection_basis = "topic_default"
    if explicit_youth:
        primary_source = "youth_policy"
        resource_type = "policy"
        selection_basis = "explicit_youth_center"
    elif explicit_work24 and recruitment_resource:
        primary_source = "recruitment"
        resource_type = "recruitment_listing"
        selection_basis = "explicit_work24_recruitment"
    elif explicit_work24 and (training_resource or topic == "교육·직업·훈련"):
        primary_source = "training"
        resource_type = "training_course"
        selection_basis = "explicit_work24_training"
    elif mixed_requested and policy_resource and (training_resource or recruitment_resource):
        primary_source = "youth_policy"
        resource_type = "mixed"
        selection_basis = "explicit_mixed_request"
        if training_resource:
            companion_sources.append("training")
        if recruitment_resource:
            companion_sources.append("recruitment")
    elif policy_resource:
        primary_source = "youth_policy"
        resource_type = "policy"
        selection_basis = "policy_resource"
    elif recruitment_resource:
        primary_source = "recruitment"
        resource_type = "recruitment_listing"
        selection_basis = "recruitment_resource"
    elif training_resource:
        primary_source = "training"
        resource_type = "training_course"
        selection_basis = "training_resource"
    elif any(keyword in normalized for keyword in RECRUITMENT_KEYWORDS):
        primary_source = "recruitment"
        resource_type = "recruitment_listing"
    elif any(keyword in normalized for keyword in TRAINING_KEYWORDS):
        primary_source = "training"
        resource_type = "training_course"
    else:
        primary_source = "youth_policy"
        resource_type = "policy"

    if not companion_sources:
        if primary_source == "training":
            companion_sources.append("youth_policy")
        elif primary_source == "recruitment":
            companion_sources.append("youth_policy")
        elif primary_source == "youth_policy" and topic == "교육·직업·훈련":
            companion_sources.append("training")
        elif primary_source == "youth_policy" and topic == "일자리":
            companion_sources.append("recruitment")

    return {
        "primary_source": primary_source,
        "companion_sources": list(dict.fromkeys(source for source in companion_sources if source != primary_source)),
        "resource_type": resource_type,
        "topic": topic,
        "selection_basis": selection_basis,
        "source_is_explicit": selection_basis != "topic_default",
    }


def classify_request_kind(text: str, profile: dict[str, Any] | None = None) -> str:
    return str(source_selection_plan(text, profile)["primary_source"])


def extract_training_search_keyword(text: str) -> str | None:
    rules = [
        (("데이터", "분석"), "데이터 분석"),
        (("빅데이터",), "빅데이터"),
        (("인공지능",), "인공지능"),
        (("AI",), "AI"),
        (("클라우드",), "클라우드 엔지니어"),
        (("개발",), "개발"),
        (("프로그래밍",), "프로그래밍"),
        (("마케팅",), "마케팅"),
        (("디자인",), "디자인"),
    ]
    for keywords, result in rules:
        if all(keyword in text for keyword in keywords):
            return result
    return None


def extract_youth_policy_search_keyword(text: str) -> str | None:
    """LLM 장애 시에도 구체적인 청년정책 하위 유형을 넓히지 않는다."""

    compact = re.sub(r"\s+", "", text)
    return next((keyword for keyword in YOUTH_POLICY_SPECIFIC_QUERY_KEYWORDS if keyword in compact), None)


def extract_named_policy_query(text: str) -> str | None:
    """Extract a named program for deterministic official-data lookup."""

    match = _NAMED_POLICY_PATTERN.search(re.sub(r"\s+", "", text or ""))
    return match.group(1) if match else None


def has_supported_domain(text: str) -> bool:
    return any(keyword in text for keyword in SUPPORTED_DOMAIN_KEYWORDS)


def heuristic_route(text: str) -> str:
    if is_startup_support_request(text):
        return "OUT_OF_SCOPE"
    supported_domain = has_supported_domain(text)
    explicit_youth_policy_context = "청년" in text and any(
        keyword in text for keyword in ("정책", "지원사업", "지원금", "지원 제도")
    )
    if any(keyword in text for keyword in OUT_OF_SCOPE_KEYWORDS) and not explicit_youth_policy_context:
        return "OUT_OF_SCOPE"
    contextual_program_reference = bool(re.search(r"(?:이|그|해당)\s*(?:사업|정책|제도)", text))
    if (supported_domain or contextual_program_reference) and any(keyword in text for keyword in ELIGIBILITY_KEYWORDS):
        return "ELIGIBILITY_CHECK"
    explicit_explanation = supported_domain and any(keyword in text for keyword in EXPLAIN_KEYWORDS if keyword != "왜")
    policy_why_question = "왜" in text and any(
        keyword in text for keyword in ("정책", "지원사업", "지원금", "국비", "훈련", "채용", "내일배움")
    )
    if explicit_explanation or policy_why_question:
        return "EXPLAIN"
    availability_question = re.search(
        r"(?:정책|지원사업|지원금|과정|훈련|채용(?:공고|정보)?).{0,10}(?:있어|있나요|있을까|없어|없나요)",
        text,
    )
    if supported_domain and (any(keyword in text for keyword in RECOMMEND_KEYWORDS) or availability_question):
        return "RECOMMEND"
    return "GENERAL"


def routing_plan(text: str, profile: dict[str, Any] | None = None) -> dict[str, str | None]:
    intent = heuristic_route(text)
    if intent == "RECOMMEND":
        request_kind = classify_request_kind(text, profile)
        return {
            "intent": intent,
            "action": "SEARCH",
            "response_mode": "recommend",
            "request_kind": request_kind,
            "search_query": extract_youth_policy_search_keyword(text) if request_kind == "youth_policy" else None,
        }
    if intent == "ELIGIBILITY_CHECK":
        return {
            "intent": intent,
            "action": "SEARCH",
            "response_mode": "eligibility",
            "request_kind": classify_request_kind(text, profile),
            "search_query": None,
        }
    if intent == "EXPLAIN":
        request_kind = classify_request_kind(text, profile)
        named_query = extract_named_policy_query(text)
        narrow_policy_query = extract_youth_policy_search_keyword(text) if request_kind == "youth_policy" else None
        requires_official_lookup = bool(
            named_query or narrow_policy_query or any(marker in text for marker in _OFFICIAL_LOOKUP_MARKERS)
        )
        if requires_official_lookup:
            return {
                "intent": intent,
                "action": "SEARCH",
                "response_mode": "explain",
                "request_kind": request_kind,
                "search_query": narrow_policy_query or named_query,
            }
        return {
            "intent": intent,
            "action": "RESPOND",
            "response_mode": "explain",
            "request_kind": "general",
            "search_query": None,
        }
    if intent == "OUT_OF_SCOPE":
        return {
            "intent": intent,
            "action": "RESPOND",
            "response_mode": "out_of_scope",
            "request_kind": "general",
            "search_query": None,
        }
    return {
        "intent": intent,
        "action": "RESPOND",
        "response_mode": "general",
        "request_kind": "general",
        "search_query": None,
    }


def heuristic_extract_profile(text: str) -> dict[str, Any]:
    profile: dict[str, Any] = {}

    age_match = re.search(r"(?<!\d)(\d{1,3})\s*(?:살|세)(?!\d)", text)
    if age_match:
        profile["age"] = int(age_match.group(1))

    if region := user_region_reference(text):
        profile["region"] = region

    if any(keyword in text for keyword in JOB_SEEKING_KEYWORDS):
        profile["employment_status"] = "unemployed_seeking_job"
    elif any(keyword in text for keyword in EMPLOYED_KEYWORDS):
        profile["employment_status"] = "employed"
    elif any(keyword in text for keyword in STUDENT_KEYWORDS):
        profile["employment_status"] = "student"

    matched_fields = [
        field for field, keywords in INTEREST_KEYWORDS.items() if any(keyword in text for keyword in keywords)
    ]
    if matched_fields:
        profile["interest_fields"] = matched_fields
        profile["desired_job"] = matched_fields[0]

    for topic, keywords in POLICY_TOPIC_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            profile["policy_topic"] = topic
            break

    desired_job_match = re.search(r"([가-힣A-Za-z0-9+# ]{2,20})\s*(쪽|분야|직무)로", text)
    if desired_job_match and not profile.get("desired_job"):
        profile["desired_job"] = desired_job_match.group(1).strip()

    if "지원금" in text:
        profile["preferred_support_type"] = "지원금"
    elif any(keyword in text for keyword in TRAINING_KEYWORDS):
        profile["preferred_support_type"] = "훈련"
    elif any(keyword in text for keyword in RECRUITMENT_KEYWORDS):
        profile["preferred_support_type"] = "채용"

    return profile


def is_pending_cancel(text: str) -> bool:
    """Recognize an explicit cancellation only while a pending task exists."""

    compact = re.sub(r"\s+", "", text)
    if any(marker in compact for marker in _STRONG_PENDING_CANCEL_MARKERS):
        return True
    return compact.rstrip(".!?~") in _SOFT_PENDING_CANCEL_UTTERANCES


def is_region_unrestricted_request(text: str) -> bool:
    """Treat region-free discovery as a turn filter operation, not profile deletion."""

    normalized = " ".join((text or "").split())
    return any(pattern.search(normalized) for pattern in _REGION_UNRESTRICTED_PATTERNS)


def pending_answer_fills_required_slot(text: str, pending: dict[str, Any]) -> bool:
    """Allow pending resume only when this turn supplies awaited profile data."""

    extracted = heuristic_extract_profile(text)
    if not extracted:
        return False

    required_slots = pending.get("required_slots") or []
    if not required_slots:
        # Backward-compatible handling for pending rows saved before required_slots.
        return True

    extracted_fields = set(extracted)
    return any(extracted_fields.intersection(_PENDING_SLOT_PROFILE_FIELDS.get(slot, {slot})) for slot in required_slots)


def general_reply(query: str) -> str:
    if any(keyword in query for keyword in ("국비", "내일배움", "훈련", "교육")):
        return (
            "국비지원 훈련은 취업이나 직무 전환을 준비할 때 교육비 부담을 줄이고, "
            "필요한 직무 역량을 체계적으로 배울 수 있다는 점이 좋아요.\n\n"
            "- 장점: 자비부담을 낮출 수 있고, 데이터 분석/개발/사무 등 직무별 과정을 비교할 수 있어요.\n"
            "- 활용 포인트: 과정명보다 커리큘럼, 훈련기관, 수료 후 포트폴리오/취업지원 여부를 같이 보세요.\n"
            "- 주의점: 수강 가능 여부, 자비부담액, 출석 기준, 훈련장려금 여부는 과정마다 달라요.\n"
            "- 확인처: 고용24 국민내일배움카드 훈련과정 상세 화면에서 최신 조건을 확인해야 해요."
        )
    return POLICY_SCOPE_REPLY

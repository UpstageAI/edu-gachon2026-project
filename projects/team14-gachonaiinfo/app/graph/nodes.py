"""LangGraph 노드: router / rag / tool / response."""

import json
import logging
import re
from datetime import datetime
from typing import Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_upstage import ChatUpstage
from pydantic import BaseModel, Field

from app import config
from app.core.admission import (
    applicable_curriculum_year,
    extract_admission_year,
    is_year_sensitive_question,
    parse_year_reply,
)
from app.core.prompts import (
    CONTACT_GROUNDING,
    GUARDRAIL_GROUNDING,
    RAG_GROUNDING,
    RECOMMEND_COURSES_RULES,
    RESPONSE_PROMPT,
    ROUTER_PROMPT,
    TOOL_GROUNDING,
    build_link_hint,
    detect_link_topics,
)
from app.graph.state import AgentState
from app.observability import record_rag_observation
from app.repositories.contacts import contact_phone, format_contact, match_contact
from app.repositories.rag import get_rag_repository
from app.services.reminder_time import apply_time_update, now_kst, parse_remind_at
from app.tools.executor import ToolExecutor

logger = logging.getLogger("app.rag")


# "none" = 카테고리 미분류(전체 검색). Optional(null)보다 명시 값이 구조화 출력에서 안정적.
CATEGORY_L1 = Literal[
    "graduation",
    "course",
    "academic_calendar",
    "social_service",
    "leave_return",
    "contact",
    "none",
]


class IntentRoute(BaseModel):
    """LLM은 의도+카테고리만 분류. (숫자 인자 추출은 구조화 출력이 불안정하여 규칙으로 처리)"""

    intent: Literal["chat", "rag", "tool"] = Field(description="사용자 의도")
    category_l1: CATEGORY_L1 = Field(
        default="none",
        description="intent=rag 일 때 질문이 속한 카테고리. 판단 어려우면 'none'.",
    )


# chat 오분류 안전망: 예전엔 "사실 정보 신호 블랙리스트"에 있는 단어가 있어야만
# rag로 되돌렸는데("졸업"/"학점"/... 없으면 그냥 chat 통과), "학년별로 알려줘"처럼
# 목록에 없는 표현은 그대로 chat으로 빠져 근거 문서 하나 없이 LLM이 학과 정보를
# (가짜 과목명·전화번호·이메일까지) 지어내는 사고로 이어졌다.
# ROUTER_PROMPT 자체가 "chat은 인사/감사/잡담/사용법 정도로 매우 좁게"라고 명시하므로,
# 블랙리스트 대신 화이트리스트로 뒤집는다: 진짜 잡담으로 보이는 짧은 인사/감사/작별/
# 사용법 질문이 아니면 전부 rag로 보내 최소한 가드레일(문의처 안내)을 거치게 한다.
_SMALLTALK_PATTERNS = (
    "안녕",
    "hi",
    "hello",
    "헬로",
    "고마워",
    "고마웠",
    "감사",
    "고맙",
    "잘가",
    "바이",
    "bye",
    "수고",
    "뭘 도와",
    "뭐 도와",
    "무엇을 도와",
    "어떻게 써",
    "어떻게 쓰",
    "사용법",
    "어떻게 사용",
    "넌 누구",
    "너는 누구",
    "넌 뭐야",
    "너는 뭐야",
    "너 뭐하는",
)


def _looks_like_smalltalk(text: str) -> bool:
    stripped = text.strip()
    low = stripped.lower()
    return any(p in stripped or p in low for p in _SMALLTALK_PATTERNS)


# ── 학과 스코프 가드레일 ──────────────────────────────────────────────────
# 이 챗봇은 인공지능학과(구 AI·소프트웨어학부) 전용이다. 다른 학과(예: 컴퓨터공학과,
# 전자공학과, 간호학과…)를 물으면 인공지능학과 자료로 답하면 안 되고 "전용 챗봇"임을
# 안내해야 한다. RESPONSE_PROMPT에 "다른 학과명이 없으면 인공지능학과로 답하라"는
# 지시는 있으나 '다른 학과명이 있을 때' 거절 규칙이 없었고, 프롬프트 지시는
# Solar-pro가 무시하는 사례가 관측돼(과목 추천 환각 참고) 결정적 규칙으로 막는다.
_INSCOPE_DEPTS = ("인공지능", "소프트웨어", "ai")
# 학과명이 아니라 일반 지시어("우리학과", "타학과" 등)는 스코프 밖으로 보지 않는다.
_GENERIC_DEPT_PREFIX = {"우리", "저희", "본인", "타", "다른", "무슨", "어느", "해당", "각", "본"}
# "OO공학과/OO학과/OO학부" 형태의 학과명 언급을 잡는다. 접두(OO)는 붙어있는
# 한글/영문 2자 이상만(학과명 없이 " 학과 사무실"처럼 띄어 쓴 일반어는 매칭 안 됨).
_DEPT_MENTION_RE = re.compile(r"([가-힣A-Za-z]{2,}?)(?:공학과|학과|학부)")


def detect_out_of_scope_department(text: str) -> str | None:
    """질문에 인공지능/소프트웨어 외의 학과명이 있으면 그 학과명을, 없으면 None.

    "컴퓨터공학과 졸업요건" -> "컴퓨터공학과" (스코프 밖).
    "인공지능학과 교육목표", "소프트웨어학과랑 차이", "우리 학과 사무실" -> None.
    """
    for m in _DEPT_MENTION_RE.finditer(text):
        prefix = m.group(1)
        low = prefix.lower()
        if prefix in _GENERIC_DEPT_PREFIX:
            continue
        # 인공지능/소프트웨어(및 그 조합, 예: "소프트웨어융합")로 시작하면 스코프 안.
        if any(low.startswith(d) or low.endswith(d) for d in _INSCOPE_DEPTS):
            continue
        return m.group(0)
    return None


# ── 범위밖 주제 가드레일 (학과 스코프와 별개) ────────────────────────────────
# 위 학과 스코프가 '다른 학과' 질문을 막는다면, 이건 우리 학과 범위이지만 이 챗봇이
# 자료를 보유하지 않는 학교 행정 소관 주제(등록금·기숙사비·셔틀·재수강·전과·계절학기)를
# 막는다. 이 주제들은 어휘가 겹쳐 리랭커 점수가 임계값을 넘어도(재수강↔수강포기,
# 전과↔졸업이수학점처럼 임베딩상 '진짜 이웃') 검색 문서가 실제 답을 담지 않는다.
# 스칼라 임계값으로는 정상질문(최저 0.469, "수강신청은 어떻게 해?" 0.497)과 점수대가
# 겹쳐 분리 불가함이 진단(eval/diag_guardrail.py)에서 확인됨 → 점수와 무관하게
# 가드레일로 보내 올바른 문의처(학사지원팀/생활관 등, contacts.json)로 안내한다.
# 검증: 전체 50 시나리오 중 answerable=True 질문에 하나도 안 걸림(오발동 0).
# 주의: '전과'는 신청기간 데이터만 있고 학점요건 데이터는 없어, 현재 스코프상 전과 전반을
#   문의처로 안내한다("전과 신청 언제야?"류도 학사지원팀으로 — 여전히 옳은 부서).
_OUT_OF_SCOPE_TOPICS = ("재수강", "계절학기", "셔틀", "전과", "등록금", "기숙사")


def _is_out_of_scope(text: str) -> bool:
    """자료 미보유(학교 행정 소관) 주제인지 — 어휘 겹침으로 점수가 높아도 가드레일 강제."""
    return any(topic in text for topic in _OUT_OF_SCOPE_TOPICS)


def _looks_like_reminder(text: str) -> bool:
    """이메일 리마인드 요청 신호가 있는지(주소 유무와 무관). 주소가 없어도
    reminder 흐름으로 보내 되묻기(awaiting_email)부터 시작하게 한다."""
    return any(sig in text for sig in _REMINDER_SIGNALS)


def _find_int(pattern: str, text: str) -> int | None:
    m = re.search(pattern, text)
    return int(m.group(1)) if m else None


def _detect_track(text: str) -> str | None:
    t = text.lower()
    if "aiot" in t:
        return "AIoT"
    if "vision" in t or "language" in t or "비전" in text or "자연어" in text:
        return "Vision & Language"
    if "intelligent" in t or "인텔리전트" in text:
        return "Intelligent SW"
    if "부트캠프" in text or "bootcamp" in t:
        return "AI부트캠프"
    return None


# 카테고리 키워드 분류(결정적). Solar 구조화출력이 category를 잘 안 채워 규칙을 주 경로로 쓴다.
# 순서 = 우선순위(위에서부터 먼저 매칭). 시간/일정 신호는 course 보다 먼저 둬 '언제' 질문을 일정으로.
_CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("social_service", ("사회봉사", "봉사활동", "봉사시간", "자원봉사", "봉사")),
    ("leave_return", ("휴학", "복학", "휴학연기", "복적")),
    (
        "graduation",
        ("졸업", "학위", "졸업인증", "외국어인증", "외국어 졸업", "졸업요건", "졸업학점"),
    ),
    (
        "academic_calendar",
        (
            "일정",
            "날짜",
            "언제",
            "며칠",
            "기간",
            "개강",
            "종강",
            "방학",
            "시험",
            "중간고사",
            "기말고사",
            "성적",
            "등록금",
            "계절학기",
        ),
    ),
    (
        "course",
        (
            "수강신청",
            "수강 신청",
            "수강정정",
            "수강 정정",
            "수강포기",
            "수강 포기",
            "수강",
            "과목",
            "교육과정",
            "커리큘럼",
            "트랙",
            "시간표",
            "강의",
            "전공필수",
            "전공선택",
            "이수구분",
        ),
    ),
    ("contact", ("전화번호", "연락처", "문의", "사무실", "어디에 물어", "어디로 문의")),
]


def classify_categories(text: str) -> list[str]:
    """질문을 category_l1 후보로 분류(키워드 규칙).

    기존에는 첫 매칭에서 즉시 return 해 "복학 기간"처럼 leave_return(복학)과
    academic_calendar(기간)에 동시에 걸치는 질문이 leave_return 하나로만
    좁혀져, 실제 일정 데이터가 담긴 문서가 검색 범위에서 빠지는 문제가 있었다.
    매칭되는 카테고리를 전부 모아 반환한다(순서 = 우선순위, 첫 항목이 주 카테고리).
    """
    return [cat for cat, words in _CATEGORY_KEYWORDS if any(w in text for w in words)]


# 키워드 표에 없는 표현(예: "복학 몇 월부터 가능해?")도 놓치지 않도록,
# 시간 신호가 있으면 관련 category_l1을 추가로 후보에 넣는다(하드 필터가 아니라 확장).
_TIME_SIGNAL_WORDS = (
    "기간",
    "언제",
    "며칠",
    "날짜",
    "마감",
    "일정",
    "개강",
    "종강",
    "까지",
    "부터",
)

_RELATED_CATEGORIES: dict[str, tuple[str, ...]] = {
    "leave_return": ("academic_calendar",),
    "social_service": ("academic_calendar",),
    "graduation": ("academic_calendar",),
    "course": ("academic_calendar",),
}


def expand_categories(text: str, categories: list[str]) -> list[str]:
    """시간 신호가 있으면 제도 카테고리에 연관된 academic_calendar 등을 추가."""
    if not categories or not any(w in text for w in _TIME_SIGNAL_WORDS):
        return categories

    expanded = list(categories)
    for cat in categories:
        for related in _RELATED_CATEGORIES.get(cat, ()):
            if related not in expanded:
                expanded.append(related)
    return expanded


# 이메일 리마인드(ADR-007): 이메일 주소는 개인정보이므로 LLM 구조화 출력으로
# 추출하지 않고, 이 정규식으로 규칙 기반 추출만 한다.
_EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"
_REMINDER_SIGNALS = (
    "리마인드",
    "메일로 알려줘",
    "메일로 보내",
    "이메일로 알려줘",
    "이메일로 보내",
    "이메일 보내",
    "메일 보내",
    "메일 발송",
    "이메일 발송",
    # "알림 보내줘"·"까먹지 않게 알림도 보내줘"처럼 '메일/이메일'을 명시하지 않고
    # '알림'으로 표현하는 리마인드 요청도 흐름을 시작하게 한다(기획서 시나리오2 입력).
    # 이메일 주소는 이후 되묻기 단계에서 규칙으로만 받는다(ADR-007).
    "알림 보내",
    "알림도 보내",
    "알림 예약",
    "까먹지 않게",
    "잊지 않게",
    "잊지 말",
)


def resolve_tool(text: str) -> tuple[str | None, dict | None]:
    """자연어에서 도구 이름과 인자를 규칙 기반으로 추출."""
    학년 = _find_int(r"([1-4])\s*학년", text)
    학기 = _find_int(r"([1-2])\s*학기", text)

    # 이메일 리마인드는 이제 별도의 멀티턴 흐름(reminder_node)이 처리한다.
    # router가 리마인드 신호를 보면 intent=reminder로 보내 "물어보고→확인받고→
    # 발송"을 거치므로, 여기(도구 규칙)서는 리마인드를 다루지 않는다.

    # 1) 졸업요건 계산: '학점' + (졸업/남음/이수완료를 암시하는 표현)
    # "전선 30학점 들었는데 얼마나 더 들어야돼?"처럼 '졸업'/'남'이 없이
    # 줄임말(전선·전필·교필·교선)만 쓰는 질문도 있어 트리거 표현을 넓혀둔다.
    # "4학년 1학기까지 120학점 채웠어"처럼 완료형 서술만 있고 질문형 신호가
    # 없는 경우("채워야"는 안 잡힘)도 있어 "채웠"/"이수했"도 추가한다 — 이게
    # 없으면 학년+학기 숫자 때문에 아래 2)번(과목 추천)으로 잘못 빠진다.
    _REMAINING_SIGNALS = ("졸업", "남", "더", "부족", "채워야", "얼마나", "채웠", "이수했")
    if "학점" in text and any(w in text for w in _REMAINING_SIGNALS):
        args: dict = {}
        for key, pat in [
            ("전공필수", r"(?:전공\s*필수|전필)\s*(\d+)"),
            ("전공선택", r"(?:전공\s*선택|전선)\s*(\d+)"),
            ("공통필수", r"(?:공통\s*필수|교필)\s*(\d+)"),
            ("공통선택", r"(?:공통\s*선택|교선)\s*(\d+)"),
        ]:
            v = _find_int(pat, text)
            if v is not None:
                args[key] = v
        if not args:
            # "전공 30학점"은 이 정규식이 잡는다. blanket `(\d+)학점` 폴백은 문장에
            # '전공'이 있을 때만 쓴다 — 없으면 "120학점 채웠어"의 120(총 이수학점)을
            # 전공 학점으로 오인해 틀린 계산을 낸다(전공 필요=72 대비 120 → 남은 0).
            v = _find_int(r"전공\D{0,3}(\d+)\s*학점", text)
            if v is None and "전공" in text:
                v = _find_int(r"(\d+)\s*학점", text)
            if v is not None:
                args["전공"] = v
        if args:
            return "calc_graduation_progress", args

    # 2) 과목 추천: 학년+학기 숫자 + 추천을 원한다는 신호가 함께 있을 때만.
    # 숫자만 보고 무조건 반환하면 "4학년 1학기까지 120학점 채웠어"처럼 학년/
    # 학기가 다른 맥락(예: 이수학점 서술)으로 언급된 문장까지 과목 추천으로
    # 잘못 라우팅된다.
    _RECOMMEND_SIGNALS = (
        "추천",
        "들어야",
        "뭐 들어",
        "무슨 과목",
        "개설",
        "과목",
        "수강",
        "시간표",
        "커리큘럼",
    )
    if 학년 and 학기 and any(w in text for w in _RECOMMEND_SIGNALS):
        args = {"학년": 학년, "학기": 학기}
        trk = _detect_track(text)
        if trk:
            args["트랙"] = trk
        return "recommend_courses", args

    return None, None


# 리마인드 pending_action(awaiting_email/awaiting_confirm) 진행 중에도, 사용자가
# 완전히 다른 학사 질문을 하면 흐름을 끊어야 한다(그렇지 않으면 계속 이메일/확인을
# 되묻는 문제가 생김). classify_categories/resolve_tool로 이미 잡히는 학사 키워드는
# 여기서 중복 나열하지 않고, 그 규칙들에 안 걸리는 일반적인 질문 표현만 추가한다.
_GENERIC_QUESTION_SIGNALS = ("알려줘", "궁금해", "뭐야", "무엇", "설명해")


def _looks_like_new_question(text: str) -> bool:
    """pending_action 중이어도 새 학사 질문으로 볼지 판별."""
    if classify_categories(text):
        return True
    if resolve_tool(text)[0] is not None:
        return True
    return any(w in text for w in _GENERIC_QUESTION_SIGNALS)


def get_llm() -> ChatUpstage:
    return ChatUpstage(
        api_key=config.UPSTAGE_API_KEY,
        model=config.LLM_MODEL,
        temperature=0.0,
        timeout=30,
        max_retries=2,
    )


tool_executor = ToolExecutor()


async def router_node(state: AgentState) -> dict:
    """LLM으로 의도 분류 + 규칙 기반 도구 판별(resolve_tool)이 우선. 규칙이 도구
    패턴을 찾으면 LLM 판단과 무관하게 intent=tool로 승격한다."""
    user_input = state["messages"][-1].content

    # 학번(입학년도) 세션 상태. admission_year/year_prompted는 체크포인터로 유지된다.
    admission_year = state.get("admission_year")
    year_prompted = state.get("year_prompted", False)
    pending = state.get("pending_action")

    # 이번 턴에 처리할 실제 질문. 보통 방금 입력이지만, 학번 되묻기 답변 턴에서는
    # '원래 질문'(pending.orig_query)으로 복원해 그 질문을 학번-aware하게 답한다.
    query = user_input

    # ── 학번 되묻기(ask_year) 답변 이어받기 ──
    if pending and pending.get("type") == "await_admission_year":
        reply_year = parse_year_reply(user_input)
        orig = pending.get("orig_query", user_input)
        if reply_year is not None:
            # 학번을 받음 → 저장하고 원 질문을 이어서 답한다.
            admission_year = reply_year
            query = orig
            pending = None
        elif _looks_like_new_question(user_input):
            # 학번 대신 새 학사 질문을 함 → 되묻기 폐기하고 이번 입력을 정상 라우팅.
            pending = None
        else:
            # "몰라" 등 학번을 못 얻음 → 다시 나그하지 않고(year_prompted=True 유지)
            # 원 질문을 현행 기준으로 진행한다.
            query = orig
            pending = None

    # 질문 안에 학번이 명시돼 있으면 흡수한다(예: "23학번 졸업요건").
    spont_year = extract_admission_year(query)
    if spont_year is not None:
        admission_year = spont_year

    # 진행 중인 리마인드 확인 대화가 있으면, 원칙적으로 이번 사용자 답을 그 대화의
    # 응답으로 이어받는다("응"·이메일 주소 같은 짧은 답이 rag/chat으로 새는 것을 막기
    # 위해 LLM 재분류를 건너뜀). 다만 사용자가 이메일/확인 대신 완전히 다른 학사
    # 질문을 하면 pending을 계속 붙잡고 있으면 안 되므로(계속 이메일을 되묻는 문제),
    # 그런 경우엔 pending을 버리고 아래 일반 라우팅으로 흘려보낸다.
    if pending and pending.get("type") == "reminder":
        stage = pending.get("stage")
        # 진행 중이라도 '다른 학과' 언급이 있으면 이어받지 않고 아래 학과 스코프
        # 가드레일로 흘려보낸다(그렇지 않으면 "컴퓨터공학과는 어때?" 같은 입력이
        # 새 질문으로 안 잡혀 이메일만 계속 되묻는 데 갇힌다).
        is_continuation = detect_out_of_scope_department(user_input) is None and (
            (
                stage == "awaiting_email"
                and (_extract_email(user_input) or any(w in user_input for w in _CONFIRM_NO))
            )
            or (stage == "awaiting_confirm" and _classify_confirm(user_input) != "unclear")
            or not _looks_like_new_question(user_input)
        )

        logger.info(
            json.dumps(
                {
                    "stage": "router",
                    "session_id": state.get("session_id"),
                    "question": user_input,
                    "intent": "reminder" if is_continuation else "reroute_new_question",
                    "reminder_stage": stage,
                },
                ensure_ascii=False,
            )
        )

        if is_continuation:
            return {
                "intent": "reminder",
                "retrieved_docs": [],
                "guardrail": False,
                "contact": None,
                "tool_result": None,
            }

        # 새 학사 질문으로 판단 → 리마인드 대기 상태를 버리고 아래 일반 라우팅을 계속 진행
        pending = None

    # ── 학과 스코프 가드레일 ──
    # 인공지능학과(구 AI·소프트웨어학부) 외 학과명이 질문에 있으면, 검색/도구/LLM을
    # 태우지 않고 "전용 챗봇"임을 결정적으로 안내한다(→ END). 인공지능학과 자료로
    # 다른 학과 질문에 답하는 환각을 근본적으로 차단한다.
    other_dept = detect_out_of_scope_department(query)
    if other_dept is not None:
        logger.info(
            json.dumps(
                {
                    "stage": "router",
                    "session_id": state.get("session_id"),
                    "question": query,
                    "intent": "out_of_scope",
                    "detected_department": other_dept,
                },
                ensure_ascii=False,
            )
        )
        return {
            "intent": "out_of_scope",
            "query": query,
            "admission_year": admission_year,
            "year_prompted": year_prompted,
            "applied_curriculum_year": None,
            "category_l1": None,
            "tool_name": None,
            "tool_args": None,
            "retrieved_docs": [],
            "guardrail": False,
            "contact": None,
            "tool_result": None,
            "pending_action": None,
        }

    # ── 규칙 우선 판정: 도구/리마인드로 확정되면 LLM 호출을 생략한다 ──────────
    # 이 두 경우엔 LLM이 뭐라 하든 아래 규칙(resolve_tool / _looks_like_reminder)이
    # intent를 덮어쓰고, 카테고리도 안 쓰므로 LLM 출력이 전부 버려졌다(순수 낭비).
    # 규칙을 새로 늘리는 게 아니라 기존 판정을 LLM '앞'으로 옮겨, 도구·리마인드 요청의
    # 라우터 LLM 지연(~1.5s)만 제거한다. chat/rag 구분과 카테고리 fallback은 여전히
    # LLM이 담당하므로 그 경로의 동작은 동일하다.
    # (학번 되묻기 답변 턴이면 query가 '원래 질문'으로 복원돼 있어 그 질문으로 판정한다.)
    # rag도 카테고리 키워드가 잡히면 그 자체로 학사 질문이 확정되고 검색 카테고리도
    # 규칙이 채우므로 LLM 출력이 쓰이지 않는다(잡담은 이 키워드들을 포함하지 않아 안전).
    # 실측상 LLM은 category를 거의 'none'으로만 반환해 기여가 얕았다 → 규칙이 카테고리를
    # 못 찾는 '키워드 밖' 질문(예: 교환학생)과 잡담에서만 LLM을 호출한다(이 경로 동작 동일).
    tool_name, tool_args = resolve_tool(query)
    tool_forced_by_rule = tool_name is not None
    llm_called = False
    llm_intent = "skipped"
    llm_category = "none"
    rule_categories: list[str] = []
    expanded_categories: list[str] = []
    categories: list[str] | None = None

    if tool_name is not None:
        intent = "tool"
    elif _looks_like_reminder(query):
        # (졸업계산·과목추천처럼 규칙으로 확정된 tool은 위에서 이미 잡혔으므로 여기선 순수 리마인드)
        intent = "reminder"
    elif rule_categories := classify_categories(query):
        # 카테고리 키워드 매칭 → 학사 질문(rag) 확정. LLM 불필요.
        intent = "rag"
    elif _looks_like_smalltalk(query) and not _is_out_of_scope(query):
        # 명백한 잡담(인사/감사/작별/사용법 등) → chat 확정. LLM 판단에 맡기면
        # "너 어떻게 쓰는 거야?"처럼 rag로 오분류돼 근거 없는 검색·가드레일 오발동으로
        # 새므로, 화이트리스트가 걸리면 LLM 호출 없이 chat으로 단락한다(지연도 절약).
        # 단, 범위밖 주제("셔틀 어떻게 써?")는 스몰토크로 새면 주제 가드레일(rag_node)을
        # 우회하므로 여기서 제외해 rag 경로로 보내 문의처 안내를 받게 한다.
        intent = "chat"
    else:
        # 카테고리 미매칭(키워드 밖 질문) → LLM으로 chat/rag 구분 + 카테고리 fallback
        llm_called = True
        structured_llm = get_llm().with_structured_output(IntentRoute)
        try:
            result = await structured_llm.ainvoke(
                [SystemMessage(content=ROUTER_PROMPT), HumanMessage(content=query)]
            )
            llm_intent = result.intent
            llm_category = result.category_l1
        except Exception:
            llm_intent = "rag"
        intent = llm_intent

        # LLM은 tool이라 했지만 규칙이 인자를 못 찾음 → RAG로 폴백
        if intent == "tool":
            intent = "rag"
        # 안전망: 위 잡담 화이트리스트를 안 통과했으므로(=명백한 잡담 아님) LLM이 chat이라
        # 해도 rag로 강제. (근거 문서 없이 LLM이 학과 정보를 지어내는 환각 방지)
        if intent == "chat":
            intent = "rag"

    # 카테고리 최종 계산 (intent == rag일 때만). rule_categories는 위 분기에서 이미
    # 채워졌다(키워드 매칭 경로는 값 있음, LLM 경로는 미매칭이라 빈 리스트).
    # ("none"/contact 는 문서가 없어 필터 안 함 → 전체 검색 후 가드레일이 문의처 안내)
    if intent == "rag":
        expanded_categories = expand_categories(query, rule_categories)
        categories = [c for c in expanded_categories if c != "contact"] or None
        if not categories and llm_category not in ("none", "contact"):
            categories = [llm_category]

    # 졸업계산 도구도 학번에 따라 답이 갈린다(졸업 이수학점 기준이 학번별로 다름).
    # 학번을 알면 도구에 넘겨 해당 학번 기준으로 계산하게 한다.
    if intent == "tool" and tool_name == "calc_graduation_progress" and admission_year is not None:
        tool_args = {**(tool_args or {}), "학번": admission_year}

    # ── 학번 되묻기 게이트 ──
    # 학번에 따라 답이 갈리는 질문인데 학번을 아직 모르면 한 번만 되묻는다
    # (year_prompted=True 이후로는 재질문 없이 현행 기준으로 답한다).
    # 대상: ①년도-민감 rag 질문(졸업요건·교육과정) ②졸업계산 중 '전공필수/전공선택/
    # 공통' 등 학번별로 기준이 다른 세부 이수구분 계산.
    # 제외: 개설과목 추천·수강신청 일정, 그리고 '전공(통합)' 계산 — 전공(필수+선택)은
    # 전 학번 72로 동일하므로 학번을 물을 필요가 없다.
    calc_needs_year = tool_name == "calc_graduation_progress" and any(
        k in (tool_args or {}) for k in ("전공필수", "전공선택", "공통필수", "공통선택")
    )
    needs_admission_year = (intent == "rag" and is_year_sensitive_question(query)) or (
        intent == "tool" and calc_needs_year
    )
    if needs_admission_year and admission_year is None and not year_prompted:
        logger.info(
            json.dumps(
                {
                    "stage": "router",
                    "session_id": state.get("session_id"),
                    "question": query,
                    "intent": "ask_year",
                    "reason": "year_sensitive_without_admission_year",
                },
                ensure_ascii=False,
            )
        )
        return {
            "intent": "ask_year",
            "query": query,
            "admission_year": None,
            "year_prompted": True,
            "applied_curriculum_year": None,
            "category_l1": categories,
            "tool_name": None,
            "tool_args": None,
            "retrieved_docs": [],
            "guardrail": False,
            "contact": None,
            "tool_result": None,
            "pending_action": {"type": "await_admission_year", "orig_query": query},
        }

    logger.info(
        json.dumps(
            {
                "stage": "router",
                "session_id": state.get("session_id"),
                "question": query,
                "llm_called": llm_called,
                "llm_intent": llm_intent,
                "intent": intent,
                "admission_year": admission_year,
                "tool_forced_by_rule": tool_forced_by_rule,
                "rule_categories": rule_categories,
                "expanded_categories": expanded_categories,
                "llm_category": llm_category,
                "final_categories": categories,
            },
            ensure_ascii=False,
        )
    )

    return {
        "intent": intent,
        "query": query,
        "admission_year": admission_year,
        "year_prompted": year_prompted,
        "applied_curriculum_year": None,
        "category_l1": categories,
        "tool_name": tool_name,
        "tool_args": tool_args,
        # 체크포인터로 턴 간 상태가 영속되므로, 이번 턴에 rag/tool을 안 타면
        # 지난 턴의 검색 결과·가드레일·도구 결과가 그대로 남아있을 수 있다.
        # 매 턴 router에서 명시적으로 리셋해 이전 턴 상태가 새지 않게 한다.
        "retrieved_docs": [],
        "guardrail": False,
        "contact": None,
        "tool_result": None,
        # 이 경로(early return이 아닌 일반 라우팅)에 도달했다는 건 pending_action이
        # 애초에 없었거나, 위에서 새 질문으로 판단해 버렸다는 뜻 → 명시적으로 비운다.
        "pending_action": pending,
    }


async def rag_node(state: AgentState) -> dict:
    """질문 관련 문서 검색. 자료가 없거나 관련도가 낮으면 가드레일로 전환."""
    # 학번 되묻기 답변 턴이면 query가 '원래 질문'으로 복원돼 있다.
    user_input = state.get("query") or state["messages"][-1].content
    categories = state.get("category_l1")

    # 학번-aware: 학번을 보유 교육과정 년도로 매핑해 검색 년도 필터로 넘긴다.
    # (매핑 결과 applied_year는 응답 그라운딩에서 '어느 년도 기준'인지 밝히는 데 쓴다.)
    # 년도 필터는 '학번에 따라 답이 갈리는 질문'(졸업요건·교육과정)에만 적용한다.
    # 수강신청 일정·개설과목 등 현행이 맞는 질문까지 필터하면, 과거 학번 세션에서
    # 현행(2026) 문서가 필터로 제외돼 오히려 답이 나빠진다.
    admission_year = state.get("admission_year")
    applied_year = None
    # 년도-민감 질문이거나, 사용자가 이번 메시지에서 학번을 직접 밝힌 경우
    # (예: "아 나 21학번이야 다시 알려줘")에 검색을 그 학번으로 스코프한다.
    # 후자를 놓치면 학번만 갱신되고 검색은 직전/현행 년도에 머물러, 21·22학번에게
    # 23~26년 값(전필35/전선37)을 답하는 멀티턴 오답이 난다.
    year_scoped = (
        is_year_sensitive_question(user_input) or extract_admission_year(user_input) is not None
    )
    if admission_year is not None and year_scoped:
        try:
            years = await get_rag_repository().available_academic_years()
        except Exception:
            years = set()
        applied_year = applicable_curriculum_year(admission_year, years)
    # 카테고리가 여러 개 걸린 복합 질문(예: "2학기 수강신청" -> academic_calendar
    # + course)은 k=5로 좁히면 한 카테고리가 상위를 독식해 다른 카테고리 문서가
    # 아예 잘려나갈 수 있다. 여유를 더 준다.
    k = 8 if categories and len(categories) > 1 else 5
    try:
        docs = await get_rag_repository().search_similar(
            user_input,
            k=k,
            category_l1=categories,
            academic_year=applied_year,
            session_id=state.get("session_id"),
        )
    except Exception:
        docs = []

    # Langfuse trace에 검색 점수/출처/가드레일 판단 근거를 span으로 남긴다(비활성 시 no-op).
    record_rag_observation(question=user_input, categories=categories, k=k, docs=docs)

    top_score = docs[0]["score"] if docs else 0.0
    # 연락처/문의처 질문은 답(부서 전화번호 등)이 RAG 문서가 아니라 contacts.json에
    # 있다. 검색이 우연히 무관한 문서를 임계값 이상으로 올리면 거기서 엉뚱한 번호를
    # 긁어온다(예: 외국어졸업인증 문서의 국제어학원 번호를 '학과사무실/교무처'로
    # 오기). 그래서 연락처 질문은 점수와 무관하게 항상 문의처(가드레일) 경로로 답해
    # contacts.json의 정확한 부서·번호를 쓰게 한다.
    # 순수 연락처 질문(contact 카테고리만 매칭)일 때만 강제한다. "졸업요건 문의"처럼
    # 다른 주제 + '문의'가 섞인 질문은 정상 RAG로 내용을 답하게 둔다.
    is_contact_question = classify_categories(user_input) == ["contact"]
    # 범위밖 주제(자료 미보유)는 점수와 무관하게 가드레일. 스칼라 임계값으로는 정상질문과
    # 점수대가 겹쳐 못 거르는 under-fire(재수강·계절학기·전과·셔틀 등)를 여기서 차단한다.
    out_of_scope = _is_out_of_scope(user_input)
    guardrail = (
        is_contact_question or out_of_scope or not docs or top_score < config.GUARDRAIL_MIN_SCORE
    )
    contact = match_contact(user_input) if guardrail else None

    logger.info(
        json.dumps(
            {
                "stage": "guardrail",
                "session_id": state.get("session_id"),
                "question": user_input,
                "top_score": top_score,
                "guardrail": guardrail,
                "is_contact_question": is_contact_question,
                "out_of_scope": out_of_scope,
                "contact_matched": contact is not None,
                "admission_year": admission_year,
                "applied_curriculum_year": applied_year,
            },
            ensure_ascii=False,
        )
    )

    if guardrail:
        # 자료로 답할 수 없음 → 질문 주제에 맞는 문의처를 찾아 안내
        return {
            "retrieved_docs": docs,
            "guardrail": True,
            "contact": contact,
            "is_contact_question": is_contact_question,
            "applied_curriculum_year": applied_year,
        }
    return {
        "retrieved_docs": docs,
        "guardrail": False,
        "contact": None,
        "is_contact_question": False,
        "applied_curriculum_year": applied_year,
    }


async def tool_node(state: AgentState) -> dict:
    """Router가 고른 도구 실행."""
    result = await tool_executor.execute(
        tool_name=state["tool_name"],
        tool_args=state["tool_args"] or {},
        session_id=state["session_id"],
    )
    return {"tool_result": result}


# ── 학번 되묻기 흐름 ────────────────────────────────────────────────────
# 졸업요건·전공교육과정은 입학년도(학번)에 따라 갈리므로, 학번을 모르는 채 그런
# 질문을 받으면 한 번 되묻는다. reminder 노드처럼 결정적 템플릿으로 질문만 던지고
# END로 간다(응답 LLM을 거치지 않음). router가 pending_action(await_admission_year)을
# 이미 세팅해 뒀고, 다음 턴 router가 사용자의 학번 답을 받아 원 질문을 이어 답한다.
_ASK_ADMISSION_YEAR_MSG = (
    "졸업요건과 전공교육과정은 입학년도(학번)에 따라 달라져요. "
    "정확히 안내해 드릴 수 있게 몇 학번이신지 알려주시겠어요? (예: 23학번) 🎓"
)


async def ask_admission_year_node(state: AgentState) -> dict:
    """학번을 한 번 되묻는다(결정적 템플릿)."""
    return {"messages": [AIMessage(content=_ASK_ADMISSION_YEAR_MSG)]}


# ── 학과 스코프 밖 안내 흐름 ────────────────────────────────────────────
# 인공지능학과(구 AI·소프트웨어학부) 외 학과 질문 → 결정적 템플릿으로 "전용 챗봇"임을
# 안내하고 END. RAG/도구/응답 LLM을 거치지 않아 다른 학과 자료로 답하는 환각이 없다.
_OUT_OF_SCOPE_MSG = (
    "앗, 저는 가천대학교 **인공지능학과(구 AI·소프트웨어학부)** 학생을 돕는 학사 안내 "
    "AI라서, 다른 학과의 학사 정보는 안내해 드리기 어려워요. 😥\n\n"
    "인공지능학과(구 AI·소프트웨어학부) 관련해서 궁금한 점이 있으면 무엇이든 물어봐 "
    "주세요! 다른 학과의 졸업요건·교육과정은 해당 학과사무실이나 가천대 학사안내"
    "(https://www.gachon.ac.kr) 에서 확인하시는 게 정확해요."
)


async def out_of_scope_node(state: AgentState) -> dict:
    """스코프 밖 학과 질문에 '인공지능학과 전용'임을 안내한다(결정적 템플릿)."""
    return {"messages": [AIMessage(content=_OUT_OF_SCOPE_MSG)]}


# ── 이메일 리마인드 멀티턴 확인 흐름 ─────────────────────────────────────
# 외부 상태를 바꾸는 이메일 발송은 "물어보고 → 확인받고 → 발송"으로만 실행한다
# (README §6.2). 진행 단계는 pending_action(체크포인터로 턴 간 영속)에 담고,
#   {"type":"reminder", "stage":"awaiting_email"|"awaiting_confirm",
#    "content":str, "remind_at":ISO, "remind_label":str, "email":str|None}
# 안내/확인 문구는 이 노드가 '결정적 템플릿'으로 직접 만든다: 이메일 주소를 응답
# LLM에 넘기지 않아 ADR-007을 지키고(주소는 여기서만 다룸), 주소를 정확히 되비추며,
# 턴마다 동일하게 동작한다. 그래서 response 노드를 타지 않고 바로 END로 간다.

# 확인 응답(예/아니오) 규칙 분류용. 애매하면 재확인하므로 오분류 위험은 낮다.
_CONFIRM_YES = (
    "응",
    "네",
    "넵",
    "예",
    "그래",
    "좋아",
    "좋습니다",
    "보내",
    "부탁",
    "ㅇㅇ",
    "오케",
    "ok",
    "okay",
    "yes",
    "맞아",
    "해줘",
    "해 줘",
    "진행",
    "등록",
)
_CONFIRM_NO = (
    "아니",
    "아뇨",
    "취소",
    "됐어",
    "됐습니다",
    "됐네",
    "싫",
    "no",
    "하지마",
    "하지 마",
    "지마",
    "지 마",
    "그만",
    "말아",
    "말래",
    "말자",
    "안 보",
)


def _extract_email(text: str) -> str | None:
    m = re.search(_EMAIL_PATTERN, text)
    return m.group(0) if m else None


def _classify_confirm(text: str) -> Literal["yes", "no", "unclear"]:
    low = text.strip().lower()
    # 부정을 먼저 본다("아니 보내지마"처럼 긍정어가 섞여도 취소로 처리)
    if any(p in low for p in _CONFIRM_NO):
        return "no"
    if any(p in low for p in _CONFIRM_YES):
        return "yes"
    return "unclear"


def _timing_phrase(pending: dict) -> str:
    label = pending.get("remind_label") or ""
    return "지금 바로" if label == "지금 바로" else f"{label}에"


def _ask_email_msg(pending: dict) -> str:
    return (
        f"네! 요청하신 내용을 {_timing_phrase(pending)} 리마인드 메일로 보내드릴 수 있어요. 📮\n"
        "어느 이메일 주소로 받으실지 알려주시겠어요? (예: hong@gachon.ac.kr)"
    )


def _ask_confirm_msg(pending: dict) -> str:
    return (
        "보내기 전에 확인해주세요! 아래 내용으로 리마인드 메일을 보낼까요?\n"
        f"- 받는 사람: {pending['email']}\n"
        f"- 발송 시점: {pending.get('remind_label')}\n"
        f"- 내용: {pending['content']}\n\n"
        "'네'라고 답하시면 예약할게요. 취소하려면 '아니오'라고 답해주세요."
    )


def _reask_confirm_msg(pending: dict) -> str:
    return (
        "'네'(보내기) 또는 '아니오'(취소)로 답해주세요. "
        f"{pending['email']}로 {_timing_phrase(pending)} 보낼 예정이에요."
    )


_REMINDER_REASK_EMAIL = (
    "앗, 이메일 주소를 못 찾았어요. 예: hong@gachon.ac.kr 처럼 받으실 주소를 알려주시겠어요?"
)
_REMINDER_CANCELED = "알겠어요, 리마인드는 취소했어요. 필요하면 언제든 다시 말씀해 주세요! 🙂"
_REMINDER_REGISTER_FAILED = "죄송해요, 예약 등록 중 문제가 생겼어요. 잠시 후 다시 시도해 주세요."
_REMINDER_NO_SCHEDULE = (
    "앗, 그 일정은 제 자료에서 확인이 어려워 리마인드 메일로 보내드리기 어려워요. 😥\n"
    "공식 학사공지에서 최종 확인해 주세요."
)

# 리마인드 요청 문장에서 '일정 주제'만 남긴다. 이메일 주소와 "리마인드/메일/보내줘"
# 같은 보일러플레이트는 임베딩 검색을 흐리므로 토큰 단위로 제거한다(부분 문자열이
# 아니라 독립 토큰만 지워 "일정을" 같은 조사 붙은 명사는 보존).
_REMINDER_STOPWORDS = {
    "리마인드",
    "리마인더",
    "메일",
    "이메일",
    "메일로",
    "이메일로",
    "알림",
    "알림으로",
    "보내줘",
    "보내",
    "보내주세요",
    "보내줄래",
    "발송",
    "발송해줘",
    "알려줘",
    "알려",
    "알려주세요",
    "예약",
    "예약해줘",
    "해줘",
    "해",
    "줘",
    "좀",
    "로",
    "으로",
    "주소로",
}


def _reminder_topic_query(text: str) -> str:
    """리마인드 요청에서 RAG 검색에 쓸 주제 질의를 뽑는다."""
    no_email = re.sub(_EMAIL_PATTERN, " ", text)
    tokens = [w for w in re.split(r"\s+", no_email) if w and w not in _REMINDER_STOPWORDS]
    topic = " ".join(tokens).strip()
    # 주제어가 다 지워졌으면(예: "리마인드 해줘") 이메일만 제거한 원문으로 폴백
    return topic if len(topic) >= 2 else re.sub(r"\s+", " ", no_email).strip()


async def _fetch_schedule_for_reminder(topic_query: str) -> str | None:
    """리마인드 주제로 RAG 검색 후 근거 기반 일정 답변을 생성해 반환한다.
    관련 자료가 없거나(가드레일) 범위 밖 주제면 None → 리마인드 내용 구성 불가."""
    categories = classify_categories(topic_query)
    try:
        docs = await get_rag_repository().search_similar(topic_query, k=5, category_l1=categories)
    except Exception:
        docs = []
    top_score = docs[0]["score"] if docs else 0.0
    if not docs or top_score < config.GUARDRAIL_MIN_SCORE or _is_out_of_scope(topic_query):
        return None
    context = "\n\n".join(f"[자료{i + 1}] {d['content']}" for i, d in enumerate(docs))
    system_prompt = f"{RESPONSE_PROMPT}\n\n{RAG_GROUNDING.format(context=context)}"
    try:
        answer = await get_llm().ainvoke(
            [SystemMessage(content=system_prompt), HumanMessage(content=topic_query)]
        )
    except Exception:
        return None
    content = (answer.content or "").strip()
    return content or None


def _reminder_reply(text: str, pending: dict | None) -> dict:
    """리마인드 노드의 반환 형태: 사용자에게 보낼 메시지 + 진행 상태(pending) 갱신."""
    return {"messages": [AIMessage(content=text)], "pending_action": pending}


def _apply_remind_update(pending: dict, user_input: str) -> dict | None:
    """진행 중 pending에 사용자가 말한 시간/날짜 수정을 반영한 새 pending을 반환.
    수정 표현이 없거나 값이 그대로면 None(변화 없음)."""
    updated = apply_time_update(pending["remind_at"], user_input, now=now_kst())
    if updated is None or updated.isoformat() == pending.get("remind_at"):
        return None
    return {
        **pending,
        "remind_at": updated.isoformat(),
        "remind_label": updated.strftime("%Y-%m-%d %H:%M"),
    }


async def _register_reminder(pending: dict, session_id: str | None) -> dict:
    """확인 완료 → reminder_requests에 예약 등록(실제 발송은 스케줄러가 처리)."""
    remind_at = datetime.fromisoformat(pending["remind_at"])
    result = await tool_executor.execute(
        tool_name="send_reminder_email",
        tool_args={
            "이메일": pending["email"],
            "내용": pending["content"],
            "발송예정시각": remind_at,
        },
        session_id=session_id,
    )
    if not result.get("success"):
        return _reminder_reply(_REMINDER_REGISTER_FAILED, None)

    if pending.get("remind_label") == "지금 바로":
        msg = "✅ 리마인드 예약을 등록했어요! 곧 메일이 도착할 거예요."
    else:
        msg = f"✅ 리마인드 예약 완료! {pending.get('remind_label')}에 메일로 알려드릴게요."
    return _reminder_reply(msg, None)


async def reminder_node(state: AgentState) -> dict:
    """이메일 리마인드 멀티턴 확인 흐름(물어보고 → 확인받고 → 발송)."""
    user_input = state["messages"][-1].content
    pending = state.get("pending_action")
    session_id = state.get("session_id")

    # ── 진행 중인 대화 이어받기 ─────────────────────────────
    if pending and pending.get("type") == "reminder":
        stage = pending.get("stage")

        if stage == "awaiting_email":
            if any(w in user_input for w in _CONFIRM_NO):
                return _reminder_reply(_REMINDER_CANCELED, None)
            # 이메일을 받기 전에 사용자가 발송 시각만 바꾸는 경우("9시 30분으로 해줘")
            # 그 수정을 반영한다(기존 날짜는 보존 — 날짜를 다시 되묻지 않는다).
            updated = _apply_remind_update(pending, user_input)
            if updated is not None:
                pending = updated
            email = _extract_email(user_input)
            if not email:
                # 시각을 방금 바꿨으면 그 새 시각을 반영해 이메일을 다시 청한다.
                # (아무 정보도 없으면 '주소를 못 찾았어요'로 안내)
                msg = _ask_email_msg(pending) if updated is not None else _REMINDER_REASK_EMAIL
                return _reminder_reply(msg, pending)
            pending = {**pending, "email": email, "stage": "awaiting_confirm"}
            return _reminder_reply(_ask_confirm_msg(pending), pending)

        if stage == "awaiting_confirm":
            # 확인 단계에서 시각/날짜를 바꾸면("9시 30분으로 해줘") 옛 시각으로
            # 등록되지 않도록 수정을 먼저 반영하고 새 내용으로 다시 확인받는다.
            # ("해줘"가 confirm-yes로 오인돼 옛 시각으로 발송되는 사고 방지)
            updated = _apply_remind_update(pending, user_input)
            if updated is not None:
                return _reminder_reply(_ask_confirm_msg(updated), updated)
            decision = _classify_confirm(user_input)
            if decision == "no":
                return _reminder_reply(_REMINDER_CANCELED, None)
            if decision == "unclear":
                return _reminder_reply(_reask_confirm_msg(pending), pending)
            return await _register_reminder(pending, session_id)

    # ── 새 리마인드 요청 시작 ───────────────────────────────
    # 메일 본문은 요청 문장이 아니라 RAG로 찾은 실제 일정(LLM 정리 답변)을 담는다.
    # 자료에서 일정을 찾지 못하면 예약하지 않고 안내만 한다(엉뚱한 요청 문장 발송 방지).
    content = await _fetch_schedule_for_reminder(_reminder_topic_query(user_input))
    if content is None:
        return _reminder_reply(_REMINDER_NO_SCHEDULE, None)

    now = now_kst()
    remind_at = parse_remind_at(user_input, now=now)
    # parse_remind_at은 날짜 표현이 없으면 now를 그대로 반환 → '즉시 발송'으로 본다.
    immediate = abs((remind_at - now).total_seconds()) < 60
    label = "지금 바로" if immediate else remind_at.strftime("%Y-%m-%d %H:%M")

    base = {
        "type": "reminder",
        "content": content,
        "remind_at": remind_at.isoformat(),
        "remind_label": label,
        "email": _extract_email(user_input),
    }
    if base["email"]:
        pending = {**base, "stage": "awaiting_confirm"}
        return _reminder_reply(_ask_confirm_msg(pending), pending)
    pending = {**base, "stage": "awaiting_email"}
    return _reminder_reply(_ask_email_msg(pending), pending)


def _office_contact_line() -> str:
    """도구 응답의 '학과사무실 확인' 안내에 쓸 실제 학과사무실 연락처(contacts.json).
    봇이 번호를 지어내지 않도록 근거로 제공한다. 매칭 실패 시 빈 문자열."""
    c = match_contact("학과사무실 전화번호")
    phone = contact_phone(c)
    if c.get("matched") and phone:
        return f"{c['부서']} ☎ {phone}"
    return ""


def _year_note(state: AgentState) -> str:
    """학번-aware 응답에 붙일 '어느 년도 교육과정 기준으로 답했는지' 안내(투명성).

    응답 LLM이 근거의 적용 년도를 답변에 밝히도록 유도한다. 요청 학번 데이터가 없어
    다른 년도로 매핑됐으면 그 사실(정확한 값은 학과사무실 확인 권장)까지 알려준다.
    """
    admission_year = state.get("admission_year")
    applied_year = state.get("applied_curriculum_year")
    if not admission_year or not applied_year:
        return ""
    if applied_year == admission_year:
        return (
            f"[학번 안내] 사용자는 {admission_year}학번입니다. {applied_year}학년도 교육과정/"
            f"졸업요건 기준으로 답하고, 답변에 '{applied_year}학번 기준'임을 밝히세요."
        )
    return (
        f"[학번 안내] 사용자는 {admission_year}학번이나 해당 학번 전용 자료가 아직 없어 "
        f"{applied_year}학년도 교육과정 기준으로 안내합니다. 이 점을 답변에 밝히고, "
        f"정확한 값은 학과사무실 확인을 권하세요."
    )


def build_response_inputs(state: AgentState) -> tuple[str, str]:
    """최종 응답 생성을 위한 system_prompt, user_input 생성."""
    # 학번 되묻기 답변 턴이면 query가 '원래 질문'으로 복원돼 있다.
    user_input = state.get("query") or state["messages"][-1].content
    intent = state["intent"]
    # 공식 링크 안내 트리거: 라우터가 매긴 category_l1 후보 또는 질문 텍스트의
    # 키워드로 관련 공식 페이지 topic을 찾아, 자료에 답이 없을 때 링크 힌트를
    # 그라운딩에 붙인다. "예비수강신청 일자"처럼 category가 course여도 실제로는
    # 일정 질문인 경우를 놓치지 않으려 텍스트도 본다. (데이터·규칙은
    # prompts.OFFICIAL_LINKS / detect_link_topics 참고)
    link_hint = build_link_hint(detect_link_topics(user_input or "", state.get("category_l1")))

    if intent == "rag" and state.get("guardrail"):
        contact = state.get("contact")
        contact_text = format_contact(contact)
        # 순수 연락처 질문이고 부서가 매칭됐으면(번호를 아는 경우) "자료에서 확인
        # 어렵다"는 얼버무림 없이 자신 있게 바로 안내한다. 그 외(주제는 있으나 자료에
        # 답이 없는 경우)는 기존 가드레일 문구로 솔직히 밝히고 문의처를 안내한다.
        if state.get("is_contact_question") and contact and contact.get("matched"):
            grounding = CONTACT_GROUNDING.format(contact=contact_text)
        else:
            grounding = GUARDRAIL_GROUNDING.format(contact=contact_text)
        if link_hint:
            grounding = f"{link_hint}\n{grounding}"
        system_prompt = f"{RESPONSE_PROMPT}\n\n{grounding}"

    elif intent == "rag":
        context = (
            "\n\n".join(
                f"[자료{i + 1}] {d['content']}" for i, d in enumerate(state["retrieved_docs"])
            )
            or "(관련 자료 없음)"
        )
        grounding = RAG_GROUNDING.format(context=context)
        year_note = _year_note(state)
        if year_note:
            grounding = f"{year_note}\n{grounding}"
        if link_hint:
            grounding = f"{link_hint}\n{grounding}"
        system_prompt = f"{RESPONSE_PROMPT}\n\n{grounding}"

    elif intent == "tool":
        tool_result = json.dumps(state["tool_result"], ensure_ascii=False)
        grounding = TOOL_GROUNDING.format(tool_result=tool_result)
        # 과목 추천은 Solar가 목록을 무시하고 지어내는 환각이 잦아 전용 규칙을 덧붙인다.
        if state.get("tool_name") == "recommend_courses":
            grounding = f"{grounding}\n{RECOMMEND_COURSES_RULES}"
        # 도구 응답은 "학과사무실 확인"을 권하는데, 봇이 번호를 지어내지 않도록
        # contacts.json의 실제 학과사무실 연락처를 근거로 함께 제공한다.
        office = _office_contact_line()
        if office:
            grounding = (
                f"{grounding}\n\n[학과사무실 연락처] 최종 확인을 권할 때 이 번호만 그대로 "
                f"안내하고, 다른 번호는 지어내지 마라: {office}"
            )
        system_prompt = f"{RESPONSE_PROMPT}\n\n{grounding}"

    else:
        system_prompt = RESPONSE_PROMPT

    return system_prompt, user_input


async def response_node(state: AgentState) -> dict:
    """intent별 그라운딩을 붙여 최종 응답 생성."""
    llm = get_llm()

    system_prompt, user_input = build_response_inputs(state)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_input),
    ]

    answer = await llm.ainvoke(messages)
    return {"messages": [AIMessage(content=answer.content)]}

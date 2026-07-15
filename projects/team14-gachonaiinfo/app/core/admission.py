"""학번(입학년도) 인식 순수 로직.

한국 대학은 '입학년도(학번)' 기준으로 졸업 이수학점 기준표(별표)와 전공교육과정표가
갈린다. 봇이 학번-aware하게 답하려면 (1) 질문에서 학번을 뽑고, (2) 학번이 갈리는
질문인지 판별하고, (3) 학번을 우리가 가진 교육과정 년도로 매핑해야 한다.

이 모듈은 embeddings/graph/DB 등 무거운 의존성을 import하지 않는 순수 함수만 둔다
(CI에서 API 키 없이 테스트되도록). DB에서 뽑은 '보유 년도 집합'은 인자로 받는다.
"""

import re

# 학번 2자리는 20xx로 편다(21 → 2021). 4자리는 그대로 본다.
_MIN_YEAR = 2000
_MAX_YEAR = 2099


def _to_year(n: int) -> int | None:
    """숫자를 학년도로 정규화. 2자리→20xx, 4자리→그대로. 범위 밖이면 None."""
    if _MIN_YEAR <= n <= _MAX_YEAR:
        return n
    if 0 <= n <= 99:
        return 2000 + n
    return None


# 명시적으로 '학번'이라 말한 경우만 잡는다(엄격). "3학년"·"120학점"·"2023년"은
# 학번이 아니므로 배제하려고 반드시 '학번' 토큰을 요구한다.
_ADMISSION_RE = re.compile(r"(\d{2,4})\s*학번")


def extract_admission_year(text: str) -> int | None:
    """일반 질문 텍스트에서 학번을 추출한다(엄격: '학번' 토큰 필수).

    "23학번 졸업요건" → 2023, "2021학번인데" → 2021.
    "3학년 1학기", "졸업 120학점", "2023년" 등은 매칭되지 않는다.
    """
    m = _ADMISSION_RE.search(text or "")
    if not m:
        return None
    return _to_year(int(m.group(1)))


# "몇 학번이세요?"에 대한 답은 "23", "2023", "23학번이요", "21학번" 등 형태가 다양하다.
# 되묻기 답변 처리에서만 쓰는 관대한 파서(맨 앞 년도형 숫자를 학번으로 본다).
_BARE_NUMBER_RE = re.compile(r"\b(\d{2,4})\b")


def parse_year_reply(text: str) -> int | None:
    """'몇 학번?' 되묻기에 대한 답에서 학번을 추출한다(관대).

    "23학번"·"23"·"2023"·"21학번이요" 모두 인식. "몰라요"·"글쎄"는 None.
    '학번'이 붙은 숫자를 우선하고, 없으면 맨 앞 2~4자리 숫자를 학번으로 본다.
    """
    year = extract_admission_year(text)
    if year is not None:
        return year
    m = _BARE_NUMBER_RE.search(text or "")
    if not m:
        return None
    return _to_year(int(m.group(1)))


# 학번에 따라 답이 달라지는 질문(졸업 이수학점 기준·전공교육과정표 구성)에서만
# 학번을 따진다. 개설과목 추천·수강신청 일정 등 '현행이 맞는' 질문은 제외한다.
# (멘토링/프로젝트 메모: 학번별로 달라지는 것 = ①졸업 이수학점 기준 ②전공교육과정표.
#  개설과목 추천은 현행 2026이 오히려 맞음.)
_YEAR_SENSITIVE_KEYWORDS = (
    # 졸업 이수학점 기준
    "졸업요건",
    "졸업 요건",
    "졸업학점",
    "졸업 학점",
    "졸업이수",
    "졸업 이수",
    "졸업조건",
    "졸업 조건",
    "이수학점",
    "이수 학점",
    "이수구분",
    "필수학점",
    "필요학점",
    # 전공교육과정표(구성). "트랙"은 아래에서 조건부 처리(현행 트랙명 명시 시 제외).
    "교육과정",
    "커리큘럼",
    "전공교육과정",
)

# 현행(2026) 트랙명 토큰. 트랙 구성은 학번별로 다르지만, 이 현행 트랙명을 콕 집어
# 물으면(예: "AIoT 트랙 과목") 현행 기준이 명확하므로 학번을 되묻지 않는다.
_CURRENT_TRACK_TOKENS = (
    "aiot",
    "vision",
    "language",
    "비전",
    "자연어",
    "intelligent",
    "인텔리전트",
    "부트캠프",
    "bootcamp",
)


def _mentions_current_track(text: str) -> bool:
    low = text.lower()
    return any(tok in low for tok in _CURRENT_TRACK_TOKENS)


def is_year_sensitive_question(text: str) -> bool:
    """학번에 따라 답이 달라지는 질문인지(졸업 이수학점 기준·전공교육과정표)."""
    t = text or ""
    if any(kw in t for kw in _YEAR_SENSITIVE_KEYWORDS):
        return True
    # "트랙"은 학번별 구성이 달라 원칙적으로 년도-민감이나, 현행 트랙명(AIoT 등)을
    # 명시하면 현행 기준이 분명하므로 되묻지 않는다.
    if "트랙" in t and not _mentions_current_track(t):
        return True
    # "졸업 N학점/이수/요건..." 등 졸업요건성 질문만 년도-민감. bare "몇 "은 제외한다
    # (졸업작품 '몇 학년', 사회봉사 '몇 시간 해야 졸업' 같은 비-요건 질문 오탐 방지).
    if "졸업" in t and any(w in t for w in ("학점", "이수", "요건", "필요", "조건")):
        return True
    return False


def applicable_curriculum_year(admission_year: int, available_years) -> int | None:
    """입학년도를 '우리가 보유한 교육과정 년도'로 매핑한다.

    - 정확히 해당 학번 데이터가 있으면 그것을 쓴다(별표는 학번별로 존재).
    - 보유 최신보다 신입(예: 27학번인데 최신이 2026)이면 최신을 적용.
    - 보유 최소보다 과거면(예: 19학번인데 최소가 2021) 최소를 적용(최선).
    - 중간에 빈 년도면 '이하 중 가장 최근'(교육과정은 개정 전까지 유지)을 적용.
    - 보유 년도가 하나도 없으면 None(→ 정확히 답할 수 없음, 문의처 안내).
    """
    years = sorted({int(y) for y in available_years if y is not None})
    if not years:
        return None
    if admission_year in years:
        return admission_year
    if admission_year > years[-1]:
        return years[-1]
    if admission_year < years[0]:
        return years[0]
    lower = [y for y in years if y <= admission_year]
    return lower[-1] if lower else years[0]

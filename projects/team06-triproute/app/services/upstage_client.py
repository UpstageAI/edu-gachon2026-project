# app/services/upstage_client.py

import json
import os
import re
from typing import Any, Dict, Iterator, List

# Langfuse가 openai 클라이언트를 감싸서 제공하는 드롭인 대체품 — 이 클라이언트로 만든
# 모든 chat.completions.create()/embeddings.create() 호출이 프롬프트/응답/토큰
# 사용량/지연시간과 함께 자동으로 Langfuse에 기록된다(호출부 코드는 전혀 안 바뀜).
# LANGFUSE_PUBLIC_KEY/SECRET_KEY가 없으면 Langfuse 쪽이 알아서 tracing을 꺼서
# 조용히 동작하므로, 이 기능을 아직 설정 안 한 환경에서도 기존과 동일하게 동작한다.
from langfuse.openai import OpenAI

from app.core.config import settings
from app.core.prompts import (
    COORDINATOR_PARSE_SYSTEM_PROMPT,
    FINANCIAL_USEFEE_PARSE_SYSTEM_PROMPT,
    TRIP_SUMMARY_STREAM_SYSTEM_PROMPT,
)


BASE_URL = "https://api.upstage.ai/v1"

CHAT_MODEL = "solar-pro2"
EMBEDDING_QUERY_MODEL = "solar-embedding-1-large-query"
EMBEDDING_PASSAGE_MODEL = "solar-embedding-1-large-passage"


DEFAULT_PARSE_RESULT = {
    "city": "강릉",
    "season": "여름",
    "duration": "1박 2일",
    "travel_style": ["바다", "감성 카페", "먹거리"],
    "must_include_places": [],
    "schedule_intensity": "여유로운 일정",
    "prefer_local": False,
    "prefer_budget": False,
    "is_peak_season": True,
}

# "로컬만 아는 곳", "사람 안 몰리는 곳" 같은 hidden-gem 선호 표현 감지용 키워드.
# Solar 파싱이 실패해 Mock parser로 넘어갔을 때도 이 신호만큼은 규칙 기반으로 살리기 위해 씀.
PREFER_LOCAL_KEYWORDS = [
    "로컬",
    "현지인",
    "숨은",
    "한적한",
    "덜 붐비는",
    "붐비지 않는",
    "사람 안 몰리는",
    "사람 없는",
    "관광객 없는",
    "핫플 말고",
    "유명하지 않은",
]


def _detect_prefer_local(user_input: str) -> bool:
    return any(keyword in user_input for keyword in PREFER_LOCAL_KEYWORDS)


# 프롬프트 인젝션 의심 패턴(input 가드레일). 알려진 대표 문구만 걸러내는 근사치라
# 완벽하지 않지만(새로운 우회 표현엔 뚫릴 수 있음), 걸리면 아예 Solar 호출을 건너뛰고
# Mock parser로 처리해서 실제 LLM에 의심스러운 입력을 노출시키지 않는다(deny-by-default).
# COORDINATOR_PARSE_SYSTEM_PROMPT의 보안 규칙 문구가 이 탐지를 우회한 입력에 대한
# 2차 방어선 역할을 한다.
PROMPT_INJECTION_KEYWORDS = [
    "이전 지시 무시",
    "위 지시 무시",
    "지시를 무시해",
    "명령을 무시해",
    "규칙을 무시해",
    "시스템 프롬프트",
    "시스템 메시지를 알려",
    "너는 이제부터",
    "지금부터 너는",
    "역할을 무시하고",
    "탈옥",
    "ignore previous instructions",
    "ignore all previous instructions",
    "ignore the above",
    "disregard the above",
    "disregard previous instructions",
    "reveal your system prompt",
    "reveal your instructions",
    "print your prompt",
    "you are now",
    "developer mode",
    "jailbreak",
]


def _detect_prompt_injection(user_input: str) -> bool:
    lowered = user_input.lower()
    return any(keyword.lower() in lowered for keyword in PROMPT_INJECTION_KEYWORDS)


# 부정 문맥 감지용 키워드 (Mock parser fallback용). "돈 아끼지 않고", "여름은
# 피하고"처럼 키워드 바로 앞/뒤에 부정 표현이 붙어 뜻이 반전되는 흔한 패턴만
# 걸러내는 간단한 근사치이며, 완전한 부정 감지를 보장하지는 않는다.
NEGATION_MARKERS = ["안", "않", "말고", "아니", "피하"]


def _is_negated(user_input: str, keyword: str) -> bool:
    idx = user_input.find(keyword)

    if idx == -1:
        return False

    window_start = max(0, idx - 6)
    window_end = min(len(user_input), idx + len(keyword) + 8)
    window = user_input[window_start:window_end]

    return any(marker in window for marker in NEGATION_MARKERS)


# "가성비", "저렴하게" 같은 예산 중시 표현 감지용 키워드 (Mock parser fallback용, prefer_local과 동일한 이유)
PREFER_BUDGET_KEYWORDS = [
    "가성비",
    "저렴",
    "알뜰",
    "돈 아끼",
    "저가",
    "budget",
]


def _detect_prefer_budget(user_input: str) -> bool:
    return any(
        keyword in user_input and not _is_negated(user_input, keyword)
        for keyword in PREFER_BUDGET_KEYWORDS
    )


# 국내 숙박 성수기 시즌 감지용 키워드 (Mock parser fallback용). Solar는 날짜/시기를
# 문맥으로 판단하지만, Mock은 규칙 기반이라 정교한 날짜 계산 대신 키워드로만 근사한다.
PEAK_SEASON_KEYWORDS = [
    "여름",
    "성수기",
    "휴가철",
    "명절",
    "설날",
    "추석",
    "연휴",
    "크리스마스",
    "연말",
]


def _detect_peak_season(user_input: str) -> bool:
    return any(
        keyword in user_input and not _is_negated(user_input, keyword)
        for keyword in PEAK_SEASON_KEYWORDS
    )


# 실제 관광지 데이터(Supabase places 테이블)를 확보해둔 도시만 감지 대상으로 함
# (Step 4 RAG 수집 대상, docs/project_plan.md 참고). 목록에 없는 도시를 입력하면
# Mock parser는 기존처럼 DEFAULT_PARSE_RESULT["city"](강릉)로 대체한다.
KNOWN_CITIES = [
    "강릉", "속초", "춘천", "부산", "제주",
    "경주", "전주", "여수", "인천", "서울",
]


def _detect_city(user_input: str) -> str | None:
    for city in KNOWN_CITIES:
        if city in user_input:
            return city

    return None


# 슬롯 교체 후속 요청("2일차 점심만 바꿔줘") 감지용 시간대 키워드. route_planner의
# 실제 daily_schedule time_slot 값과 정확히 일치해야 한다(순서는 길게 겹치는 표현을
# 먼저 매칭하도록 "늦은 오후"를 "오후"보다 앞에 둠).
TIME_SLOT_KEYWORDS = ["늦은 오후", "오전", "점심", "오후", "저녁", "체크인"]


def _detect_target_day(user_input: str) -> int | None:
    """
    "2일차", "Day 2", "둘째 날" 처럼 특정 하루를 콕 짚은 표현에서 며칠차인지 뽑아낸다.
    Mock parser는 대화 맥락을 못 보므로, target_time_slot과 같이 있을 때만 의미가
    있어(parse_user_input_mock에서 둘 다 있을 때만 채움) 오탐(단순히 "3일"이 기간
    설명으로 쓰인 경우 등) 영향을 줄인다.
    """
    match = re.search(r"(\d+)\s*일\s*[차째]", user_input)
    if match:
        return int(match.group(1))

    match = re.search(r"[Dd]ay\s*(\d+)", user_input)
    if match:
        return int(match.group(1))

    return None


def _detect_target_time_slot(user_input: str) -> str | None:
    for slot in TIME_SLOT_KEYWORDS:
        if slot in user_input:
            return slot

    return None


VALID_TIME_SLOTS = set(TIME_SLOT_KEYWORDS)


def _normalize_target_day(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and int(value) > 0:
        return int(value)
    return None


def _normalize_target_time_slot(value: Any) -> str | None:
    if isinstance(value, str) and value in VALID_TIME_SLOTS:
        return value
    return None


def _normalize_movable_time_slot(value: Any) -> str | None:
    if isinstance(value, str) and value in MOVABLE_TIME_SLOTS:
        return value
    return None


# 장소 이동("2일차 관광지를 1일차로 옮겨줘") 요청에서는 체크인(숙박) 슬롯은 대상이 아니다.
MOVABLE_TIME_SLOTS = VALID_TIME_SLOTS - {"체크인"}

_DAY_MENTION_PATTERN = re.compile(r"(\d+)\s*일\s*[차째]|[Dd]ay\s*(\d+)")


def _find_day_mentions(user_input: str) -> list[tuple[int, int]]:
    """문장에 나오는 "N일차"/"Day N" 표현을 등장 순서대로 (day, 문자열 위치) 목록으로 뽑는다."""
    mentions: list[tuple[int, int]] = []
    for match in _DAY_MENTION_PATTERN.finditer(user_input):
        day_str = match.group(1) or match.group(2)
        mentions.append((int(day_str), match.start()))
    return mentions


def _time_slot_near(user_input: str, position: int, window: int = 12) -> str | None:
    """position 주변(앞 3자~뒤 window자)에서 이동 가능한 시간대 키워드를 찾는다."""
    snippet = user_input[max(0, position - 3) : position + window]
    for slot in MOVABLE_TIME_SLOTS:
        if slot in snippet:
            return slot
    return None


def _detect_move_request(
    user_input: str,
) -> tuple[int | None, str | None, int | None, str | None]:
    """
    "2일차 관광지를 1일차로 옮겨줘", "1일차 오후랑 2일차 오전 바꿔줘"처럼 이미 일정에
    있는 장소를 다른 날로 옮기거나 맞바꾸는 요청을 감지한다. 서로 다른 일차가 정확히
    2번 언급됐을 때만 (source_day, source_slot, destination_day, destination_slot)을
    채우고, 그 외(일차가 1개뿐이거나 3개 이상 언급됨)에는 전부 None을 반환해서 슬롯
    교체/기간 연장 등 다른 요청과 헷갈리지 않게 한다.
    """
    mentions = _find_day_mentions(user_input)
    distinct_days: list[tuple[int, int]] = []
    seen_days: set[int] = set()
    for day, position in mentions:
        if day not in seen_days:
            distinct_days.append((day, position))
            seen_days.add(day)

    if len(distinct_days) != 2:
        return None, None, None, None

    (source_day, source_pos), (destination_day, destination_pos) = distinct_days
    source_slot = _time_slot_near(user_input, source_pos)
    destination_slot = _time_slot_near(user_input, destination_pos)

    return source_day, source_slot, destination_day, destination_slot


def _normalize_daily_preferences(value: Any) -> list[dict[str, Any]]:
    """
    Solar가 뽑아낸 daily_preferences(일차별 취향/일정 강도/필수 방문지)를 검증하고
    정규화한다. day가 없거나 양의 정수가 아닌 항목, day가 중복된 항목(뒤에 나온 것
    우선)은 버려서 route_planner가 이상한 값으로 검색하지 않게 한다. Mock parser는
    이 구조를 규칙 기반으로 뽑아내기 사실상 불가능하므로 항상 빈 리스트를 반환해
    전체 공통 조건으로 자연스럽게 대체되게 한다(parse_user_input_mock 참고).
    """
    if not isinstance(value, list):
        return []

    by_day: dict[int, dict[str, Any]] = {}
    for item in value:
        if not isinstance(item, dict):
            continue

        day = _normalize_target_day(item.get("day"))
        if day is None:
            continue

        travel_style = item.get("travel_style")
        if isinstance(travel_style, str):
            travel_style = [travel_style]
        if not isinstance(travel_style, list) or not travel_style:
            travel_style = None

        schedule_intensity = item.get("schedule_intensity")
        if not isinstance(schedule_intensity, str) or not schedule_intensity:
            schedule_intensity = None

        must_include_places = item.get("must_include_places")
        if isinstance(must_include_places, str):
            must_include_places = [must_include_places]
        if isinstance(must_include_places, list):
            must_include_places = [
                str(p).strip() for p in must_include_places if str(p).strip()
            ] or None
        else:
            must_include_places = None

        if travel_style is None and schedule_intensity is None and must_include_places is None:
            continue

        by_day[day] = {
            "day": day,
            "travel_style": travel_style,
            "schedule_intensity": schedule_intensity,
            "must_include_places": must_include_places,
        }

    return list(by_day.values())


def _client() -> OpenAI:
    """
    Upstage OpenAI-compatible API 클라이언트를 생성합니다.
    """

    api_key = settings.UPSTAGE_API_KEY

    if not api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 설정되어 있지 않습니다.")

    return OpenAI(
        api_key=api_key,
        base_url=BASE_URL,
    )


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = CHAT_MODEL,
) -> str:
    """
    Solar Chat 모델로 일반 답변을 생성합니다.
    """

    response = _client().chat.completions.create(
        model=model,
        messages=messages,
    )

    return response.choices[0].message.content or ""


def _build_trip_summary_payload(
    condition_summary: Dict[str, Any],
    daily_schedule: List[Dict[str, Any]],
    cost_summary: Dict[str, Any],
) -> Dict[str, Any]:
    """
    완성된 일정 전체를 그대로 프롬프트에 넣으면 불필요하게 길고(주소/좌표/이미지 URL 등),
    금액도 다시 언급하지 말라고 프롬프트에서 지시하므로 총액 정도만 대략적인 규모 힌트로
    남긴다. 일차별로 장소명만 순서대로 뽑아서 가볍게 요약해 넘긴다.
    """
    days: Dict[str, List[str]] = {}
    for entry in daily_schedule:
        day = entry.get("day", "")
        days.setdefault(day, []).append(entry.get("place_name") or entry.get("place") or "")

    return {
        "city": condition_summary.get("city"),
        "season": condition_summary.get("season"),
        "duration": condition_summary.get("duration"),
        "travel_style": condition_summary.get("travel_style", []),
        "prefer_local": condition_summary.get("prefer_local", False),
        "prefer_budget": condition_summary.get("prefer_budget", False),
        "itinerary": [
            {"day": day, "places": places} for day, places in days.items()
        ],
        "total_cost_level": (
            "저예산" if cost_summary.get("total", 0) < 150000
            else "중간" if cost_summary.get("total", 0) < 350000
            else "고예산"
        ),
    }


def stream_trip_summary(
    condition_summary: Dict[str, Any],
    daily_schedule: List[Dict[str, Any]],
    cost_summary: Dict[str, Any],
) -> Iterator[str]:
    """
    완성된 여행 일정을 자연스러운 대화체 문단으로 요약하는 텍스트를 Solar에 stream=True로
    요청하고, 생성되는 대로 텍스트 조각(delta)을 하나씩 yield한다. 호출부(Gradio)가 이걸
    받아서 타이핑 효과로 화면에 이어붙인다.

    실패(네트워크 오류 등)하면 예외가 그대로 올라간다 — 호출부가 문단 하나 전체를 위한
    고정 문구로 대체할 수 있게, 여기서 대신 침묵하지 않는다.
    """
    model = os.getenv("UPSTAGE_MODEL", CHAT_MODEL)
    payload = _build_trip_summary_payload(condition_summary, daily_schedule, cost_summary)

    stream = _client().chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": TRIP_SUMMARY_STREAM_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        temperature=0.4,
        stream=True,
    )

    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


def embed_query(text: str) -> List[float]:
    """
    사용자 취향 문장 등 질의 텍스트를 임베딩합니다.
    """

    response = _client().embeddings.create(
        model=EMBEDDING_QUERY_MODEL,
        input=text,
    )

    return response.data[0].embedding


def embed_passages(texts: List[str]) -> List[List[float]]:
    """
    관광지 설명 등 저장 대상 문서를 임베딩합니다.
    """

    response = _client().embeddings.create(
        model=EMBEDDING_PASSAGE_MODEL,
        input=texts,
    )

    return [item.embedding for item in response.data]


def parse_user_input_mock(
    user_input: str,
    previous_condition_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Solar API 호출 실패 시 사용하는 Mock 입력 파서입니다.

    첫 턴(previous_condition_summary 없음)은 고정 데모 값(DEFAULT_PARSE_RESULT)을
    기본값으로 쓰지만, 후속 턴은 직전 condition_summary를 기본값으로 삼는다 — 안 그러면
    "2일차 위치 바꿔줘"처럼 도시를 다시 언급하지 않는 후속 요청에서 city/season/duration/
    travel_style이 전부 고정 데모 값(강릉 등)으로 리셋되는 문제가 있었다.
    city/prefer_local/prefer_budget/is_peak_season는 이번 user_input에서 실제로
    감지된 신호가 있을 때만 덮어쓴다.
    """

    base = {**DEFAULT_PARSE_RESULT, **(previous_condition_summary or {})}

    move_source_day, move_source_slot, move_destination_day, move_destination_slot = (
        _detect_move_request(user_input)
    )

    target_day = None
    target_time_slot = None
    if move_source_day is None:
        # 이동 요청(서로 다른 일차 2개)이 아닐 때만 슬롯 교체(일차 1개 + 시간대) 감지로 넘어간다
        # — 안 그러면 "2일차 관광지를 1일차로"에서 "2일차"가 슬롯 교체로도 잘못 잡힐 수 있다.
        target_day = _detect_target_day(user_input)
        target_time_slot = _detect_target_time_slot(user_input)
        # 둘 다 있을 때만 "특정 일차의 특정 시간대 교체" 신호로 본다 — 하나만 있으면
        # (예: "3일 여행"의 "3일"엔 시간대 언급이 없음) 기간 설명과 헷갈릴 위험이 크다.
        if target_day is None or target_time_slot is None:
            target_day = None
            target_time_slot = None

    return {
        **base,
        "city": _detect_city(user_input) or base.get("city") or DEFAULT_PARSE_RESULT["city"],
        "prefer_local": _detect_prefer_local(user_input) or bool(base.get("prefer_local", False)),
        "prefer_budget": _detect_prefer_budget(user_input) or bool(base.get("prefer_budget", False)),
        "is_peak_season": _detect_peak_season(user_input)
        or bool(base.get("is_peak_season", DEFAULT_PARSE_RESULT["is_peak_season"])),
        "target_day": target_day,
        "target_time_slot": target_time_slot,
        "move_source_day": move_source_day,
        "move_source_time_slot": move_source_slot,
        # 장소 이름만으로 원본을 지칭하는 건("안목해변을 3일차로 옮겨줘") 임의 어휘라
        # 규칙 기반으로 신뢰성 있게 못 뽑아낸다 — Solar 파싱 성공을 전제로 하는 필드다
        # (parse_user_input_mock 자체는 이 필드를 채우지 않는다).
        "move_source_place_name": None,
        # 날짜 지정 장소 추가("2일차에 OO 추가해줘")도 임의 어휘 추출이 필요해 Mock은
        # 지원하지 않는다(daily_preferences/move_source_place_name과 동일한 이유).
        "add_place_name": None,
        "add_place_day": None,
        "move_destination_day": move_destination_day,
        "move_destination_time_slot": move_destination_slot,
        # Mock parser는 규칙 기반이라 "일차별로 다른 취향" 같은 중첩 구조를 신뢰성 있게
        # 못 뽑아낸다 — 항상 빈 리스트를 반환해서 route_planner가 전체 공통 조건으로
        # 자연스럽게 대체하게 한다(daily_preferences가 있는 요청은 Solar 파싱 성공을 전제).
        "daily_preferences": [],
        "_parser": "mock",
    }


def _extract_json(text: str) -> dict[str, Any]:
    """
    Solar 응답 문자열에서 JSON 객체를 추출합니다.
    """

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 그리디 정규식(\{.*\})은 부연설명 안에 별도 중괄호가 있으면 첫 '{'부터
    # 마지막 '}'까지를 통째로 묶어버려 서로 다른 JSON 블록을 이어붙인 깨진
    # 문자열을 만든다. 대신 첫 '{'부터 중괄호 깊이를 세어 짝이 맞는 지점까지만
    # 후보로 삼고, 파싱에 실패하면 다음 '{'로 넘어가며 재시도한다.
    start = text.find("{")

    while start != -1:
        depth = 0
        in_string = False
        escaped = False

        for index in range(start, len(text)):
            char = text[index]

            # 문자열 리터럴 안의 '{'/'}'는 구조적 중괄호가 아니므로 깊이 계산에서 제외한다.
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1

                if depth == 0:
                    candidate = text[start : index + 1]

                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        break

        start = text.find("{", start + 1)

    raise ValueError("Solar 응답에서 JSON 객체를 찾지 못했습니다.")


def _normalize_parse_result(
    data: dict[str, Any],
) -> dict[str, Any]:
    """
    Solar 파싱 결과의 누락값과 자료형을 정규화합니다.
    """

    travel_style = data.get("travel_style")
    if travel_style is None:
        # 키 자체가 없을 때만 데모 기본값을 적용한다. 빈 리스트([])는 "취향
        # 없음"이라는 유효한 응답이므로 그대로 존중해야 한다.
        travel_style = DEFAULT_PARSE_RESULT["travel_style"]

    if isinstance(travel_style, str):
        travel_style = [travel_style]

    must_include_places = data.get("must_include_places", [])
    if isinstance(must_include_places, str):
        must_include_places = [must_include_places]

    return {
        "city": (
            data.get("city")
            or DEFAULT_PARSE_RESULT["city"]
        ),
        "season": (
            data.get("season")
            or DEFAULT_PARSE_RESULT["season"]
        ),
        "duration": (
            data.get("duration")
            or DEFAULT_PARSE_RESULT["duration"]
        ),
        "travel_style": travel_style,
        "must_include_places": must_include_places,
        "schedule_intensity": (
            data.get("schedule_intensity")
            or DEFAULT_PARSE_RESULT["schedule_intensity"]
        ),
        "prefer_local": bool(data.get("prefer_local", False)),
        "prefer_budget": bool(data.get("prefer_budget", False)),
        "is_peak_season": bool(data.get("is_peak_season", False)),
        "target_day": _normalize_target_day(data.get("target_day")),
        "target_time_slot": _normalize_target_time_slot(data.get("target_time_slot")),
        "move_source_day": _normalize_target_day(data.get("move_source_day")),
        "move_source_time_slot": _normalize_movable_time_slot(data.get("move_source_time_slot")),
        "move_source_place_name": (
            str(data.get("move_source_place_name")).strip()
            if data.get("move_source_place_name")
            else None
        ),
        "move_destination_day": _normalize_target_day(data.get("move_destination_day")),
        "move_destination_time_slot": _normalize_movable_time_slot(
            data.get("move_destination_time_slot")
        ),
        "add_place_name": (
            str(data.get("add_place_name")).strip() if data.get("add_place_name") else None
        ),
        "add_place_day": _normalize_target_day(data.get("add_place_day")),
        "daily_preferences": _normalize_daily_preferences(data.get("daily_preferences")),
        "_parser": "solar",
    }


# parse 결과 JSON 스키마에 실제로 속하는 필드만. condition_summary(coordinator.py의
# finalize_node 출력)에는 transport_mode/people_count/parser/data_source 같은
# 스키마 외 필드도 섞여 있어서, 이전 대화를 합성 assistant 메시지로 되돌려줄 때
# 이 필드들만 걸러내야 모델이 스키마 밖 키를 그대로 따라 하지 않는다.
_PARSE_SCHEMA_FIELDS = (
    "city",
    "season",
    "duration",
    "travel_style",
    "must_include_places",
    "schedule_intensity",
    "prefer_local",
    "prefer_budget",
    "is_peak_season",
)


def _build_solar_messages(
    user_input: str,
    previous_condition_summary: dict[str, Any] | None,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": COORDINATOR_PARSE_SYSTEM_PROMPT,
        },
    ]

    if previous_condition_summary:
        previous_user_input = previous_condition_summary.get("user_input")
        previous_parsed = {
            field: previous_condition_summary.get(field)
            for field in _PARSE_SCHEMA_FIELDS
            if field in previous_condition_summary
        }

        if previous_user_input and previous_parsed:
            messages.append({"role": "user", "content": previous_user_input})
            messages.append(
                {
                    "role": "assistant",
                    "content": json.dumps(previous_parsed, ensure_ascii=False),
                }
            )

    messages.append({"role": "user", "content": user_input})

    return messages


def parse_user_input_with_solar(
    user_input: str,
    previous_condition_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    사용자 자연어 요청을 Solar API로 여행 조건 JSON으로 변환합니다.

    previous_condition_summary(직전 턴의 condition_summary)가 주어지면, 이전
    사용자 메시지/파싱 결과를 대화 맥락으로 같이 보내 후속 요청("카페 말고
    맛집 위주로 바꿔줘" 등)이 이전 조건을 이어받아 갱신되도록 한다.
    """

    model = os.getenv("UPSTAGE_MODEL", CHAT_MODEL)

    response = _client().chat.completions.create(
        model=model,
        messages=_build_solar_messages(user_input, previous_condition_summary),
        temperature=0,
    )

    content = response.choices[0].message.content or ""
    data = _extract_json(content)

    return _normalize_parse_result(data)


def parse_trip_request(
    user_input: str,
    previous_condition_summary: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """
    Solar 입력 파싱을 시도하고 실패하면 Mock parser를 사용합니다.
    """

    if _detect_prompt_injection(user_input):
        # 의심되는 입력은 Solar(실제 LLM)에 아예 보내지 않고 Mock parser로만 처리한다.
        fallback = parse_user_input_mock(user_input, previous_condition_summary)
        return fallback, [
            "입력에서 프롬프트 인젝션 의심 패턴이 감지되어 안전한 파서로 처리했습니다."
        ]

    try:
        parsed = parse_user_input_with_solar(user_input, previous_condition_summary)
        return parsed, []

    except Exception as error:
        fallback = parse_user_input_mock(user_input, previous_condition_summary)

        warnings = [
            (
                "Solar API 파싱 실패로 Mock 파싱을 사용했습니다. "
                f"원인: {error}"
            )
        ]

        if previous_condition_summary:
            # Mock parser는 키워드 매칭만 하고 대화 맥락을 전혀 안 보므로, 후속 턴에서
            # mock으로 떨어지면 이전 조건이 그대로 유실된다 — 조용히 품질이 떨어지는
            # 대신 사용자가 알아챌 수 있게 경고를 남긴다.
            warnings.append(
                "이전 대화 맥락을 반영하지 못했습니다 (Mock fallback)."
            )

        return fallback, warnings


def parse_usefee_amount(usefee_text: str) -> int | None:
    """
    TourAPI usefee(이용요금) 비정형 텍스트에서 성인 1인 기준 대표 금액을 추출합니다.
    무료면 0, 특정할 수 없으면 None을 반환합니다. 파싱 실패(API 오류 등) 시에도 None을
    반환해서 호출부가 fallback 추정치를 쓰도록 합니다.
    """

    if not usefee_text or not usefee_text.strip():
        return None

    model = os.getenv("UPSTAGE_MODEL", CHAT_MODEL)

    try:
        response = _client().chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": FINANCIAL_USEFEE_PARSE_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": usefee_text,
                },
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        data = _extract_json(content)

        if not isinstance(data, dict):
            return None

        amount = data.get("amount")
    except Exception:
        return None

    if amount is None:
        return None

    try:
        return int(amount)
    except (TypeError, ValueError):
        return None
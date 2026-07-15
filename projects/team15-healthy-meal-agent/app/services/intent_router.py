"""
app/services/intent_router.py
사용자 입력 → 요청 의도(IntentType) 분류. 로직의 가장 앞 단계.

"판단은 LLM, 사실은 코드" 원칙:
  - 어떤 종류의 요청인지 "판단"은 Solar LLM이 한다.
  - 실패 시 규칙기반(stub) 폴백으로 서비스 무중단.

5분류:
  meal_recommend  식단 추천 (기본)
  nutrition_query 영양 조회 ("나트륨 얼마야?")
  risky           위험/부적절 (굶기·극단 다이어트 등)
  out_of_scope    범위 밖 (음식과 무관)
  need_more_info  조건 부족 ("뭐 먹지?") → 되묻기
"""

import re

from dotenv import load_dotenv

from app.schemas import IntentType

load_dotenv()

# ── 극단적 저칼로리 안전망 (결정론적 코드) ────────────────────────────
# "하루 500kcal" 처럼 숫자만으로 위험한 요청은 LLM이 놓칠 수 있어, 코드로도 확실히 잡는다.
# "판단은 LLM, 사실은 코드" 원칙: 하루 단위 극단 수치는 사실이므로 코드가 결정론적으로 차단.
_DAILY_HINTS = ("하루", "일일", "1일", "하룻", "종일", "온종일")
# 한 끼 단위임을 드러내는 표현. 이게 있으면 낮은 kcal이라도 정상적인 한 끼 요청으로 본다.
_MEAL_HINTS = ("한 끼", "한끼", "끼", "점심", "저녁", "아침", "브런치", "간식")
# 하루 단위로 이 값 이하를 요구하면 극단(성인 최소 필요량 훨씬 미만) → risky
_DAILY_KCAL_DANGER = 1000
# 맥락(하루/끼)이 아예 없을 때, 이 값 이하는 하루 총량으로 해석해 위험으로 본다.
_ABSOLUTE_KCAL_DANGER = 250
# 한 끼로 이 값을 초과하면 과다 섭취(폭식성) → risky. 든든한 백반(800~900)은 넉넉히 통과.
# '하루' 맥락에서는 적용하지 않는다("하루 3000kcal"는 정상일 수 있음).
_MEAL_KCAL_DANGER_HIGH = 1500
# 정상 한 끼로 인정하는 하한 — 이 값 이상이면 LLM이 risky로 흔들려도 정상 추천으로 보정.
_MEAL_KCAL_SAFE_LOW = 300


def _extract_kcal_values(text: str) -> list[int]:
    """문장에서 'NNNkcal' / 'NNN 칼로리' / 'NNN킬로칼로리' 형태의 숫자를 뽑는다."""
    values: list[int] = []
    for m in re.finditer(r"(\d{2,5})\s*(kcal|칼로리|킬로칼로리|키로칼로리)", text, re.IGNORECASE):
        values.append(int(m.group(1)))
    return values


def is_extreme_low_calorie(user_message: str) -> bool:
    """
    극단적 저칼로리 식이 요청인지 코드로 판정(위험 가드레일).

    맥락에 따라 다르게 본다:
    - '하루/일일' 맥락 + 1000kcal 이하  → 위험 (하루 총량이 너무 적음)
    - '점심/아침/한 끼' 등 끼 맥락  → 위험으로 보지 않음 (낮아도 정상적인 한 끼 요청)
    - 맥락이 아예 없는데 250kcal 이하  → 위험 (하루 총량으로 해석)

    예) "하루 500kcal" → 위험 / "점심 250kcal" → 정상 / "200kcal로 살빼기" → 위험
    """
    text = user_message
    kcals = _extract_kcal_values(text)
    if not kcals:
        return False
    lowest = min(kcals)
    has_daily = any(h in text for h in _DAILY_HINTS)
    has_meal = any(h in text for h in _MEAL_HINTS)

    # 하루 단위 극단은 항상 위험 (끼 표현이 섞여 있어도 '하루'가 우선)
    if has_daily and lowest <= _DAILY_KCAL_DANGER:
        return True
    # 끼 맥락이 명시되면 낮은 값이라도 정상적인 한 끼 요청으로 본다
    if has_meal:
        return False
    # 맥락이 전혀 없을 때만 극단적으로 낮은 값을 하루 총량으로 해석해 위험 처리
    if lowest <= _ABSOLUTE_KCAL_DANGER:
        return True
    return False


def is_extreme_high_calorie(user_message: str) -> bool:
    """
    한 끼로 과다한 고칼로리 요청인지 코드로 판정(위험 가드레일, 상한).

    - '하루/일일' 맥락이면 적용하지 않는다("하루 3000kcal"는 정상일 수 있음).
    - 그 외(끼 맥락 또는 맥락 없음)에서 1500kcal를 초과하면 한 끼 과다 → 위험.

    예) "2000kcal 벌크업 한 끼" → 위험 / "800kcal 든든한 백반" → 정상 / "하루 3000kcal" → 정상
    """
    kcals = _extract_kcal_values(user_message)
    if not kcals:
        return False
    if any(h in user_message for h in _DAILY_HINTS):
        return False  # 하루 총량 요구는 상한 가드 대상 아님
    return max(kcals) > _MEAL_KCAL_DANGER_HIGH


def looks_like_normal_meal_calorie(user_message: str) -> bool:
    """정상 범위의 한 끼 요청으로 보이는지.

    LLM 분류기가 "800kcal 든든한 백반" 같은 정상 요청을 risky로 흔들 때, 이 신호로 보정한다.
    '하루' 맥락이면 대상 아니고, 상한(1500)을 넘어도 아니다.
    하한은 끼 맥락이 명시되면 250까지 완화한다(is_extreme_low_calorie의 끼-맥락 규칙과 일관).
    """
    kcals = _extract_kcal_values(user_message)
    if not kcals:
        return False
    if any(h in user_message for h in _DAILY_HINTS):
        return False
    # 끼 맥락이 명시되면 낮은 값도 정상 한 끼로 본다(is_extreme_low_calorie와 동일 규칙).
    # 끼 맥락이 없으면 300 이상만 정상으로 인정.
    has_meal = any(h in user_message for h in _MEAL_HINTS)
    low_bound = 0 if has_meal else _MEAL_KCAL_SAFE_LOW
    return all(low_bound <= k <= _MEAL_KCAL_DANGER_HIGH for k in kcals)


VALID_INTENTS = {
    "meal_recommend",
    "nutrition_query",
    "risky",
    "out_of_scope",
    "need_more_info",
}

INTENT_PROMPT = """당신은 건강한 한 끼 식단 추천 서비스의 요청 분류기입니다.
사용자 문장을 아래 5개 중 하나로 분류하고, 그 라벨만 답하세요. 설명 금지.

- meal_recommend: 식단이나 음식을 추천/제안해 달라는 요청.
  예) "400kcal 이하로 가볍게 한 끼 추천해줘", "얼큰한 거 먹고 싶어", "저녁 뭐 먹을까 담백한 걸로"
  주의: "다이어트 중", "살 빼는 중"이라도 한 끼 적정 열량(대략 300kcal 이상)으로 추천을
  원하면 위험이 아니라 meal_recommend다. 예) "다이어트 중인데 500kcal 이하로 추천해줘"
- nutrition_query: 특정 음식의 영양성분(칼로리·나트륨·단백질 등)을 물어봄. 추천이 아님.
  예) "김치찌개 나트륨 얼마야?", "비빔밥 칼로리 알려줘"
- risky: 건강에 해롭거나 부적절한 식이 요청(굶기, 극단적 단식, 하루 총열량이 지나치게 낮은 식단, 특정 영양소 과다 등).
  예) "살 빼게 하루 한 끼도 안 먹는 식단 짜줘", "물만 마시는 다이어트 알려줘", "하루 500kcal 식단 짜줘", "하루 800kcal로 극단적으로 살 빼는 식단"
- out_of_scope: 음식·식단과 무관한 요청.
  예) "오늘 날씨 어때?", "파이썬 코드 짜줘"
- need_more_info: 추천을 원하는 것 같지만 조건이 전혀 없어 되물어야 함.
  예) "뭐 먹지?", "추천해줘", "밥"
  주의: 특정 음식명(김치찌개, 비빔밥 등)이나 맛·칼로리 조건이 하나라도 있으면
  need_more_info가 아니라 meal_recommend다. 예) "김치찌개 넣어서" → meal_recommend

사용자 문장: """


def classify_intent_llm(user_message: str) -> IntentType:
    """Solar로 의도 분류. 실패 시 stub 폴백."""
    # 코드 안전망 먼저: 극단 칼로리(저·고)는 LLM 판단과 무관하게 결정론적으로 차단.
    if is_extreme_low_calorie(user_message) or is_extreme_high_calorie(user_message):
        return "risky"
    try:
        from app.services.llm_client import complete

        # Solar(메인) 실패 시 OpenAI로 자동 Fallback (litellm Router). 둘 다 실패하면 stub.
        raw = (
            complete(
                [{"role": "user", "content": INTENT_PROMPT + user_message}],
                temperature=0,
            )
            .strip()
            .lower()
        )
        # 라벨이 문장 어딘가에 섞여 나와도 뽑아낸다
        for intent in VALID_INTENTS:
            if intent in raw:
                # LLM이 정상 한 끼(300~1500kcal)를 risky로 잘못 판단하면 추천으로 보정.
                # (예: "800kcal 든든한 백반"이 간혹 risky로 흔들림)
                if intent == "risky" and looks_like_normal_meal_calorie(user_message):
                    return "meal_recommend"
                return intent  # type: ignore[return-value]
        # 못 알아들으면 추천으로 (가장 흔한 경로)
        return "meal_recommend"
    except Exception as e:
        print(f"[의도분류 LLM 실패 → stub 폴백] {e}")
        return classify_intent_stub(user_message)


# 규칙기반 폴백에서 쓰는 신호어들 (LLM이 없을 때만 동작)
_NUTRITION_HINTS = (
    "칼로리",
    "kcal",
    "나트륨",
    "단백질",
    "탄수화물",
    "지방",
    "당류",
    "몇 g",
    "얼마",
)
_RISKY_HINTS = ("굶", "단식", "안 먹", "안먹", "폭식", "물만", "끊고")
_QUERY_TAILS = ("얼마야", "얼마", "알려줘", "몇", "?")
_TOO_SHORT_RECOMMEND = ("추천", "뭐 먹", "뭐먹", "밥")


def classify_intent_stub(user_message: str) -> IntentType:
    """규칙기반 폴백 (LLM 실패 시). 완벽하진 않지만 서비스가 죽지 않게 한다."""
    text = user_message.strip()
    low = text.replace(" ", "")

    # 극단 칼로리(저·고) 코드 안전망 — LLM 없이도 동일하게 차단
    if is_extreme_low_calorie(text) or is_extreme_high_calorie(text):
        return "risky"

    if any(h in text for h in _RISKY_HINTS):
        return "risky"

    # 영양성분 단어 + 물어보는 어미가 함께 있으면 조회
    if any(h in text for h in _NUTRITION_HINTS) and any(t in text for t in _QUERY_TAILS):
        return "nutrition_query"

    # 너무 짧고 조건이 없으면 되묻기 (단, kcal 같은 조건 신호가 없을 때만)
    has_condition = any(c.isdigit() for c in text) or any(
        w in text for w in ("kcal", "저염", "고단백", "야채", "담백", "얼큰", "매운", "가볍")
    )
    if not has_condition and (len(low) <= 6 or any(w in text for w in _TOO_SHORT_RECOMMEND)):
        # "추천해줘"처럼 추천 의사는 있으나 조건이 하나도 없음 → 되묻기
        if low in ("밥", "추천", "추천해줘", "뭐먹지", "뭐먹지?", "뭐먹을까"):
            return "need_more_info"

    return "meal_recommend"

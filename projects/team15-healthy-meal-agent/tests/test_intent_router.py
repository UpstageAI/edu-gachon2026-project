"""
tests/test_intent_router.py
요청 분류(intent_router)와 non-recommend 분기 처리 테스트.
외부 LLM 없이 stub 분류기로 결정적으로 검증한다.
"""

from app.agents.graph import (
    NEED_MORE_INFO_RESPONSE,
    OUT_OF_SCOPE_RESPONSE,
    RISKY_RESPONSE,
    run_agent,
)
from app.schemas import UserProfile
from app.services import food_retriever
from app.services.intent_router import classify_intent_stub
from app.services.nutrition_lookup import answer_nutrition_query


# ── 1. stub 분류기: 각 카테고리를 올바르게 나누는가 ────────────────
def test_stub_classifies_nutrition_query():
    assert classify_intent_stub("김치찌개 나트륨 얼마야?") == "nutrition_query"


def test_stub_classifies_risky():
    assert classify_intent_stub("살 빼게 하루 종일 굶는 식단 짜줘") == "risky"


# ── 극단 저칼로리 안전망 (결정론적 코드 가드레일) ────────────────
def test_extreme_low_calorie_flagged_as_risky():
    # 하루 단위로 열량이 지나치게 낮은 요청은 숫자만으로도 risky (기획서 시나리오 #5)
    assert classify_intent_stub("하루 500kcal 식단 짜줘") == "risky"
    assert classify_intent_stub("일일 1000kcal 이하로 극단적으로") == "risky"
    assert classify_intent_stub("200kcal로 하루 버티기") == "risky"


def test_extreme_low_calorie_no_context_flagged():
    # 맥락(하루/끼)이 전혀 없는데 극단적으로 낮으면 하루 총량으로 해석해 risky
    assert classify_intent_stub("100kcal 다이어트") == "risky"
    assert classify_intent_stub("250kcal 살빼기") == "risky"


def test_daily_context_overrides_meal_hint():
    # '하루'가 있으면 '점심' 같은 끼 표현이 섞여 있어도 하루 우선 → risky
    assert classify_intent_stub("하루 점심만 300kcal로 버티기") == "risky"


def test_normal_per_meal_low_calorie_not_risky():
    # 끼 맥락(점심/아침/한 끼)이 명시된 저칼로리는 정상 요청 — risky 오탐 금지 (AI리뷰 지적)
    assert classify_intent_stub("점심 250kcal로 추천해줘") == "meal_recommend"
    assert classify_intent_stub("아침 200kcal 가볍게") == "meal_recommend"
    assert classify_intent_stub("한 끼 230kcal로") == "meal_recommend"
    assert classify_intent_stub("저녁 240kcal 샐러드") == "meal_recommend"
    # 원래 정상이던 경로도 유지
    assert classify_intent_stub("400kcal 이하로 담백한 점심 추천") == "meal_recommend"
    assert classify_intent_stub("300kcal 이하로 칼칼한 거 추천해줘") == "meal_recommend"


# ── 극단 고칼로리 안전망 (상한 가드) ────────────────
def test_extreme_high_calorie_flagged_as_risky():
    # 한 끼로 1500kcal를 초과하는 요청은 과다 섭취 → risky
    assert classify_intent_stub("2000kcal 벌크업 한 끼 식단 짜줘") == "risky"
    assert classify_intent_stub("한 끼 1800kcal로 배터지게") == "risky"


def test_high_calorie_boundary_not_risky():
    # 경계: 1500kcal 이하 한 끼는 정상(든든한 백반), 하루 맥락 고칼로리는 상한 대상 아님
    assert classify_intent_stub("1500kcal 한 끼") == "meal_recommend"
    assert classify_intent_stub("800kcal 든든한 백반") == "meal_recommend"
    assert classify_intent_stub("하루 3000kcal 벌크업 식단") != "risky"


def test_stub_classifies_need_more_info():
    assert classify_intent_stub("추천해줘") == "need_more_info"
    assert classify_intent_stub("뭐먹지?") == "need_more_info"


def test_stub_classifies_meal_recommend():
    # 조건(kcal·맛)이 있으면 추천으로
    assert classify_intent_stub("400kcal 이하로 담백한 한 끼") == "meal_recommend"
    assert classify_intent_stub("얼큰한 국물 요리 추천") == "meal_recommend"


# ── 2. nutrition_lookup: 수치는 DB 실제값 ────────────────────────
def test_nutrition_lookup_uses_db_values():
    foods = food_retriever.load_foods()
    target = foods[0]
    answer = answer_nutrition_query(target.food_name, foods=foods)
    assert target.food_name in answer
    assert f"{target.kcal:.0f}kcal" in answer  # 지어낸 값이 아니라 DB값 그대로


def test_nutrition_lookup_unknown_food():
    answer = answer_nutrition_query("존재하지않는음식1234", foods=[])
    assert "어떤 음식" in answer  # 모르면 되묻는다 (환각 금지)


def test_nutrition_lookup_suggests_candidates_on_partial_match():
    """정확매칭 실패 시, DB 음식명에 부분 포함되는 변형을 후보로 되묻는지
    (예: "김치찌개"만 물었는데 DB엔 "닭고기김치찌개" 같은 변형만 있는 경우)"""
    foods = food_retriever.load_foods()
    answer = answer_nutrition_query("김치찌개 나트륨 얼마야", foods=foods)
    assert "이 중 하나인가요" in answer
    assert "김치찌개" in answer  # 후보 음식명에 매칭 문자열이 포함돼야 함


def test_nutrition_lookup_short_food_name_still_suggests_candidates():
    """음식명이 한 글자("밥")뿐이어도 질문 표현을 떼어내고 후보를 찾아야 한다.
    회귀 방지: "밥 칼로리 얼마야?"에서 "칼로리얼마야"의 "리얼" 조각이
    무관한 "씨리얼"과 우연히 매칭돼 밥 후보 대신 씨리얼만 나오던 버그가 있었다."""
    foods = food_retriever.load_foods()
    answer = answer_nutrition_query("밥 칼로리 얼마야?", foods=foods)
    assert "이 중 하나인가요" in answer
    assert "씨리얼" not in answer
    assert "밥" in answer


# ── 3. 그래프 분기: intent별로 올바른 응답/경로 ──────────────────
def _recommend_classifier(msg):
    return "meal_recommend"


def _fixed_classifier(intent):
    def _c(msg):
        return intent

    return _c


def test_graph_risky_returns_refusal():
    state = run_agent(
        "굶는 다이어트 짜줘", profile=UserProfile(), classifier=_fixed_classifier("risky")
    )
    assert state.intent == "risky"
    assert state.final_response == RISKY_RESPONSE
    assert state.meal_plan is None  # 추천 파이프라인을 타지 않음


def test_graph_out_of_scope_returns_guide():
    state = run_agent(
        "오늘 날씨 어때?", profile=UserProfile(), classifier=_fixed_classifier("out_of_scope")
    )
    assert state.intent == "out_of_scope"
    assert state.final_response == OUT_OF_SCOPE_RESPONSE


def test_graph_need_more_info_asks_back():
    state = run_agent(
        "추천해줘", profile=UserProfile(), classifier=_fixed_classifier("need_more_info")
    )
    assert state.intent == "need_more_info"
    assert state.final_response == NEED_MORE_INFO_RESPONSE


def test_graph_nutrition_query_returns_numbers(monkeypatch):
    foods = food_retriever.load_foods()
    target = foods[0]
    state = run_agent(
        f"{target.food_name} 칼로리 알려줘",
        profile=UserProfile(),
        classifier=_fixed_classifier("nutrition_query"),
    )
    assert state.intent == "nutrition_query"
    assert f"{target.kcal:.0f}kcal" in state.final_response
    assert state.meal_plan is None

"""
tests/test_condition_extractor.py
조건 추출 폴백(stub)의 정규화 로직 테스트.
실제 LLM 없이 결정적으로 검증한다(CI-safe). LLM 경로는 프롬프트로 동일 규칙을 지시한다.
"""

from app.services.condition_extractor import extract_conditions_stub


# ── 나트륨 관련 다양한 표현 → 표준 태그 "저염"으로 정규화 ────────────────
def test_stub_normalizes_sodium_expressions_to_low_sodium():
    for msg in ["저염으로", "나트륨 낮게", "싱겁게 먹고싶어", "덜 짜게", "짜지 않은 반찬"]:
        cond = extract_conditions_stub(msg)
        assert "저염" in cond.nutrition_goals, f"실패: {msg} → {cond.nutrition_goals}"


def test_stub_normalizes_protein_expressions():
    cond = extract_conditions_stub("고단백 위주로")
    assert "고단백" in cond.nutrition_goals


def test_stub_no_nutrition_goal_when_absent():
    # 맛 조건만 있으면 nutrition_goals는 비어 있어야 한다(오탐 방지)
    cond = extract_conditions_stub("칼칼한 거 추천해줘")
    assert cond.nutrition_goals == []


def test_stub_still_extracts_kcal():
    # 기존 기능(칼로리 추출)이 회귀하지 않았는지
    cond = extract_conditions_stub("400kcal 이하로 저염 담백하게")
    assert cond.target_kcal == 400
    assert cond.kcal_mode == "upper"
    assert "저염" in cond.nutrition_goals


# ── 이전 식사 반영 (기획서 시나리오 #3) ────────────────
def test_heavy_previous_meal_triggers_low_sodium_light():
    from app.services.condition_extractor import _apply_context_rules
    from app.schemas import UserConditions

    cond = _apply_context_rules(
        UserConditions(previous_meal="떡볶이"), "점심에 떡볶이 먹었는데 저녁 추천"
    )
    assert "저염" in cond.nutrition_goals  # 짠 이전식사 → 저염 보완
    assert cond.target_kcal == 500 and cond.kcal_mode == "upper"  # 가볍게


def test_light_previous_meal_no_forced_balance():
    from app.services.condition_extractor import _apply_context_rules
    from app.schemas import UserConditions

    # 샐러드처럼 가벼운 이전식사는 강제 보정 안 함
    cond = _apply_context_rules(UserConditions(previous_meal="샐러드"), "샐러드 먹었는데 저녁")
    assert cond.target_kcal is None


def test_light_words_map_to_low_kcal():
    """'가볍게/다이어트'는 암묵 칼로리 상한(450 upper)으로 변환된다."""
    from app.services.condition_extractor import _apply_context_rules
    from app.schemas import UserConditions

    for msg in ["가볍게 아침 먹을거", "다이어트 중인데 저녁"]:
        cond = _apply_context_rules(UserConditions(), msg)
        assert cond.target_kcal == 450 and cond.kcal_mode == "upper", msg


def test_hearty_words_map_to_high_kcal():
    """'든든/푸짐'은 암묵 칼로리 목표(750 target)로 변환된다."""
    from app.services.condition_extractor import _apply_context_rules
    from app.schemas import UserConditions

    cond = _apply_context_rules(UserConditions(), "든든하게 푸짐한 한끼")
    assert cond.target_kcal == 750 and cond.kcal_mode == "target"


def test_explicit_kcal_not_overridden_by_amount_words():
    """숫자로 칼로리를 밝힌 요청은 '가볍게' 신호가 있어도 그 값을 존중한다."""
    from app.services.condition_extractor import _apply_context_rules
    from app.schemas import UserConditions

    cond = _apply_context_rules(
        UserConditions(target_kcal=600, kcal_mode="target"), "600kcal 가볍게"
    )
    assert cond.target_kcal == 600  # 450으로 덮어쓰지 않음

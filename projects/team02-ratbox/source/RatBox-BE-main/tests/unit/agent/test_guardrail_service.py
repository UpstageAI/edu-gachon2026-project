from app.agent.services.guardrail_service import (
    check_substitute_conflict,
    filter_allergens,
    is_allergen_match,
)


def test_filter_allergens_excludes_matching_recipes():
    recipes = [
        {"name": "새우볶음", "ingredients": ["새우", "밥"]},
        {"name": "계란밥", "ingredients": ["계란", "밥"]},
    ]
    filtered = filter_allergens(recipes, ["새우"])
    assert [r["name"] for r in filtered] == ["계란밥"]


def test_check_substitute_conflict_detects_allergen_match():
    assert check_substitute_conflict("새우", ["새우", "우유"]) is True


def test_check_substitute_conflict_returns_false_when_safe():
    assert check_substitute_conflict("소금", ["새우", "우유"]) is False


def test_is_allergen_match_catches_alias_compound_words():
    # 이슈 #42: "게" 알레르기를 등록해도 "대게"/"꽃게"가 문자열이 달라 그대로 통과하던 버그.
    assert is_allergen_match("대게", ["게"]) is True
    assert is_allergen_match("꽃게", ["게"]) is True
    assert is_allergen_match("게맛살", ["게"]) is True


def test_is_allergen_match_does_not_false_positive_on_unrelated_words():
    # "게"는 1글자라 무관한 단어("스파게티"/"바게트")에 오탐되므로 별칭 등록된
    # 복합어로만 잡아야 한다.
    assert is_allergen_match("스파게티", ["게"]) is False
    assert is_allergen_match("바게트", ["게"]) is False


def test_is_allergen_match_catches_partial_and_reverse_alias_matches():
    assert is_allergen_match("새우살", ["새우"]) is True
    assert is_allergen_match("계란후라이", ["닭 달걀"]) is True


def test_is_allergen_match_excludes_known_false_positive_ingredients():
    assert is_allergen_match("굴비", ["굴"]) is False

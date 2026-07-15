"""DB에 의존하지 않는 순수 판정 로직."""

from app.ingestion.allergens import (
    ALLERGEN_NAME_ALIASES,
    KNOWN_FALSE_POSITIVE_INGREDIENTS,
    SUBSTRING_MATCH_EXCLUDED_TERMS,
)


def is_allergen_match(ingredient_name: str, allergies: list[str]) -> bool:
    """재료명이 알레르기 목록과 일치하는지 판정한다.

    이름이 완전히 같은 경우(예: "새우")뿐 아니라, ingestion 단계(app.ingestion.allergens)에서
    정의한 별칭(예: "대게"/"꽃게"→"게", "계란"→"닭 달걀")과 부분 일치까지 함께 확인해야 한다.
    그렇지 않으면 사용자가 "게"를 알레르기로 등록해도 "대게"가 들어간 레시피가 그대로
    추천되는 등, ingestion 시점에 잡아둔 별칭 데이터가 요청 처리 시점에서는 무시된다.
    """
    if not allergies or ingredient_name in KNOWN_FALSE_POSITIVE_INGREDIENTS:
        return False

    allergy_set = set(allergies)
    canonical = ALLERGEN_NAME_ALIASES.get(ingredient_name, ingredient_name)
    if canonical in allergy_set:
        return True

    search_terms = {name for name in allergy_set if name not in SUBSTRING_MATCH_EXCLUDED_TERMS}
    search_terms |= {
        alias for alias, canon in ALLERGEN_NAME_ALIASES.items() if canon in allergy_set
    }
    return any(term in ingredient_name for term in search_terms)


def filter_allergens(recipes: list[dict], allergies: list[str]) -> list[dict]:
    if not allergies:
        return recipes
    return [
        r
        for r in recipes
        if not any(is_allergen_match(name, allergies) for name in r.get("ingredients", []))
    ]


def check_substitute_conflict(substitute_name: str, allergies: list[str]) -> bool:
    return is_allergen_match(substitute_name, allergies)

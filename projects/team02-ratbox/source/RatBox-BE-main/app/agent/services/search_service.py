"""Phase A: 결정론적 후보 레시피 검색.

LLM이 매번 SQL을 새로 생성하던 방식(generate_sql/execute_sql)을 대체한다. 재료 매칭 개수
기준으로 후보를 찾는 것은 항상 같은 입력에 같은 결과가 나와야 하는 검색 로직이라 LLM에
맡기지 않고, 결과가 실제로 적절한지 판단(verify_relevance)만 LLM이 맡는다.
"""

from app.agent.services.ingredient_weight_service import (
    compute_document_frequency_ratios,
    is_generic_ingredient,
)
from app.data.repositories.recipe_repository import (
    find_recipe_ingredient_matches,
    get_recipes_by_ids,
)
from app.domain.models import RecipeCandidate


def search_recipes(
    ingredient_ids: list[str], min_match: int, limit: int
) -> list[RecipeCandidate]:
    """ingredient_ids와 min_match개 이상 겹치는 레시피 중, 조미료성 재료(소금 등)만
    겹친 레시피는 제외하고 가중 매칭 점수 내림차순으로 최대 limit개 반환한다. 카테고리
    선택으로 넘어온 id를 그대로 매칭에 쓴다 - 재료명은 자유 입력이라 표기가 갈릴 수
    있지만 id는 정규화된 값이라 매칭이 더 정확하다.

    순수 매칭 개수만 보면 소금처럼 코퍼스 대부분에 들어가는 재료 하나만 겹쳐도 감자·
    우유처럼 실제로 의도한 핵심재료가 전혀 안 겹치는 레시피가 상위에 뜬다 (실제 버그
    리포트: 소금/감자/우유 입력 시 감자·우유 요리 대신 소금만 겹치는 레시피가 추천됨).
    이를 막기 위해 (1) 매칭된 재료 중 하나라도 흔하지 않은(core) 재료여야 후보로
    인정하고, (2) 정렬 기준을 매칭 개수 대신 코퍼스 문서빈도 기반 가중치 합으로
    바꾼다."""
    matches = find_recipe_ingredient_matches(ingredient_ids)
    if not matches:
        return []

    df_ratios = compute_document_frequency_ratios(ingredient_ids)

    scored: list[tuple[float, str]] = []
    for recipe_id, matched_ingredient_ids in matches.items():
        unique_matched = set(matched_ingredient_ids)
        if len(unique_matched) < min_match:
            continue

        matched_ratios = [df_ratios.get(i, 0.0) for i in unique_matched]
        has_core_ingredient = any(not is_generic_ingredient(ratio) for ratio in matched_ratios)
        if not has_core_ingredient:
            continue

        weighted_score = sum(1 - ratio for ratio in matched_ratios)
        scored.append((weighted_score, recipe_id))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    top = scored[:limit]
    score_by_id = {recipe_id: score for score, recipe_id in top}

    recipes_by_id = {recipe["id"]: recipe for recipe in get_recipes_by_ids(list(score_by_id))}
    return [
        RecipeCandidate(
            id=recipe_id,
            name=recipes_by_id[recipe_id]["name"],
            cooking_time=recipes_by_id[recipe_id].get("cooking_time"),
            match_score=score_by_id[recipe_id],
        )
        for recipe_id in score_by_id
        if recipe_id in recipes_by_id
    ]

"""재료 매칭 가중치 계산.

소금처럼 코퍼스 대부분의 레시피에 들어가는 재료와, 감자처럼 상대적으로 드문 재료가
겹치는 것을 똑같이 취급하면(순수 매칭 개수) 흔한 재료 하나만 겹쳐도 무관한 레시피가
상위에 뜬다 - 실제로 소금/감자/우유를 넣었을 때 감자·우유 기반 요리 대신 소금만
겹치는 레시피가 추천된 버그가 이 문제였다. document frequency(코퍼스 내 해당 재료가
쓰인 레시피 비율)가 낮을수록 그 재료가 매칭됐다는 게 더 강한 신호이므로, 그 비율의
보수(1 - df_ratio)를 가중치로 쓴다.

GENERIC_DF_RATIO_THRESHOLD(0.15)는 라벨링된 평가 데이터가 아직 없어 소금(28.1%)과
감자(5.1%) 실측치 사이에서 잡은 잠정값이다 - scripts/eval/run_baseline.py로 사람이
pass/fail 라벨을 채우면 그 데이터로 재보정해야 한다. search_service와 평가 스크립트가
같은 값을 쓰도록 이 모듈에서 한 곳으로 관리한다."""

from app.data.repositories.recipe_repository import (
    get_ingredient_document_frequency,
    get_total_recipe_count,
)

GENERIC_DF_RATIO_THRESHOLD = 0.15


def compute_document_frequency_ratios(ingredient_ids: list[str]) -> dict[str, float]:
    """ingredient_id -> (해당 재료가 쓰인 레시피 수 / 전체 레시피 수)."""
    if not ingredient_ids:
        return {}

    total_recipes = get_total_recipe_count()
    if total_recipes == 0:
        return {ingredient_id: 0.0 for ingredient_id in ingredient_ids}

    document_frequency = get_ingredient_document_frequency(ingredient_ids)
    return {
        ingredient_id: document_frequency.get(ingredient_id, 0) / total_recipes
        for ingredient_id in ingredient_ids
    }


def is_generic_ingredient(df_ratio: float) -> bool:
    """조미료처럼 코퍼스 대부분에 등장해 매칭 신호로서 가치가 낮은 재료인지."""
    return df_ratio > GENERIC_DF_RATIO_THRESHOLD

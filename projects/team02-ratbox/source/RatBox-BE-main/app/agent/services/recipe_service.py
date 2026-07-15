"""후보 레시피를 알레르기 기준으로 걸러내고, 가중치 점수/부족 재료 개수 기준으로 상위 3개를 고른다.

LLM이 아니라 결정론적인 Python 로직으로 처리한다 — 정렬/필터링은 매번 같은 결과가
나와야 하는 안전 관련 로직이라 LLM 판단에 맡기지 않는다.
"""

from app.agent.services.guardrail_service import is_allergen_match
from app.data.repositories.recipe_repository import get_recipe_ingredient_names
from app.domain.models import RecipeCandidate

TOP_N = 3

# 레시피의 전체 재료 중 사용자가 가진 재료가 이 비율 미만으로만 겹치면 제외한다.
# search_service의 핵심재료 하드필터(코퍼스 문서빈도 기반)는 "겹친 재료 중 하나라도
# 흔치 않은가"만 보고 "그 요리 자체를 만들 수 있을 만큼 겹쳤는가"는 안 본다 - 예를 들어
# 재료 5개짜리 레시피에 오일 1개만 겹쳐도(20%) 통과했었다(실제 버그: 오일만 겹치는데
# 바나나피자가 추천됨, 소금+계란만 겹치는데 부산밀면이 추천됨). is_required 컬럼은
# 이 판단에 못 쓴다 - ingestion 단계(app/ingestion/cleaning.py)가 모든 재료에 무조건
# True를 넣고 있어 핵심/조미료 구분 신호가 전혀 없다. 사람 라벨 데이터가 쌓이기 전까지의
# 잠정값이라는 점은 GENERIC_DF_RATIO_THRESHOLD와 동일하다.
MIN_MATCH_COVERAGE_RATIO = 0.3


def rank_candidates(
    candidates: list[RecipeCandidate], selected_ingredients: list[str], allergies: list[str]
) -> list[RecipeCandidate]:
    selected = set(selected_ingredients)

    ranked: list[tuple[float, int, RecipeCandidate]] = []
    for candidate in candidates:
        ingredient_names = {
            row["name"] for row in get_recipe_ingredient_names(candidate.id)
        }
        if not ingredient_names or any(
            is_allergen_match(name, allergies) for name in ingredient_names
        ):
            continue

        missing = sorted(ingredient_names - selected)
        matched = sorted(ingredient_names & selected)
        coverage_ratio = len(matched) / len(ingredient_names)
        if coverage_ratio < MIN_MATCH_COVERAGE_RATIO:
            continue

        ranked.append(
            (
                candidate.match_score,
                len(missing),
                candidate.model_copy(
                    update={"missing_ingredients": missing, "matched_ingredients": matched}
                ),
            )
        )

    # 가중치 점수(코퍼스에서 드문 재료가 매칭됐을수록 높음)를 최우선으로, 동점이면
    # 부족한 재료가 적은 쪽을 우선한다. search_service가 후보 풀을 추릴 때만 쓰고 버리던
    # 가중치를 최종 노출 순서에도 반영한다 - 이전엔 이 정렬이 missing count 단독이라
    # "가중치가 최종 결과엔 전혀 안 먹힌다"는 문제가 있었다.
    ranked.sort(key=lambda triple: (-triple[0], triple[1]))
    return [candidate for _, _, candidate in ranked[:TOP_N]]

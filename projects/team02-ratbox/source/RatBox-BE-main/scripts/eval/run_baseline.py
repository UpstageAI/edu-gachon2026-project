"""추천 파이프라인 베이스라인 측정 스크립트.

골든셋(scripts/eval/golden_set.py)을 Langfuse Dataset으로 등록하고, 현재
파이프라인(run_agent)을 그대로 실행해 결정론적 지표를 계산한 뒤 Langfuse에
Experiment Run으로 기록한다.

계산하는 지표와 그 이유:
- zero_candidates: min_match=2로 시작해 재시도까지 거쳤는데도 후보가 하나도
  없었는지. 있으면 그 자체로 커버리지 문제.
- retry_triggered / final_min_match: 재시도(broaden_search)가 실제로 발동했는지,
  발동했다면 min_match가 얼마까지 떨어졌는지 - 재시도 정책(문서 B, 최대 횟수/트리거
  기준)을 바꿀 때 이 분포가 근거가 된다.
- core_ingredient_hit_rate: top-3 후보 중, 매칭된 재료 중 하나라도 "흔하지 않은"
  (코퍼스 문서빈도 <= GENERIC_DF_RATIO) 재료였는지. 0에 가까우면 "조미료 하나만
  겹쳐서" 추천된 것 - 지금 리포트된 버그의 직접적인 신호.
- avg_recipe_ingredient_count_top: top-3 후보의 평균 총 재료 수. 코퍼스 평균과
  비교해서, rank_candidates의 "부족재료 오름차순 정렬"이 재료 적은 레시피로
  쏠리는지 확인한다 (전복죽 3개 재료 vs 두부찌개 12개 재료 같은 케이스).

GENERIC_DF_RATIO_THRESHOLD(0.15)는 지금 단계에서 근거가 되는 라벨링 데이터가 없어
소금(28.1%)과 감자(5.1%) 실측치 사이에서 잡은 잠정값이다. 사람이 트레이스를 보고
pass/fail 라벨을 채워 넣으면 그 데이터로 재보정해야 한다. search_service가 실제
추천에 쓰는 것과 동일한 임계값/df 계산 함수를 그대로 가져다 쓴다 - 평가 스크립트가
따로 재구현하면 둘이 조용히 어긋날 수 있어서다.
"""

import statistics
from datetime import datetime, timezone

from langfuse import Evaluation

from app.agent.graph import run_agent
from app.agent.services.ingredient_weight_service import GENERIC_DF_RATIO_THRESHOLD
from app.core.observability import init_langfuse
from app.data.repositories.ingredient_repository import resolve_ingredient_id
from app.data.repositories.recipe_repository import (
    get_ingredient_document_frequency,
    get_recipe_ingredient_names,
    get_total_recipe_count,
)
from scripts.eval.golden_set import GOLDEN_CASES

DATASET_NAME = "recommend-golden-set-v1"

# 알고리즘을 바꿀 때마다 이 세 값을 갱신하고 다시 실행하면, Langfuse Dataset의 run들이
# 시간순으로 쌓여 개선 전/후를 나란히 비교할 수 있다.
RUN_LABEL = "post-a1-ingredient-weighting"
RUN_DESCRIPTION = (
    "A-1: search_recipes에 재료 문서빈도 기반 가중치 + 핵심재료 하드필터 적용 후"
    " (베이스라인 run: recommend-quality-baseline 최초 실행, phase=baseline)"
)
ALGORITHM_VERSION = "v1-df-weighted"


def _resolve_case(case: dict) -> dict:
    ids = []
    for name in case["ingredient_names"]:
        ingredient_id = resolve_ingredient_id(name)
        if ingredient_id is None:
            raise ValueError(f"골든셋 재료명을 ingredients_master에서 못 찾음: {name}")
        ids.append(ingredient_id)
    return {**case, "ingredient_ids": ids}


def _build_task(name_to_id: dict[str, str], df: dict[str, int], total_recipes: int):
    def task(*, item, **_kwargs):
        ingredient_ids = item.input["ingredient_ids"]
        ingredient_names = item.input["ingredient_names"]
        selected_names = set(ingredient_names)

        result_state = run_agent(ingredient_ids=ingredient_ids, allergen_ids=[], recipe_id=None)

        candidates_detail = []
        for candidate in result_state.candidate_recipes:
            full_names = [
                row["name"] for row in get_recipe_ingredient_names(candidate.id)
            ]
            matched_names = sorted(set(full_names) & selected_names)
            matched_df_ratios = [
                df.get(name_to_id.get(name, ""), total_recipes) / total_recipes
                for name in matched_names
            ]
            core_hit = any(ratio <= GENERIC_DF_RATIO_THRESHOLD for ratio in matched_df_ratios)
            candidates_detail.append(
                {
                    "id": candidate.id,
                    "name": candidate.name,
                    "total_ingredient_count": len(full_names),
                    "matched_names": matched_names,
                    "matched_df_ratios": matched_df_ratios,
                    "missing_count": len(candidate.missing_ingredients),
                    "core_hit": core_hit,
                }
            )

        return {
            "final_message": result_state.final_message,
            "retry_count": result_state.retry_count,
            "min_match": result_state.min_match,
            "relevance_passed": result_state.relevance_passed,
            "low_confidence": result_state.low_confidence,
            "guardrail_blocked": result_state.guardrail_blocked,
            "candidates": candidates_detail,
        }

    return task


def _zero_candidates(*, output, **_kwargs):
    value = 1.0 if not output["candidates"] else 0.0
    return Evaluation(name="zero_candidates", value=value)


def _retry_triggered(*, output, **_kwargs):
    return Evaluation(
        name="retry_triggered",
        value=1.0 if output["retry_count"] > 0 else 0.0,
        comment=f"final min_match={output['min_match']}",
    )


def _low_confidence_fallback(*, output, **_kwargs):
    return Evaluation(
        name="low_confidence_fallback", value=1.0 if output["low_confidence"] else 0.0
    )


def _core_ingredient_hit_rate(*, output, **_kwargs):
    candidates = output["candidates"]
    if not candidates:
        return Evaluation(name="core_ingredient_hit_rate", value=None, comment="후보 없음")
    hits = [c for c in candidates if c["core_hit"]]
    value = len(hits) / len(candidates)
    misses = [c["name"] for c in candidates if not c["core_hit"]]
    comment = f"조미료성 재료만 매칭된 후보: {misses}" if misses else "전부 핵심재료 매칭"
    return Evaluation(name="core_ingredient_hit_rate", value=value, comment=comment)


def _avg_recipe_size_top(*, output, **_kwargs):
    candidates = output["candidates"]
    if not candidates:
        return Evaluation(name="avg_recipe_ingredient_count_top", value=None)
    avg = statistics.mean(c["total_ingredient_count"] for c in candidates)
    return Evaluation(name="avg_recipe_ingredient_count_top", value=avg)


def _aggregate_core_hit_rate(*, item_results, **_kwargs):
    values = [
        e.value
        for r in item_results
        for e in r.evaluations
        if e.name == "core_ingredient_hit_rate" and e.value is not None
    ]
    return Evaluation(
        name="avg_core_ingredient_hit_rate",
        value=statistics.mean(values) if values else None,
        comment=f"{len(values)}개 케이스 집계",
    )


def _aggregate_retry_rate(*, item_results, **_kwargs):
    values = [
        e.value for r in item_results for e in r.evaluations if e.name == "retry_triggered"
    ]
    return Evaluation(name="retry_rate", value=statistics.mean(values) if values else None)


def _aggregate_zero_candidate_rate(*, item_results, **_kwargs):
    values = [
        e.value for r in item_results for e in r.evaluations if e.name == "zero_candidates"
    ]
    return Evaluation(
        name="zero_candidate_rate", value=statistics.mean(values) if values else None
    )


def main() -> None:
    init_langfuse()
    from langfuse import get_client

    client = get_client()

    resolved_cases = [_resolve_case(case) for case in GOLDEN_CASES]
    all_ids = sorted({i for case in resolved_cases for i in case["ingredient_ids"]})
    name_to_id = {
        name: ingredient_id
        for case in resolved_cases
        for name, ingredient_id in zip(case["ingredient_names"], case["ingredient_ids"])
    }

    print(f"[1/4] 코퍼스 통계 계산 중... (재료 {len(all_ids)}종)")
    total_recipes = get_total_recipe_count()
    df = get_ingredient_document_frequency(all_ids)
    for case in resolved_cases:
        ratios = [
            f"{name}={df[i]}/{total_recipes}({df[i] / total_recipes:.1%})"
            for name, i in zip(case["ingredient_names"], case["ingredient_ids"])
        ]
        print(f"  {case['case_id']}: {', '.join(ratios)}")

    print(f"\n[2/4] Langfuse Dataset '{DATASET_NAME}' 등록 중...")
    try:
        client.create_dataset(
            name=DATASET_NAME,
            description="추천 품질 평가 골든셋 v1 - scripts/eval/golden_set.py 참조",
        )
    except Exception as exc:  # noqa: BLE001 - 이미 존재하면 그냥 진행
        print(f"  (데이터셋 이미 존재하거나 생성 스킵: {exc})")

    for case in resolved_cases:
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=f"case-{case['case_id']}",
            input={
                "ingredient_names": case["ingredient_names"],
                "ingredient_ids": case["ingredient_ids"],
            },
            metadata={"notes": case["notes"], "df_ratios": {
                name: df[i] / total_recipes
                for name, i in zip(case["ingredient_names"], case["ingredient_ids"])
            }},
        )
    print(f"  {len(resolved_cases)}개 케이스 등록 완료")

    print("\n[3/4] 실행 (run_agent, 현재 알고리즘 그대로) 중...")
    dataset = client.get_dataset(DATASET_NAME)
    run_name = f"{RUN_LABEL}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
    result = client.run_experiment(
        name="recommend-quality-baseline",
        run_name=run_name,
        description=RUN_DESCRIPTION,
        data=dataset.items,
        task=_build_task(name_to_id, df, total_recipes),
        evaluators=[
            _zero_candidates,
            _retry_triggered,
            _low_confidence_fallback,
            _core_ingredient_hit_rate,
            _avg_recipe_size_top,
        ],
        run_evaluators=[
            _aggregate_core_hit_rate,
            _aggregate_retry_rate,
            _aggregate_zero_candidate_rate,
        ],
        max_concurrency=4,
        metadata={"phase": RUN_LABEL, "algorithm_version": ALGORITHM_VERSION},
    )

    print(f"\n[4/4] 완료. Dataset run URL:\n  {result.dataset_run_url}\n")
    print("=== Run-level aggregate ===")
    for ev in result.run_evaluations:
        print(f"  {ev.name}: {ev.value} ({ev.comment or ''})")

    print("\n=== Item-level summary ===")
    for r in result.item_results:
        by_name = {e.name: e.value for e in r.evaluations}
        print(f"  {r.item.id}: {by_name}")

    client.flush()


if __name__ == "__main__":
    main()

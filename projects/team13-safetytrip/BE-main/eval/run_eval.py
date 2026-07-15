"""
평가셋 30건으로 게이트(escalate 판단) precision/recall 측정.
전체 답변 생성(스트리밍)까지 가지 않고, parse -> stats/retrieve -> gate까지만
실행해서 "답변 가능 vs 에스컬레이션" 판단만 검증함 (빠르고 비용도 적음).

실행: python eval/run_eval.py
결과: eval/eval_results.json에 상세 결과 저장 + 터미널에 요약 출력
"""
import sys
import os
import json
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.graph.build_graph import build_graph

TEST_CASES_PATH = "eval/test_cases.json"
RESULTS_PATH = "eval/eval_results.json"

# escalate를 positive class로 둠 (기획서 "에스컬레이션 판단 precision/recall" 기준)
POSITIVE_LABEL = "escalate"


def classify_actual(result_state: dict) -> str:
    """그래프 실행 결과를 answer/escalate/reask 셋 중 하나로 분류"""
    intent = result_state.get("intent")

    is_unrecoverable = (
        result_state.get("parse_failed")
        or (intent == "prevention" and not result_state.get("region_sido"))
        or intent not in ("prevention", "reactive")
    )
    if is_unrecoverable:
        return "reask"

    if result_state.get("should_escalate"):
        return "escalate"

    return "answer"


def run_eval():
    with open(TEST_CASES_PATH, "r", encoding="utf-8") as f:
        test_cases = json.load(f)

    graph = build_graph()
    results = []

    print(f"총 {len(test_cases)}건 평가 시작...\n")

    for case in test_cases:
        print(f"[{case['id']:2d}] {case['query'][:50]}...")
        try:
            result_state = graph.invoke({"user_query": case["query"]})
            actual = classify_actual(result_state)
        except Exception as e:
            actual = "error"
            print(f"     [ERROR] {e}")

        record = {
            **case,
            "actual_result": actual,
            "match": actual == case["expected_result"],
        }
        results.append(record)
        print(f"     예상: {case['expected_result']:10s} | 실제: {actual:10s} | {'✅' if record['match'] else '❌'}")

        time.sleep(0.3)  # API 과호출 방지

    # ---- 지표 계산 (escalate = positive) ----
    tp = fp = fn = tn = 0
    reask_count = 0
    error_count = 0

    for r in results:
        expected = r["expected_result"]
        actual = r["actual_result"]

        if actual == "reask":
            reask_count += 1
            continue
        if actual == "error":
            error_count += 1
            continue

        if expected == POSITIVE_LABEL and actual == POSITIVE_LABEL:
            tp += 1
        elif expected != POSITIVE_LABEL and actual == POSITIVE_LABEL:
            fp += 1
        elif expected == POSITIVE_LABEL and actual != POSITIVE_LABEL:
            fn += 1
        else:
            tn += 1

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    accuracy = sum(1 for r in results if r["match"]) / len(results)

    print("\n" + "=" * 60)
    print("=== 최종 결과 ===")
    print("=" * 60)
    print(f"전체 정확도(accuracy): {accuracy:.1%} ({sum(1 for r in results if r['match'])}/{len(results)})")
    print("\n[에스컬레이션 판단 기준 - escalate가 positive]")
    print(f"  TP={tp}  FP={fp}  FN={fn}  TN={tn}")
    print(f"  Precision: {precision:.1%}  (에스컬레이션했다고 한 것 중 진짜 맞은 비율)")
    print(f"  Recall:    {recall:.1%}  (진짜 에스컬레이션해야 했던 것 중 맞게 잡아낸 비율)")
    print(f"  F1:        {f1:.1%}")
    print(f"\n[별도 집계] reask(파싱실패)로 빠진 케이스: {reask_count}건 / 에러: {error_count}건")

    # B그룹 subtype별 breakdown
    print("\n[B그룹 subtype별 실패 케이스]")
    for r in results:
        if r["group"] == "B" and not r["match"]:
            print(f"  #{r['id']} ({r['subtype']}): {r['query'][:40]}... -> 실제={r['actual_result']}")

    print("\n[A그룹 실패 케이스]")
    for r in results:
        if r["group"] == "A" and not r["match"]:
            print(f"  #{r['id']} ({r['expected_disaster_type']}): {r['query'][:40]}... -> 실제={r['actual_result']}")

    # 저장
    os.makedirs("eval", exist_ok=True)
    summary = {
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "confusion_matrix": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "reask_count": reask_count,
        "error_count": error_count,
        "results": results,
    }
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n상세 결과 저장됨: {RESULTS_PATH}")


if __name__ == "__main__":
    run_eval()
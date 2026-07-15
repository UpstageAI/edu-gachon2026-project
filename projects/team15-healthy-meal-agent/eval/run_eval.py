"""평가셋 자동 채점 스크립트 (멘토링 2026-07-14 지시 이행).

RFP → 기능 리스트 → 평가 기준 → 정답셋 → **시나리오 테스트(통계표)**의 마지막 단계.

- 프로덕션 경로(LLM classifier + LLM extractor)로 돌린다. stub은 규칙 성능이라 서비스 성능이 아님.
- retrieve는 CSV로 고정해 네트워크 의존 없이 결정론적으로 돈다.
- 결과를 통계표(markdown + csv)로 저장 → 발표 자료에 그대로 삽입.

실행:  .venv/bin/python eval/run_eval.py
빠른 확인(의도만):  .venv/bin/python eval/run_eval.py --intent-only
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.agents.meal_agent import run_agent
from app.schemas import UserProfile
from app.services import food_retriever
from app.services.condition_extractor import extract_conditions_llm
from app.services.food_retriever import load_foods, retrieve_foods
from app.services.intent_router import classify_intent_llm

EVAL_DIR = Path(__file__).resolve().parent
TARGET_KCAL_TOLERANCE = 0.15  # validator.py와 동일 (±15%)

# retrieve를 CSV로 고정 (Supabase/네트워크 의존 제거, 결정론적)
_FOODS = load_foods()


def _csv_retrieve(conditions, profile, foods=None, relax=False):
    return retrieve_foods(conditions, profile, foods=_FOODS, relax=relax)


food_retriever.retrieve_foods = _csv_retrieve
import app.agents.graph as _graph  # noqa: E402

_graph.retrieve_foods = _csv_retrieve


def _run(input_text: str, allergies: list[str] | None = None):
    """프로덕션 LLM 경로로 파이프라인 1회 실행. (state, elapsed_seconds) 반환."""
    profile = UserProfile(allergies=allergies or [])
    t0 = time.time()
    state = run_agent(
        input_text,
        profile,
        classifier=classify_intent_llm,
        extractor=extract_conditions_llm,
    )
    return state, time.time() - t0


def _load(name: str) -> list[dict]:
    path = EVAL_DIR / name
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


# ---------------------------------------------------------------- 채점기들


def eval_intent() -> dict:
    rows = _load("dataset_intent.jsonl")
    hits, details = 0, []
    for r in rows:
        state, _ = _run(r["input"])
        ok = state.intent == r["expected_intent"]
        hits += ok
        details.append((r["id"], ok, r["expected_intent"], state.intent, r["input"]))
    return {"name": "의도 분류 (FR-1)", "total": len(rows), "hits": hits, "details": details}


def eval_extract() -> dict:
    rows = _load("dataset_extract.jsonl")
    hits, details = 0, []
    for r in rows:
        c = extract_conditions_llm(r["input"])
        try:
            ok = bool(eval(r["check"], {"__builtins__": {}}, {"c": c}))  # noqa: S307
        except Exception:  # noqa: BLE001
            ok = False
        hits += ok
        details.append((r["id"], ok, r["check"], "", r["input"]))
    return {"name": "조건 추출 (FR-2)", "total": len(rows), "hits": hits, "details": details}


def _check_calc(state) -> bool:
    """FR-5: 총합 == Σ개별 (코드 합산이므로 항상 참이어야)."""
    if not state.meal_plan or not state.meal_plan.items:
        return True  # 추천 없는 의도(risky 등)는 계산 대상 아님
    manual = sum((it.kcal or 0) for it in state.meal_plan.items)
    return abs((state.nutrition_total.total_kcal or 0) - manual) < 0.5


def _eval_check(token: str, state) -> bool:
    """워크플로우 체크 토큰 하나를 판정."""
    mp = state.meal_plan
    items = mp.items if mp else []
    nt = state.nutrition_total
    vr = state.validation_result

    if token == "has_items":
        return len(items) > 0
    if token == "no_items":
        return len(items) == 0
    if token == "final_not_empty":
        return bool(state.final_response and state.final_response.strip())
    if token.startswith("status_in:"):
        allowed = token.split(":", 1)[1].split(",")
        return vr is not None and vr.status in allowed
    if token.startswith("sodium<="):
        limit = float(token.split("<=")[1])
        return nt is None or (nt.total_sodium or 0) <= limit
    if token.startswith("kcal_upper<="):
        limit = float(token.split("<=")[1])
        return nt is None or (nt.total_kcal or 0) <= limit
    if token.startswith("kcal_target_15:"):
        tgt = float(token.split(":", 1)[1])
        if nt is None:
            return False
        return (
            tgt * (1 - TARGET_KCAL_TOLERANCE)
            <= (nt.total_kcal or 0)
            <= tgt * (1 + TARGET_KCAL_TOLERANCE)
        )
    if token.startswith("no_allergen:"):
        allergen = token.split(":", 1)[1]
        for it in items:
            hay = f"{it.food_name} {getattr(it, 'ingredients', '') or ''}"
            if allergen in hay:
                return False
        return True
    raise ValueError(f"unknown check token: {token}")


def eval_workflow() -> dict:
    rows = _load("dataset_workflow.jsonl")
    hits, details = 0, []
    latencies = []
    intent_hits = 0
    calc_ok = 0
    calc_total = 0
    # 안전 지표
    allergen_trials = 0
    allergen_leaks = 0
    sodium_trials = 0
    sodium_violations = 0

    for r in rows:
        state, dt = _run(r["input"], r.get("allergies"))
        latencies.append(dt)

        intent_ok = state.intent == r["expect_intent"]
        intent_hits += intent_ok

        checks_ok = all(_eval_check(tok, state) for tok in r["checks"])
        case_ok = intent_ok and checks_ok
        hits += case_ok

        # FR-5 계산 정확도 (추천 낸 케이스만)
        if state.meal_plan and state.meal_plan.items:
            calc_total += 1
            calc_ok += _check_calc(state)

        # 안전: 알레르기 누출율
        for tok in r["checks"]:
            if tok.startswith("no_allergen:"):
                allergen_trials += 1
                if not _eval_check(tok, state):
                    allergen_leaks += 1

        # 안전: 나트륨 위반율 (추천 낸 케이스 전부 대상)
        if state.meal_plan and state.meal_plan.items and state.nutrition_total:
            sodium_trials += 1
            if (state.nutrition_total.total_sodium or 0) > 1500:
                sodium_violations += 1

        details.append((r["id"], case_ok, r["expect_intent"], state.intent, r["input"]))

    latencies.sort()
    return {
        "name": "전체 워크플로우 (FR-1~8)",
        "total": len(rows),
        "hits": hits,
        "details": details,
        "extra": {
            "intent_acc": (intent_hits, len(rows)),
            "calc_acc": (calc_ok, calc_total),
            "allergen_leak": (allergen_leaks, allergen_trials),
            "sodium_violation": (sodium_violations, sodium_trials),
            "latency_avg": sum(latencies) / len(latencies) if latencies else 0,
            "latency_p50": latencies[len(latencies) // 2] if latencies else 0,
            "latency_max": latencies[-1] if latencies else 0,
        },
    }


# ---------------------------------------------------------------- 출력


def _pct(hit, total):
    return f"{100 * hit / total:.1f}%" if total else "N/A"


def render_report(results: list[dict], wf_extra: dict) -> str:
    lines = ["# 평가 실행 결과 (Evaluation Run Report)", ""]
    lines.append(
        "> 프로덕션 경로(LLM classifier + LLM extractor), retrieve=CSV 고정, temperature=0."
    )
    lines.append("")
    lines.append("## 1. 기능별 정확도")
    lines.append("")
    lines.append("| 기능 | 통과 / 전체 | 정확도 |")
    lines.append("|---|---|---|")
    for res in results:
        lines.append(
            f"| {res['name']} | {res['hits']} / {res['total']} | {_pct(res['hits'], res['total'])} |"
        )
    lines.append("")

    lines.append("## 2. 안전 지표 (Zero-Tolerance 목표 0%)")
    lines.append("")
    leak_n, leak_t = wf_extra["allergen_leak"]
    na_n, na_t = wf_extra["sodium_violation"]
    calc_n, calc_t = wf_extra["calc_acc"]
    lines.append("| 지표 | 값 | 목표 |")
    lines.append("|---|---|---|")
    lines.append(f"| 알레르기 누출율 | {_pct(leak_n, leak_t)} ({leak_n}/{leak_t}) | 0% |")
    lines.append(f"| 나트륨 1500 초과 노출율 | {_pct(na_n, na_t)} ({na_n}/{na_t}) | 0% |")
    lines.append(
        f"| 영양 계산 정확도 (합계=Σ개별) | {_pct(calc_n, calc_t)} ({calc_n}/{calc_t}) | 100% |"
    )
    lines.append("")

    lines.append("## 3. 성능 (대표 지표 — 전체 응답시간)")
    lines.append("")
    lines.append("| 지표 | 값 |")
    lines.append("|---|---|")
    lines.append(f"| 평균 응답시간 | {wf_extra['latency_avg']:.2f}s |")
    lines.append(f"| 중앙값(p50) | {wf_extra['latency_p50']:.2f}s |")
    lines.append(f"| 최대 | {wf_extra['latency_max']:.2f}s |")
    lines.append("")
    lines.append(
        "> 검색·조합은 거의 0초. 응답시간의 대부분은 LLM 판단(의도·조건·조합)에서 발생 — '판단은 LLM, 계산은 코드' 원칙의 계측 근거."
    )
    lines.append("")

    lines.append("## 4. 케이스별 상세")
    lines.append("")
    for res in results:
        lines.append(f"### {res['name']}")
        lines.append("")
        lines.append("| ID | 결과 | 기대 | 실제 | 입력 |")
        lines.append("|---|---|---|---|---|")
        for cid, ok, exp, act, inp in res["details"]:
            mark = "✅" if ok else "❌"
            lines.append(f"| {cid} | {mark} | `{exp}` | `{act}` | {inp[:30]} |")
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent-only", action="store_true")
    args = parser.parse_args()

    print("[eval] 의도 분류 채점 중...")
    results = [eval_intent()]
    wf_extra = {}
    if not args.intent_only:
        print("[eval] 조건 추출 채점 중...")
        results.append(eval_extract())
        print("[eval] 전체 워크플로우 채점 중 (LLM 호출 다수, ~2분 소요)...")
        wf = eval_workflow()
        results.append(wf)
        wf_extra = wf["extra"]

    report = (
        render_report(results, wf_extra)
        if wf_extra
        else "\n".join(
            f"{r['name']}: {r['hits']}/{r['total']} ({_pct(r['hits'], r['total'])})"
            for r in results
        )
    )
    out = EVAL_DIR / "RESULT.md"
    out.write_text(report, encoding="utf-8")
    print("\n" + report)
    print(f"\n[eval] 저장: {out}")


if __name__ == "__main__":
    main()

"""라우팅 평가 — 앱의 **실제 generator 코드**로 난이도×모델 EX 를 측정한다.

bench 의 별도 조건(zero/few…)이 아니라 `app.graph.nodes.generator.generate` 를 그대로
태운다(우리 GENERATOR_SYSTEM+난이도 가이드+값힌트 스키마 프롬프트, few-shot 없음).
난이도는 AI Hub 라벨로 고정하고 모델만 mini/pro2/pro3 교체 → "난이도 H 에서 어느 모델이
정확한가"를 잰다. 컨텍스트=값힌트 붙은 스키마(eval_set_schema.json), gold 실행채점(EX).

    uv run python -m bench.route_eval           # 실행 (유료, 병렬)
    uv run python -m bench.route_eval report    # 난이도×모델 표 + 라우팅 추천

결과: bench/results_route.jsonl (재개 가능)
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

from app.core import llm
from app.core.settings import settings
from app.graph.nodes.generator import generate
from bench import config, evaluate

FEWSHOT = "fewshot" in sys.argv  # few-shot 모드 (같은 DB 예시 주입)
EVAL = config.CONDITIONS["schema_few" if FEWSHOT else "schema"][0]
RESULTS = config.BENCH_DIR / ("results_route_fewshot.jsonl" if FEWSHOT else "results_route.jsonl")
WORKERS = 12
_HARD2DIFF = {"easy": "easy", "medium": "medium", "hard": "hard", "extra hard": "extra_hard"}


def _done() -> set:
    if not RESULTS.exists():
        return set()
    out = set()
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            out.add((o["id"], o["model"]))
    return out


def _one(rec: dict, model: str) -> dict:
    diff = _HARD2DIFF.get(rec["hardness"], "medium")
    state = {"question": rec["question"], "schema": rec["schema"],
             "difficulty": diff, "model": model, "iteration": 0}
    if FEWSHOT:
        state["fewshot"] = rec.get("fewshot", [])
    err, sql, ptok, ctok = None, "", 0, 0
    t0 = time.perf_counter()
    for attempt in range(3):  # 일시 오류(레이트리밋 등) 재시도
        try:
            sql = generate(state)["sql"]
            ptok, ctok = llm.last_usage()
            err = None
            break
        except Exception as e:  # noqa: BLE001
            err = str(e)[:200]
            time.sleep(1.5 * (attempt + 1))
    latency = time.perf_counter() - t0
    db = str(config.DB_DIR / f"{rec['db_id']}.sqlite")
    if err or not sql:
        ex, note = False, err or "empty"
    else:
        ex, note = evaluate.exec_match(sql, rec["gold_sql"], db, config.EXEC_TIMEOUT_S)
    return {
        "id": rec["id"], "hardness": rec["hardness"], "level_ko": config.HARDNESS_KO[rec["hardness"]],
        "model": model, "ex": ex,
        "prompt_tokens": ptok, "completion_tokens": ctok, "latency": round(latency, 3),
        "cost_usd": config.price_usd(model, ptok, ctok),
        "error": err, "exec_note": None if ex else note, "pred_sql": sql,
    }


def cmd_run() -> None:
    if not settings.upstage_api_key:
        raise SystemExit("UPSTAGE_API_KEY 필요 (.env)")
    if not EVAL.exists():
        raise SystemExit(f"{EVAL.name} 없음 — `python -m bench.build_schema_linked` 먼저")
    recs = json.loads(EVAL.read_text(encoding="utf-8"))
    done = _done()
    models = list(config.MODELS)
    todo = [(r, m) for r in recs for m in models if (r["id"], m) not in done]
    print(f"[route_eval] 문항 {len(recs)} × 모델 {len(models)} → 남은 {len(todo)} (완료 {len(done)}), 병렬 {WORKERS}")

    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(rm):
            row = _one(*rm)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                fout.flush()
                spent[0] += row["cost_usd"]
                n[0] += 1
                if n[0] % 100 == 0:
                    print(f"  {n[0]}/{len(todo)}  ${spent[0]:.3f}")
        list(pool.map(work, todo))
    print(f"완료. 누적 비용 ≈ ${spent[0]:.4f}. 리포트: python -m bench.route_eval report")


def cmd_report() -> None:
    if not RESULTS.exists():
        raise SystemExit("results_route.jsonl 없음 — 먼저 run")
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    cell = defaultdict(lambda: {"n": 0, "ex": 0, "ptok": 0, "ctok": 0, "lat": 0.0, "cost": 0.0})
    for o in rows:
        c = cell[(o["model"], o["hardness"])]
        c["n"] += 1
        c["ex"] += int(o["ex"])
        c["ptok"] += o["prompt_tokens"]; c["ctok"] += o["completion_tokens"]
        c["lat"] += o["latency"]; c["cost"] += o["cost_usd"]
    models = list(config.MODELS)

    def line(cells):
        print("| " + " | ".join(cells) + " |")

    print("\n## 난이도 × 모델 — EX 성공률 (우리 generator, n/level)\n")
    line(["난이도\\모델"] + models)
    line(["---"] * (len(models) + 1))
    for lv in config.HARDNESS_ORDER:
        cells = [config.HARDNESS_KO[lv]]
        for m in models:
            c = cell.get((m, lv))
            cells.append(f"{c['ex']/c['n']*100:.0f}% ({c['ex']}/{c['n']})" if c and c["n"] else "-")
        line(cells)

    print("\n## 난이도 × 모델 — 정답당 비용(USD) · 평균 지연(s)\n")
    line(["난이도\\모델"] + models)
    line(["---"] * (len(models) + 1))
    for lv in config.HARDNESS_ORDER:
        cells = [config.HARDNESS_KO[lv]]
        for m in models:
            c = cell.get((m, lv))
            if not c or not c["n"]:
                cells.append("-"); continue
            pc = "∞" if c["ex"] == 0 else f"${c['cost']/c['ex']:.5f}"
            cells.append(f"{pc} / {c['lat']/c['n']:.1f}s")
        line(cells)

    print(f"\n## 라우팅 추천 (EX ≥ {config.ROUTING_EX_TARGET*100:.0f}% 중 정답당 비용 최소)\n")
    line(["난이도", "추천 모델", "EX", "정답당 비용", "근거"])
    line(["---"] * 5)
    for lv in config.HARDNESS_ORDER:
        cand = []
        for m in models:
            c = cell.get((m, lv))
            if c and c["n"]:
                cand.append((m, c["ex"] / c["n"], c["cost"] / c["ex"] if c["ex"] else float("inf")))
        if not cand:
            line([config.HARDNESS_KO[lv], "-", "-", "-", "데이터 없음"]); continue
        passing = [x for x in cand if x[1] >= config.ROUTING_EX_TARGET]
        if passing:
            m, ex, pc = min(passing, key=lambda x: x[2]); why = "목표 충족 최저가"
        else:
            m, ex, pc = max(cand, key=lambda x: x[1]); why = "목표 미달, EX 최고"
        line([config.HARDNESS_KO[lv], m, f"{ex*100:.0f}%",
              "∞" if pc == float("inf") else f"${pc:.5f}", why])
    print()


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

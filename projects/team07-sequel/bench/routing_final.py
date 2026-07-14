"""확정 파이프라인 위 라우팅 그리드 — 난이도별 (모델 × few-shot) 최적 배정 찾기.

확정 파이프라인 = normalize on + 확정(exact/synonym) 힌트만 주입 + 소형 bypass
+ 실행수리(2회) + gen_decompose off. korean_final n1최종과 동일 조건.

셀: 3×3 그리드 (mini/pro2/pro3 × k0/k3/k8) — CELLS 는 8셀 실측 + pro2|k3 은
results_korean_final 의 n1 재사용으로 합류. 답할 질문:
  ① 난이도별 최적 모델 (mini/pro2/pro3 — 신파이프라인에서 재검증)
  ② few-shot 을 하(easy)에도 줘야 하나 — 난이도별 k0→k3(→k8) 효과
  ③ 최상 KPI 70%: pro2|k8 / pro3|k8 로 달성?

결과 raw: results_routing_final.jsonl (cell 필드). 재개 가능.
실행: uv run python -m bench.routing_final [report]
"""
from __future__ import annotations

import os

os.environ.setdefault("GEN_DECOMPOSE", "false")

import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from threading import Lock  # noqa: E402

from app.core import db, llm  # noqa: E402
from app.graph.nodes.generator import generate  # noqa: E402
from app.graph.nodes.query_normalizer import normalize  # noqa: E402
from app.graph.nodes.schema_linker import schema_link  # noqa: E402
from bench import config, evaluate  # noqa: E402
from bench.korean_final import _H2D, _official, _sqlite  # noqa: E402

RESULTS = config.BENCH_DIR / "results_routing_final.jsonl"
WORKERS = int(os.getenv("RF_WORKERS", "6"))
REPAIRS = 2
CELLS = [("solar-mini", 0), ("solar-mini", 3), ("solar-mini", 8), ("solar-pro2", 0),
         ("solar-pro2", 8), ("solar-pro3", 0), ("solar-pro3", 3), ("solar-pro3", 8)]
# pro2|k3 셀은 results_korean_final.jsonl 의 cond=n1 을 report 에서 합류
# pro3|k0 추가(3×3 그리드 완성): pro3 가 few-shot 없이도 pro2 를 넘는지 확인용

_K3 = {r["id"]: r for r in json.loads((config.BENCH_DIR / "eval_set_fewshot_k3.json").read_text(encoding="utf-8"))}
_K8 = {r["id"]: r for r in json.loads((config.BENCH_DIR / "eval_set_fewshot_k8.json").read_text(encoding="utf-8"))}

N_PER_LEVEL = int(os.getenv("RF_N", "100"))  # 난이도별 표본 (400/셀 — 라우팅 판단엔 충분, 전수의 1/3)
SEED = 7


def _sample() -> list[dict]:
    """난이도별 N 층화 표본 (seed 고정 → 셀 간·재실행 간 동일 문항)."""
    by = defaultdict(list)
    for r in _K3.values():
        by[r["hardness"]].append(r)
    rng = random.Random(SEED)
    out = []
    for lv in config.HARDNESS_ORDER:
        pool = sorted(by[lv], key=lambda r: r["id"])  # dict 순서 의존 제거
        out.extend(rng.sample(pool, min(N_PER_LEVEL, len(pool))))
    return out


def _fewshot(rid: str, k: int) -> list[dict]:
    if k == 0:
        return []
    src = _K8 if k == 8 else _K3
    return (src.get(rid) or {}).get("fewshot", [])[:k]


def run_one(rec, model: str, k: int) -> dict:
    cell = f"{model.split('-')[1]}|k{k}"
    dbp = _sqlite(rec["db_id"])
    db.set_target(dbp)
    err, sql, pt, ct, n_rep = None, "", 0, 0, 0
    t0 = time.perf_counter()
    try:
        norm = normalize({"question": rec["question"]})  # 확정 config: normalize on
        p, c = llm.last_usage(); pt += p; ct += c
        linked = schema_link({"question": rec["question"], **norm})
        state = {"question": rec["question"], "schema": linked["schema"], "tables": linked["tables"],
                 "difficulty": _H2D.get(rec["hardness"], "medium"), "model": model,
                 "fewshot": _fewshot(rec["id"], k), "iteration": 0}
        sql = generate(state)["sql"]
        p, c = llm.last_usage(); pt += p; ct += c
        for _ in range(REPAIRS):
            _, run_err = evaluate._run(sql, dbp, config.EXEC_TIMEOUT_S)
            if run_err is None:
                break
            n_rep += 1
            state["exec_error"], state["sql"] = run_err[:300], sql
            sql = generate(state)["sql"]
            p, c = llm.last_usage(); pt += p; ct += c
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    latency = time.perf_counter() - t0
    db.set_target(None)

    if err or not sql:
        ex, off = False, 0
    else:
        ex, _ = evaluate.exec_match(sql, rec["gold_sql"], dbp, config.EXEC_TIMEOUT_S)
        off = _official(sql, rec["gold_sql"], dbp)
    return {"id": rec["id"], "cell": cell, "hardness": rec["hardness"], "ex": ex,
            "ex_official": off, "repairs": n_rep, "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": config.price_usd(model, pt, ct), "latency": round(latency, 3),
            "pred_sql": sql, "error": err}


def cmd_run() -> None:
    recs = _sample()
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                if not o.get("error"):
                    done.add((o["id"], o["cell"]))
    tasks = [(r, m, k) for m, k in CELLS for r in recs
             if (r["id"], f"{m.split('-')[1]}|k{k}") not in done]
    print(f"[routing_final] 셀 {len(CELLS)} × {len(recs)}문항 · 남은 {len(tasks)} · 병렬 {WORKERS}")
    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(t):
            row = run_one(*t)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                spent[0] += row["cost_usd"]; n[0] += 1
                if n[0] % 200 == 0:
                    print(f"  {n[0]}/{len(tasks)}  ${spent[0]:.3f}")
        list(pool.map(work, tasks))
    print(f"완료. ≈ ${spent[0]:.4f}. 리포트: python -m bench.routing_final report")


def _load_cells() -> dict:
    """신규 4셀 + pro2|k3(korean_final n1) 합류. {(cell, hardness): rows}"""
    latest: dict = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if not o.get("error"):
                latest[(o["id"], o["cell"])] = o
    kf = config.BENCH_DIR / "results_korean_final.jsonl"
    if kf.exists():
        for line in kf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                if o["cond"] == "n1" and not o.get("error"):
                    o["cell"] = "pro2|k3"
                    latest[(o["id"], "pro2|k3")] = o
    return latest


def cmd_report() -> None:
    sample_ids = {r["id"] for r in _sample()}
    latest = {k: o for k, o in _load_cells().items() if o["id"] in sample_ids}
    cells = ["mini|k0", "mini|k3", "mini|k8", "pro2|k0", "pro2|k3", "pro2|k8", "pro3|k0", "pro3|k3", "pro3|k8"]
    agg = defaultdict(lambda: {"n": 0, "ex": 0, "off": 0, "cost": 0.0})
    for o in latest.values():
        a = agg[(o["cell"], o["hardness"])]
        a["n"] += 1; a["ex"] += int(o["ex"]); a["off"] += int(o["ex_official"] or 0)
        a["cost"] += o["cost_usd"]
    print("\n## 라우팅 그리드 (확정 파이프라인, 공식 EX%) — 난이도 × (모델|few-shot)\n")
    print("| 난이도 | " + " | ".join(cells) + " |")
    print("|---" * (len(cells) + 1) + "|")
    best = {}
    for lv in config.HARDNESS_ORDER:
        row = [config.HARDNESS_KO[lv]]
        for cell in cells:
            a = agg.get((cell, lv))
            if a and a["n"]:
                off = a["off"] / a["n"] * 100
                row.append(f"{off:.0f}% ({a['n']})")
                # 최적: 공식 EX 최대, 동률(1%p 이내)이면 정답당 비용 낮은 쪽
                cpc = a["cost"] / a["off"] if a["off"] else float("inf")
                cur = best.get(lv)
                if not cur or off > cur[1] + 1 or (abs(off - cur[1]) <= 1 and cpc < cur[2]):
                    best[lv] = (cell, off, cpc)
            else:
                row.append("-")
        print("| " + " | ".join(row) + " |")
    print("\n**추천 라우팅** (공식 EX 최대, ±1%p 동률 시 정답당 비용):")
    for lv in config.HARDNESS_ORDER:
        if lv in best:
            c, off, cpc = best[lv]
            print(f"  {config.HARDNESS_KO[lv]}: **{c}** ({off:.0f}%, ${cpc:.5f}/정답)")
    err = sum(1 for line in RESULTS.read_text(encoding="utf-8").splitlines()
              if line.strip() and json.loads(line).get("error"))
    print(f"\n(신규 셀 에러행 {err} · 총 비용 ${sum(o['cost_usd'] for o in latest.values()):.4f})")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

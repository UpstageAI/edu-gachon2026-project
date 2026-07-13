"""한국어 AI Hub 최종 평가 — 교체된 신파이프라인으로 normalize on/off ablation.

신파이프라인 = 소형 스키마 bypass(전체 DDL) + 컬럼개념 값필터 + 실행피드백 수리(최대 2회)
+ few-shot(레코드 내장 k3) + pro2 고정 + gen_decompose off.
측정: ① normalize(한국어 LLM 전처리)의 실제 기여 ② 최상 난이도 KPI(70%) 달성 여부.

조건 2개: n1(실제 normalize 노드) / n0(원문 그대로, keyword 없음)
채점: 기존 한국어 수치와 비교 가능하도록 우리 exec_match (참고로 공식 set 방식도 병기).

결과 raw: results_korean_final.jsonl. 재개 가능.
실행: uv run python -m bench.korean_final [report]
"""
from __future__ import annotations

import os

os.environ.setdefault("GEN_DECOMPOSE", "false")

import json  # noqa: E402
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

EVAL = config.BENCH_DIR / "eval_set_fewshot_k3.json"
RESULTS = config.BENCH_DIR / "results_korean_final.jsonl"
MODEL = "solar-pro2"
WORKERS = int(os.getenv("KF_WORKERS", "3"))
REPAIRS = 2  # 제품 agent_max_retries 와 동일
_H2D = {"easy": "easy", "medium": "medium", "hard": "hard", "extra hard": "extra_hard"}


def _sqlite(db_id: str) -> str:
    return str(config.DB_DIR / f"{db_id}.sqlite")


def _official(pred: str, gold: str, db_path: str) -> int | None:
    p, _ = evaluate._run(pred, db_path, config.EXEC_TIMEOUT_S)
    g, gerr = evaluate._run(gold, db_path, config.EXEC_TIMEOUT_S)
    if gerr is not None:
        return None
    return 1 if (p is not None and set(p) == set(g)) else 0


def run_one(rec, cond: str) -> dict:
    dbp = _sqlite(rec["db_id"])
    db.set_target(dbp)
    err, sql, pt, ct, n_rep = None, "", 0, 0, 0
    t0 = time.perf_counter()
    try:
        if cond == "n1":
            norm = normalize({"question": rec["question"]})
            p, c = llm.last_usage(); pt += p; ct += c
        else:
            norm = {"normalized_question": rec["question"], "keywords": [], "time_range": {}}
        linked = schema_link({"question": rec["question"], **norm})
        state = {"question": rec["question"], "schema": linked["schema"], "tables": linked["tables"],
                 "difficulty": _H2D.get(rec["hardness"], "medium"), "model": MODEL,
                 "fewshot": rec.get("fewshot", []), "iteration": 0}
        sql = generate(state)["sql"]
        p, c = llm.last_usage(); pt += p; ct += c
        # 실행 피드백 수리 (제품과 동일: 런타임 오류만, 빈 결과는 정당)
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
        ex, note, off = False, err or "empty", 0
    else:
        ex, note = evaluate.exec_match(sql, rec["gold_sql"], dbp, config.EXEC_TIMEOUT_S)
        off = _official(sql, rec["gold_sql"], dbp)
    return {"id": rec["id"], "cond": cond, "hardness": rec["hardness"], "ex": ex,
            "ex_official": off, "repairs": n_rep, "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": config.price_usd(MODEL, pt, ct), "latency": round(latency, 3),
            "pred_sql": sql, "error": err, "exec_note": None if ex else note}


def cmd_run() -> None:
    recs = json.loads(EVAL.read_text(encoding="utf-8"))
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                if not o.get("error"):
                    done.add((o["id"], o["cond"]))
    tasks = [(r, c) for r in recs for c in ("n0", "n1") if (r["id"], c) not in done]
    print(f"[korean_final] {len(recs)}문항 × 2조건 · 남은 {len(tasks)} · 병렬 {WORKERS}")
    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(t):
            row = run_one(*t)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                spent[0] += row["cost_usd"]; n[0] += 1
                if n[0] % 100 == 0:
                    print(f"  {n[0]}/{len(tasks)}  ${spent[0]:.3f}")
        list(pool.map(work, tasks))
    print(f"완료. ≈ ${spent[0]:.4f}. 리포트: python -m bench.korean_final report")


def cmd_report() -> None:
    latest = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line); latest[(o["id"], o["cond"])] = o
    vals = list(latest.values())
    agg = defaultdict(lambda: {"n": 0, "ex": 0, "off": 0, "rep": 0})
    for o in vals:
        a = agg[(o["cond"], o["hardness"])]
        a["n"] += 1; a["ex"] += int(o["ex"]); a["off"] += int(o["ex_official"] or 0)
        a["rep"] += o.get("repairs", 0)
    print("\n## 한국어 최종 (신파이프라인, pro2+fewshot3+수리) — EX(우리)/공식\n")
    print("| 난이도 | n0 (normalize off) | n1 (normalize on) |")
    print("|---|---|---|")
    for lv in config.HARDNESS_ORDER:
        cells = [config.HARDNESS_KO[lv]]
        for c in ("n0", "n1"):
            a = agg.get((c, lv))
            cells.append(f"{a['ex']/a['n']*100:.0f}% / {a['off']/a['n']*100:.0f}% ({a['n']})" if a and a["n"] else "-")
        print("| " + " | ".join(cells) + " |")
    for c in ("n0", "n1"):
        rows = [o for o in vals if o["cond"] == c]
        if rows:
            ex = sum(o["ex"] for o in rows); off = sum(int(o["ex_official"] or 0) for o in rows)
            rep = sum(o.get("repairs", 0) for o in rows)
            print(f"{c}: 전체 {ex/len(rows)*100:.1f}% / 공식 {off/len(rows)*100:.1f}% · 수리 발동 {rep}회 · n={len(rows)}")
    err = sum(1 for o in vals if o["error"])
    print(f"에러 {err} · 비용 ${sum(o['cost_usd'] for o in vals):.4f}")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

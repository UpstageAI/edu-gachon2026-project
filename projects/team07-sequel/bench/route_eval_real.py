"""라우팅 평가 (실 linker) — 우리 query_normalizer + schema_link(schema_retriever +
value_retriever) + generator 를 AI Hub sqlite 에서 db_id 별로 **진짜** 실행한다.

정적 근사가 아니라 실제 우리 코드가 각 DB 에 대해:
  set_target(sqlite) → normalize(LLM 키워드/시간) → schema_link(임베딩 top-k+FK+값폴백)
  → 모델별 generate → gold 실행채점(EX).

두 조건:
  base : few-shot K=3 + gen_decompose off (개선 전)
  v2   : few-shot K=8 + gen_decompose on  (개선판: 예시↑·질의분해; 조인힌트는 실 retriever 기본)

    uv run python -m bench.route_eval_real base
    uv run python -m bench.route_eval_real v2
    uv run python -m bench.route_eval_real report base|v2
"""
from __future__ import annotations

import os
import sys

# settings 는 import 시점에 env 를 읽으므로, app 모듈 import 전에 토글을 세팅한다.
_MODE = "v2" if "v2" in sys.argv else "base"
os.environ["GEN_DECOMPOSE"] = "true" if _MODE == "v2" else "false"

import json  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from threading import Lock  # noqa: E402

from app.core import db, llm  # noqa: E402
from app.core.settings import settings  # noqa: E402
from app.graph.nodes.generator import generate  # noqa: E402
from app.graph.nodes.query_normalizer import normalize  # noqa: E402
from app.graph.nodes.schema_linker import schema_link  # noqa: E402
from bench import config, evaluate  # noqa: E402

_SETS = {"base": config.BENCH_DIR / "eval_set_fewshot_k3.json",
         "v2": config.BENCH_DIR / "eval_set_fewshot_k8.json"}
EVAL = _SETS[_MODE]
RESULTS = config.BENCH_DIR / f"results_reallinker_{_MODE}.jsonl"
WORKERS = 4  # 실 linker는 문항당 호출 多(normalize+임베딩x2+생성x3) → 레이트리밋 방어
_HARD2DIFF = {"easy": "easy", "medium": "medium", "hard": "hard", "extra hard": "extra_hard"}
MODELS = list(config.MODELS)


def _sqlite(db_id: str) -> str:
    return str(config.DB_DIR / f"{db_id}.sqlite")


def _row(rec, model, sql, ptok, ctok, latency, ex, note, err):
    return {"id": rec["id"], "hardness": rec["hardness"], "model": model, "ex": ex,
            "prompt_tokens": ptok, "completion_tokens": ctok, "latency": round(latency, 3),
            "cost_usd": config.price_usd(model, ptok, ctok), "error": err,
            "exec_note": None if ex else note, "pred_sql": sql}


def _process(rec) -> list[dict]:
    """한 문항: 실 linker 1회 + 모델별 generate. 3행 반환."""
    db.set_target(_sqlite(rec["db_id"]))
    try:
        norm = normalize({"question": rec["question"]})
        linked = schema_link({"question": rec["question"], **norm})
        schema = linked["schema"]
    except Exception as e:  # noqa: BLE001 — linker 실패 시 전 모델 실패 처리
        db.set_target(None)
        return [_row(rec, m, "", 0, 0, 0.0, False, f"linker: {e}"[:200], f"linker: {e}"[:200]) for m in MODELS]

    diff = _HARD2DIFF.get(rec["hardness"], "medium")
    out = []
    for model in MODELS:
        state = {"question": rec["question"], "normalized_question": norm.get("normalized_question"),
                 "schema": schema, "difficulty": diff, "model": model, "iteration": 0,
                 "fewshot": rec.get("fewshot", [])}
        err, sql, ptok, ctok = None, "", 0, 0
        t0 = time.perf_counter()
        for attempt in range(3):
            try:
                sql = generate(state)["sql"]
                ptok, ctok = llm.last_usage()
                err = None
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
                time.sleep(1.5 * (attempt + 1))
        latency = time.perf_counter() - t0
        if err or not sql:
            ex, note = False, err or "empty"
        else:
            ex, note = evaluate.exec_match(sql, rec["gold_sql"], _sqlite(rec["db_id"]), config.EXEC_TIMEOUT_S)
        out.append(_row(rec, model, sql, ptok, ctok, latency, ex, note, err))
    db.set_target(None)
    return out


def cmd_run() -> None:
    if not settings.upstage_api_key:
        raise SystemExit("UPSTAGE_API_KEY 필요")
    if not EVAL.exists():
        raise SystemExit(f"{EVAL.name} 없음 — few-shot 세트(k3/k8) 먼저 빌드")
    recs = json.loads(EVAL.read_text(encoding="utf-8"))
    done_ids = set()
    if RESULTS.exists():
        cnt = defaultdict(int)
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cnt[json.loads(line)["id"]] += 1
        done_ids = {i for i, n in cnt.items() if n >= len(MODELS)}
    todo = [r for r in recs if r["id"] not in done_ids]
    print(f"[reallinker/{_MODE}] decompose={settings.gen_decompose} | 문항 {len(recs)} 남은 {len(todo)} × {len(MODELS)}모델, 병렬 {WORKERS}")

    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(rec):
            rows = _process(rec)
            with lock:
                for row in rows:
                    fout.write(json.dumps(row, ensure_ascii=False) + "\n")
                    spent[0] += row["cost_usd"]
                fout.flush()
                n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(todo)} 문항  ${spent[0]:.3f}")
        list(pool.map(work, todo))
    print(f"완료. 누적 ≈ ${spent[0]:.4f}. 리포트: python -m bench.route_eval_real report {_MODE}")


def cmd_report() -> None:
    if not RESULTS.exists():
        raise SystemExit(f"{RESULTS.name} 없음")
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    cell = defaultdict(lambda: {"n": 0, "ex": 0, "cost": 0.0})
    for o in rows:
        c = cell[(o["model"], o["hardness"])]
        c["n"] += 1; c["ex"] += int(o["ex"]); c["cost"] += o["cost_usd"]
    print(f"\n## [{_MODE}] 난이도 × 모델 — EX (실 linker, 우리 파이프라인)\n")
    print("| 난이도\\모델 | " + " | ".join(MODELS) + " |")
    print("| --- " * (len(MODELS) + 1) + "|")
    for lv in config.HARDNESS_ORDER:
        cells = [config.HARDNESS_KO[lv]]
        for m in MODELS:
            c = cell.get((m, lv))
            cells.append(f"{c['ex']/c['n']*100:.0f}% ({c['ex']}/{c['n']})" if c and c["n"] else "-")
        print("| " + " | ".join(cells) + " |")
    err = sum(1 for o in rows if o["error"])
    print(f"\n총 {len(rows)}행, 에러 {err}, 비용 ${sum(o['cost_usd'] for o in rows):.4f}")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

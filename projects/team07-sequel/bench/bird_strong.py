"""BIRD 성능 올리기용 강화 config (ablation 아님) — pro3 + evidence + few-shot8 + 공식 채점.

ablation 에서 좋았던 구조(full schema + metadata)에, 일부러 껐던 레버를 다시 켠다:
  - 모델 solar-pro3
  - evidence(질문별 외부지식)를 스키마 컨텍스트에 주입
  - few-shot 8 (dev 풀, self 제외·같은 DB 우선 — 약한 누수 있음, 상한 추정)
  - 채점 = BIRD 공식 방식(set(pred)==set(gold), 원시 튜플)
app/ 파이프라인 미변경. bench.ablation 헬퍼(warm/_metadata_block/_sqlite/DIFF_MAP) 재사용.

결과 raw: bench/results_bird_strong.jsonl. 재개 가능.
실행: uv run python -m bench.bird_strong  |  report
"""
from __future__ import annotations

import os

os.environ.setdefault("GEN_DECOMPOSE", "false")

import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from threading import Lock  # noqa: E402

import numpy as np  # noqa: E402

from app.core import db, llm  # noqa: E402
from app.graph.nodes.generator import generate  # noqa: E402
from app.repositories import schema_repository as sr  # noqa: E402
from bench import config, evaluate  # noqa: E402
from bench.ablation import BIRD, DIFF_MAP, EMB, _metadata_block, _sqlite, warm  # noqa: E402

MODEL = "solar-pro3"
FEWSHOT_K = 8
WORKERS = int(os.getenv("STRONG_WORKERS", "3"))
RESULTS = config.BENCH_DIR / "results_bird_strong.jsonl"

_RECS = json.loads((BIRD / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
for _i, _r in enumerate(_RECS):
    _r["gold_sql"] = _r["SQL"]
    _r["rid"] = str(_i)

# 질문 임베딩(raw, recs 순서) → few-shot 유사도 검색용
_qz = np.load(EMB / "questions.npz")
_RAW = _qz["raw"].astype(float)
_RAWN = _RAW / (np.linalg.norm(_RAW, axis=1, keepdims=True) + 1e-9)


def _fewshot(i: int) -> list[dict]:
    """질문 i 와 유사한 dev 예시 K개(self 제외, 같은 DB 우선)."""
    sims = _RAWN @ _RAWN[i]
    order = np.argsort(-sims)
    same = [j for j in order if j != i and _RECS[j]["db_id"] == _RECS[i]["db_id"]]
    other = [j for j in order if j != i and _RECS[j]["db_id"] != _RECS[i]["db_id"]]
    picks = (same + other)[:FEWSHOT_K]
    return [{"question": _RECS[j]["question"], "sql": _RECS[j]["SQL"]} for j in picks]


def _official_ex(pred: str, gold: str, db_path: str) -> int | None:
    """BIRD 공식: set(pred)==set(gold) 원시 튜플. gold 실패면 None(채점 제외)."""
    p_rows, _ = evaluate._run(pred, db_path, config.EXEC_TIMEOUT_S)
    g_rows, g_err = evaluate._run(gold, db_path, config.EXEC_TIMEOUT_S)
    if g_err is not None:
        return None
    if p_rows is None:
        return 0
    return 1 if set(p_rows) == set(g_rows) else 0


def run_one(rec) -> dict:
    i = int(rec["rid"])
    db.set_target(_sqlite(rec["db_id"]))
    err, sql, ptok, ctok = None, "", 0, 0
    t0 = time.perf_counter()
    try:
        tables = sr.list_tables()               # linker off = 전체 스키마 (BIRD 최적)
        schema = sr.get_ddl(tables)
        schema += "\n\n# Column notes\n" + _metadata_block(rec["db_id"], tables)   # metadata on
        ev = (rec.get("evidence") or "").strip()
        if ev:
            schema += "\n\n# Evidence (external knowledge)\n" + ev                 # evidence on
        state = {"question": rec["question"], "schema": schema, "tables": tables,
                 "difficulty": DIFF_MAP.get(rec["difficulty"], "medium"),
                 "model": MODEL, "fewshot": _fewshot(i), "iteration": 0}
        sql = generate(state)["sql"]
        ptok, ctok = llm.last_usage()
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    latency = time.perf_counter() - t0
    db.set_target(None)

    ex = 0 if (err or not sql) else _official_ex(sql, rec["gold_sql"], _sqlite(rec["db_id"]))
    return {"rid": rec["rid"], "db_id": rec["db_id"], "difficulty": rec["difficulty"],
            "ex": ex, "prompt_tokens": ptok, "completion_tokens": ctok,
            "cost_usd": config.price_usd(MODEL, ptok, ctok), "latency": round(latency, 3),
            "evidence_used": bool((rec.get("evidence") or "").strip()),
            "pred_sql": sql, "error": err}


def cmd_run() -> None:
    for db_id in sorted({r["db_id"] for r in _RECS}):
        warm(db_id)
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                if not o.get("error"):
                    done.add(o["rid"])
    todo = [r for r in _RECS if r["rid"] not in done]
    print(f"[bird_strong] {MODEL} + evidence + fewshot{FEWSHOT_K} · 문항 {len(_RECS)} 남은 {len(todo)} · 병렬 {WORKERS}")
    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(rec):
            row = run_one(rec)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                spent[0] += row["cost_usd"]; n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(todo)}  ${spent[0]:.3f}")
        list(pool.map(work, todo))
    print(f"완료. ≈ ${spent[0]:.4f}. 리포트: python -m bench.bird_strong report")


def cmd_report() -> None:
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    # 마지막 값 우선(재시도 중복 대비)
    latest = {}
    for o in rows:
        latest[o["rid"]] = o
    vals = list(latest.values())
    import collections
    by = collections.defaultdict(lambda: {"n": 0, "ex": 0})
    tot = {"n": 0, "ex": 0}
    for o in vals:
        e = int(o["ex"] or 0)
        by[o["difficulty"]]["n"] += 1; by[o["difficulty"]]["ex"] += e
        tot["n"] += 1; tot["ex"] += e
    print(f"\n## BIRD strong ({MODEL} + evidence + fewshot{FEWSHOT_K}, 공식 채점)\n")
    for lv in ["simple", "moderate", "challenging"]:
        b = by[lv]
        if b["n"]:
            print(f"  {lv:12s}: {b['ex']/b['n']*100:.1f}% ({b['ex']}/{b['n']})")
    print(f"  {'전체':12s}: {tot['ex']/tot['n']*100:.1f}% ({tot['ex']}/{tot['n']})")
    err = sum(1 for o in vals if o["error"])
    print(f"\n에러 {err}, 비용 ${sum(o['cost_usd'] for o in vals):.4f}")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

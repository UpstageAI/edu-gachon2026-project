"""few-shot 정석 측정 — train 풀(9,428) vs dev 풀(누수 상한) A/B.

dev 풀 few-shot(bird_strong)은 같은 셋에서 예시를 뽑아 낙관적(약한 누수).
정석 = BIRD train 9,428 (질문,SQL) 풀에서 유사예시 검색(누수 없음, 실전과 동일 구조).

- trainpool 팔만 생성 (150문항, bird_strong 동일 config: pro3+evidence+metadata+fewshot8)
- devpool 팔은 results_bird_strong.jsonl 에서 같은 150 rid 슬라이스 (재생성 불필요)
- 공식 채점. 결과: results_fewshot_train.jsonl

실행: uv run python -m bench.fewshot_train_ab [report]
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
from bench import config  # noqa: E402
from bench.ablation import DIFF_MAP, EMB, _metadata_block, _sqlite, warm  # noqa: E402
from bench.bird_strong import MODEL, _official_ex, _RECS  # noqa: E402
from bench.mschema_ab import _sample  # noqa: E402 — 동일 seed-7 150 표본

RESULTS = config.BENCH_DIR / "results_fewshot_train.jsonl"
WORKERS = int(os.getenv("FT_WORKERS", "3"))
K = 8

_pool = json.loads((config.BENCH_DIR / "bird/train_pool.json").read_text(encoding="utf-8"))
_pvecs = np.load(EMB / "train_pool.npz")["vecs"]
_qraw = np.load(EMB / "questions.npz")["raw"].astype(float)
_qraw = _qraw / (np.linalg.norm(_qraw, axis=1, keepdims=True) + 1e-9)


def _fewshot_train(rid: int) -> list[dict]:
    order = np.argsort(-(_pvecs @ _qraw[rid]))[:K]
    return [{"question": _pool[i]["question"], "sql": _pool[i]["sql"]} for i in order]


def run_one(rec) -> dict:
    db.set_target(_sqlite(rec["db_id"]))
    err, sql, pt, ct = None, "", 0, 0
    t0 = time.perf_counter()
    try:
        tables = sr.list_tables()
        schema = sr.get_ddl(tables) + "\n\n# Column notes\n" + _metadata_block(rec["db_id"], tables)
        ev = (rec.get("evidence") or "").strip()
        if ev:
            schema += "\n\n# Evidence (external knowledge)\n" + ev
        state = {"question": rec["question"], "schema": schema, "tables": tables,
                 "difficulty": DIFF_MAP.get(rec["difficulty"], "medium"), "model": MODEL,
                 "fewshot": _fewshot_train(int(rec["rid"])), "iteration": 0}
        sql = generate(state)["sql"]
        pt, ct = llm.last_usage()
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    db.set_target(None)
    ex = 0 if (err or not sql) else _official_ex(sql, rec["gold_sql"], _sqlite(rec["db_id"]))
    return {"rid": rec["rid"], "difficulty": rec["difficulty"], "ex": ex,
            "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": config.price_usd(MODEL, pt, ct),
            "latency": round(time.perf_counter() - t0, 3), "pred_sql": sql, "error": err}


def cmd_run() -> None:
    sample = _sample()
    for db_id in sorted({r["db_id"] for r in sample}):
        warm(db_id)
    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line)
                if not o.get("error"):
                    done.add(o["rid"])
    todo = [r for r in sample if r["rid"] not in done]
    print(f"[fewshot_train] trainpool {MODEL}+evidence+meta+few{K} · 남은 {len(todo)}/150 · 병렬 {WORKERS}")
    lock, n = Lock(), [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(rec):
            row = run_one(rec)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(todo)}")
        list(pool.map(work, todo))
    print("완료. 리포트: python -m bench.fewshot_train_ab report")


def cmd_report() -> None:
    sample_rids = {r["rid"] for r in _sample()}
    # trainpool
    latest = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line); latest[o["rid"]] = o
    tr = list(latest.values())
    # devpool 슬라이스 (bird_strong 전체 500 중 같은 150)
    dev = {}
    f = config.BENCH_DIR / "results_bird_strong.jsonl"
    for line in f.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if o["rid"] in sample_rids:
                dev[o["rid"]] = o
    print("\n## few-shot 풀 A/B (BIRD 150, pro3+evidence+meta+few8, 공식 채점)\n")
    for name, rows in (("devpool(누수 상한)", list(dev.values())), ("trainpool(정석)", tr)):
        if rows:
            ex = sum(int(o["ex"] or 0) for o in rows)
            print(f"  {name:20s}: EX {ex/len(rows)*100:.1f}% ({ex}/{len(rows)})")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

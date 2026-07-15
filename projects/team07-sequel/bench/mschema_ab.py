"""M-Schema vs DDL+notes 포맷 A/B — 동일 정보, 포맷만 차이 (BIRD 150, pro2+metadata, 공식 채점).

M-Schema(XiYan-SQL 2411.08599) 채택 전 정확도 유지 검증. 두 팔 모두 metadata on ·
linker off · normalize off (3-factor ablation 의 최적 pro2 조건 N0L0M1).
  A ddl   : CREATE TABLE + "# Column notes" (기존 ablation 포맷)
  B mschema: 컬럼당 한 줄 (col: type, 설명, ex: 샘플)

결과 raw: results_mschema_ab.jsonl. 실행: uv run python -m bench.mschema_ab [report]
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
from app.repositories import schema_repository as sr  # noqa: E402
from bench import config, evaluate  # noqa: E402
from bench.ablation import BIRD, DIFF_MAP, _meta, _sqlite, warm  # noqa: E402
from bench.bird_strong import _official_ex  # noqa: E402

RESULTS = config.BENCH_DIR / "results_mschema_ab.jsonl"
MODEL = "solar-pro2"
WORKERS = 3
N_PER_LEVEL = 50
SEED = 7


def _ddl_notes(db_id: str, tables: list[str]) -> str:
    meta = _meta(db_id).get("tables", {})
    lines = [f"{t}.{c}: {i['description']}"
             for t in tables for c, i in meta.get(t, {}).get("columns", {}).items()]
    return sr.get_ddl(tables) + "\n\n# Column notes\n" + "\n".join(lines)


def _mschema(db_id: str, tables: list[str]) -> str:
    meta = _meta(db_id).get("tables", {})
    lines: list[str] = []
    for t in tables:
        cols_meta = meta.get(t, {}).get("columns", {})
        lines.append(f"# Table: {t}")
        for name, dtype in sr.get_columns(t):
            m = cols_meta.get(name)
            if m:
                ex = ", ".join(str(s)[:16] for s in (m.get("samples") or [])[:2] if s)
                lines.append(f"({name}: {dtype}, {m['description']}" + (f", ex: {ex})" if ex else ")"))
            else:
                lines.append(f"({name}: {dtype})")
        lines.append("")
    return "\n".join(lines).strip()


def run_one(rec, arm: str) -> dict:
    db.set_target(_sqlite(rec["db_id"]))
    err, sql, pt, ct = None, "", 0, 0
    t0 = time.perf_counter()
    try:
        tables = sr.list_tables()
        schema = (_mschema if arm == "mschema" else _ddl_notes)(rec["db_id"], tables)
        state = {"question": rec["question"], "schema": schema, "tables": tables,
                 "difficulty": DIFF_MAP.get(rec["difficulty"], "medium"),
                 "model": MODEL, "fewshot": [], "iteration": 0}
        sql = generate(state)["sql"]
        pt, ct = llm.last_usage()
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    db.set_target(None)
    ex = 0 if (err or not sql) else _official_ex(sql, rec["gold_sql"], _sqlite(rec["db_id"]))
    return {"rid": rec["rid"], "arm": arm, "difficulty": rec["difficulty"], "ex": ex,
            "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": config.price_usd(MODEL, pt, ct),
            "latency": round(time.perf_counter() - t0, 3), "pred_sql": sql, "error": err}


def _sample() -> list[dict]:
    recs = json.loads((BIRD / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
    for i, r in enumerate(recs):
        r["gold_sql"] = r["SQL"]; r["rid"] = str(i)
    by = defaultdict(list)
    for r in recs:
        by[r["difficulty"]].append(r)
    rng = random.Random(SEED)
    out = []
    for lv in ("simple", "moderate", "challenging"):
        out.extend(rng.sample(by[lv], min(N_PER_LEVEL, len(by[lv]))))
    return out


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
                    done.add((o["rid"], o["arm"]))
    tasks = [(r, arm) for r in sample for arm in ("ddl", "mschema") if (r["rid"], arm) not in done]
    print(f"[mschema_ab] {len(sample)}문항 × 2팔 · 남은 {len(tasks)} · 병렬 {WORKERS}")
    lock, n = Lock(), [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(t):
            row = run_one(*t)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(tasks)}")
        list(pool.map(work, tasks))
    print("완료. 리포트: python -m bench.mschema_ab report")


def cmd_report() -> None:
    latest = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line); latest[(o["rid"], o["arm"])] = o
    agg = defaultdict(lambda: {"n": 0, "ex": 0, "pt": 0})
    for o in latest.values():
        a = agg[o["arm"]]
        a["n"] += 1; a["ex"] += int(o["ex"] or 0); a["pt"] += o["prompt_tokens"]
    print("\n## M-Schema vs DDL+notes (BIRD 150, pro2+metadata, 공식 채점)\n")
    for arm in ("ddl", "mschema"):
        a = agg[arm]
        if a["n"]:
            print(f"  {arm:8s}: EX {a['ex']/a['n']*100:.1f}% ({a['ex']}/{a['n']}) · avg prompt {a['pt']//a['n']} tok")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

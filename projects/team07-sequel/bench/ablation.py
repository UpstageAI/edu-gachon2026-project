"""3-factor ablation (normalize × schema-linker × metadata) — BIRD MiniDev, 격리 실험.

app/ 파이프라인은 한 줄도 안 바꾼다. 사전계산 캐시(bench/bird/embeddings·metadata·normalized)를
로드해 도구 인메모리 캐시를 **워밍**하고(재임베딩·재정규화 없음), config 별로 스키마 문자열을
조립한 뒤 실제 generate 노드로 SQL 생성 → EX(우리 exec_match) + 토큰 측정.

factor 토글(2×2×2 = 8):
  N normalize : on=영어 normalize 캐시(정리+keyword) / off=원문, keyword 없음
  L linker    : on=schema_link(retrieve_schema+retrieve_values) / off=전체 스키마 DDL
  M metadata  : on=컬럼 설명(profiling→LLM) 주입 / off=이름만
고정: 생성 pro2 · few-shot off · gen_decompose off · 난이도 매핑 아래.

결과 raw: bench/results_ablation.jsonl (config·문항·EX·토큰·pred_sql). 재개 가능.
실행:
  uv run python -m bench.ablation            # 표본 250 실행
  uv run python -m bench.ablation report      # 집계(Pareto)
"""
from __future__ import annotations

import os

os.environ.setdefault("GEN_DECOMPOSE", "false")  # 생성 가이드 고정(교란 방지) — app import 전에

import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from threading import Lock  # noqa: E402

import numpy as np  # noqa: E402

from app.core import db, llm  # noqa: E402
from app.core.db import current_db_key  # noqa: E402
from app.graph.nodes.generator import generate  # noqa: E402
from app.graph.nodes.schema_linker import schema_link  # noqa: E402
from app.repositories import schema_repository as sr  # noqa: E402
from app.tools import schema_retriever, value_retriever  # noqa: E402
from bench import config, evaluate  # noqa: E402

BIRD = config.BENCH_DIR / "bird/minidev/MINIDEV"
EMB = config.BENCH_DIR / "bird/embeddings"
META = config.BENCH_DIR / "bird/metadata"
NORM = config.BENCH_DIR / "bird/normalized.jsonl"
RESULTS = config.BENCH_DIR / "results_ablation.jsonl"

MODEL = "solar-pro2"
WORKERS = int(os.getenv("ABL_WORKERS", "4"))  # 재시도 시 낮춰 429 완화
SAMPLE = 500  # 전체 (BIRD MiniDev SELECT-only)
SEED = 7
LEVELS = ["simple", "moderate", "challenging"]
DIFF_MAP = {"simple": "easy", "moderate": "medium", "challenging": "hard"}
CONFIGS = [(n, l, m) for n in (0, 1) for l in (0, 1) for m in (0, 1)]  # 8


def _sqlite(db_id: str) -> str:
    return str(BIRD / "dev_databases" / db_id / f"{db_id}.sqlite")


def _cfg_str(cfg) -> str:
    n, l, m = cfg
    return f"N{n}L{l}M{m}"


# ── 캐시 로드 ──────────────────────────────────────────────────────────────
_norm_cache: dict[str, dict] = {}
_meta_cache: dict[str, dict] = {}
_warmed: set[str] = set()


def _load_norm() -> None:
    for line in NORM.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if not o.get("error"):
                _norm_cache[o["question_id"]] = o


def _meta(db_id: str) -> dict:
    if db_id not in _meta_cache:
        _meta_cache[db_id] = json.loads((META / f"{db_id}.json").read_text(encoding="utf-8"))
    return _meta_cache[db_id]


def warm(db_id: str) -> None:
    """디스크 임베딩으로 도구 인메모리 캐시 워밍(재임베딩 없음). 메인스레드에서 1회."""
    db.set_target(_sqlite(db_id))
    dbk = current_db_key()
    if dbk in _warmed:
        return
    z = np.load(EMB / "schema" / f"{db_id}.npz")
    j = json.loads((EMB / "schema" / f"{db_id}.json").read_text(encoding="utf-8"))
    schema_retriever._indices[dbk] = {
        "tables": j["tables"], "cols": j["cols"], "tvecs": z["tvecs"],
        "col_items": [tuple(x) for x in j["col_items"]], "cvecs": z["cvecs"]}
    zv = np.load(EMB / "values" / f"{db_id}.npz")
    jv = json.loads((EMB / "values" / f"{db_id}.json").read_text(encoding="utf-8"))
    for i, m in enumerate(jv):
        value_retriever._cat_cache[f"{dbk}::{m['colkey']}"] = m["values"]
        value_retriever._emb_cache[f"{dbk}::{m['colkey']}"] = zv[f"v{i}"]
    _warmed.add(dbk)
    db.set_target(None)


def _metadata_block(db_id: str, tables: list[str]) -> str:
    meta = _meta(db_id).get("tables", {})
    lines = []
    for t in tables:
        for c, info in meta.get(t, {}).get("columns", {}).items():
            lines.append(f"{t}.{c}: {info['description']}")
    return "\n".join(lines)


# ── 한 문항 × 한 config ────────────────────────────────────────────────────
def run_one(cfg, rec, rid) -> dict:
    n, l, m = cfg
    db.set_target(_sqlite(rec["db_id"]))
    nc = _norm_cache.get(rec["question_id"], {})
    nq = (nc.get("normalized_question") or rec["question"]) if n else rec["question"]
    keywords = (nc.get("keywords") or []) if n else []
    time_range = (nc.get("time_range") or {}) if n else {}

    err, sql, ptok, ctok, schema = None, "", 0, 0, ""
    t0 = time.perf_counter()
    try:
        if l:  # linker on = 실제 schema_link 노드 그대로
            linked = schema_link({"question": rec["question"], "normalized_question": nq,
                                  "keywords": keywords, "time_range": time_range})
            schema, tables = linked["schema"], linked["tables"]
        else:  # linker off = 전체 스키마 DDL
            tables = sr.list_tables()
            schema = sr.get_ddl(tables)
        if m:
            schema = schema + "\n\n# Column notes\n" + _metadata_block(rec["db_id"], tables)
        state = {"question": rec["question"], "schema": schema, "tables": tables,
                 "difficulty": DIFF_MAP.get(rec["difficulty"], "medium"),
                 "model": MODEL, "fewshot": [], "iteration": 0}
        sql = generate(state)["sql"]
        ptok, ctok = llm.last_usage()
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    latency = time.perf_counter() - t0
    db.set_target(None)

    if err or not sql:
        ex, note = False, err or "empty"
    else:
        ex, note = evaluate.exec_match(sql, rec["gold_sql"], _sqlite(rec["db_id"]), config.EXEC_TIMEOUT_S)
    return {"rid": rid, "config": _cfg_str(cfg), "question_id": rec["question_id"],
            "db_id": rec["db_id"], "difficulty": rec["difficulty"], "ex": ex,
            "prompt_tokens": ptok, "completion_tokens": ctok,
            "cost_usd": config.price_usd(MODEL, ptok, ctok), "schema_chars": len(schema),
            "latency": round(latency, 3), "pred_sql": sql, "error": err, "exec_note": None if ex else note}


# ── 표본 ──────────────────────────────────────────────────────────────────
def _sample() -> list[dict]:
    recs = json.loads((BIRD / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
    for i, r in enumerate(recs):
        r["gold_sql"] = r["SQL"]
        r["_rid"] = str(i)  # dup question_id 대비 row index 키
    if SAMPLE >= len(recs):
        return recs  # 전체
    by = defaultdict(list)
    for r in recs:
        by[r["difficulty"]].append(r)
    rng = random.Random(SEED)
    per = len(recs) and SAMPLE // len(LEVELS)
    out = []
    for lv in LEVELS:
        out.extend(rng.sample(by[lv], min(per, len(by[lv]))))
    return out


def cmd_run() -> None:
    if not settings_ok():
        raise SystemExit("UPSTAGE_API_KEY 필요")
    _load_norm()
    sample = _sample()
    for db_id in sorted({r["db_id"] for r in sample}):  # 메인스레드에서 워밍
        warm(db_id)
    tasks = [(cfg, rec, f"{i}") for i, rec in enumerate(sample) for cfg in CONFIGS]

    done = set()
    if RESULTS.exists():
        for line in RESULTS.read_text(encoding="utf-8").splitlines():
            if line.strip():
                o = json.loads(line); done.add((o["rid"], o["config"]))
    todo = [t for t in tasks if (t[2], _cfg_str(t[0])) not in done]
    print(f"[ablation] 문항 {len(sample)} × 8 config = {len(tasks)} · 남은 {len(todo)} · 병렬 {WORKERS}")

    lock, spent, n = Lock(), [0.0], [0]
    with RESULTS.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(t):
            row = run_one(*t)
            with lock:
                fout.write(json.dumps(row, ensure_ascii=False) + "\n"); fout.flush()
                spent[0] += row["cost_usd"]; n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(todo)}  ${spent[0]:.3f}")
        list(pool.map(work, todo))
    print(f"완료. 누적 ≈ ${spent[0]:.4f}. 리포트: python -m bench.ablation report")


def settings_ok() -> bool:
    from app.core.settings import settings
    return bool(settings.upstage_api_key)


def cmd_report() -> None:
    if not RESULTS.exists():
        raise SystemExit("results_ablation.jsonl 없음")
    rows = [json.loads(l) for l in RESULTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    agg = defaultdict(lambda: {"n": 0, "ex": 0, "ptok": 0, "ctok": 0, "cost": 0.0})
    for o in rows:
        a = agg[o["config"]]
        a["n"] += 1; a["ex"] += int(o["ex"]); a["ptok"] += o["prompt_tokens"]
        a["ctok"] += o["completion_tokens"]; a["cost"] += o["cost_usd"]
    print("\n## 3-factor ablation (BIRD MiniDev, pro2) — EX vs 토큰(효율)\n")
    print("| config | N|L|M | EX% | avg prompt tok | avg comp tok | $/정답 |")
    print("|---|---|---|---|---|---|---|")
    for cfg in ("N0L0M0", "N0L0M1", "N0L1M0", "N0L1M1", "N1L0M0", "N1L0M1", "N1L1M0", "N1L1M1"):
        a = agg.get(cfg)
        if not a or not a["n"]:
            continue
        n, l, m = cfg[1], cfg[3], cfg[5]
        exr = a["ex"] / a["n"] * 100
        cpc = a["cost"] / a["ex"] if a["ex"] else float("inf")
        print(f"| {cfg} | {n}|{l}|{m} | {exr:.1f}% ({a['ex']}/{a['n']}) | "
              f"{a['ptok']//a['n']} | {a['ctok']//a['n']} | ${cpc:.5f} |")
    err = sum(1 for o in rows if o["error"])
    print(f"\n총 {len(rows)}행, 에러 {err}, 비용 ${sum(o['cost_usd'] for o in rows):.4f}")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

"""BIRD 풀 파이프라인 — 강화(pro3+evidence+fewshot+metadata)에 3레버 추가 후 ablation.

추가 레버 (전부 env 토글 = leave-one-out ablation 에 그대로 사용):
  BF_CAND=3   다중 후보 N (스키마 필드 순서 셔플로 다양성) + 실행결과 다수결 투표
  BF_REPAIR=1 실행유도 수리(Maple): 결과가 에러/빈결과면 LLM 에 사유+SQL 줘서 교정(최대 2회)
  BF_CTE=1    challenging→extra_hard + gen_decompose on(런타임 settings 토글) = CTE 분해 가이드
  BF_EVID=1 / BF_FEWSHOT=1  (강화 레버, ablation 용으로 끌 수 있음)

공식 채점(set). app/ 미변경(생성/실행/추출 노드·도구만 호출, settings 값만 런타임 조정).
결과 raw: results_bird_full_<tag>.jsonl (tag=플래그). 재개 가능.
실행: uv run python -m bench.bird_full [report]
"""
from __future__ import annotations

import os

CAND = int(os.getenv("BF_CAND", "3"))
REPAIR = os.getenv("BF_REPAIR", "1") == "1"
CTE = os.getenv("BF_CTE", "1") == "1"
EVID = os.getenv("BF_EVID", "1") == "1"
FEW = os.getenv("BF_FEWSHOT", "1") == "1"
os.environ.setdefault("GEN_DECOMPOSE", "true" if CTE else "false")  # app import 전

import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter  # noqa: E402
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from threading import Lock  # noqa: E402

from app.core import db, llm  # noqa: E402
from app.core.settings import settings  # noqa: E402
from app.graph.nodes.generator import _extract_sql, generate  # noqa: E402
from app.repositories import schema_repository as sr  # noqa: E402
from bench import config, evaluate  # noqa: E402
from bench.ablation import _metadata_block, warm  # noqa: E402
from bench.bird_strong import MODEL, _RECS, _fewshot, _official_ex, _sqlite  # noqa: E402

settings.gen_decompose = CTE  # 런타임 토글(설정값, 로직 아님)
DIFF = {"simple": "easy", "moderate": "medium", "challenging": "extra_hard" if CTE else "hard"}
TAG = f"C{CAND}R{int(REPAIR)}T{int(CTE)}E{int(EVID)}F{int(FEW)}"
RESULTS = config.BENCH_DIR / f"results_bird_full_{TAG}.jsonl"
WORKERS = int(os.getenv("BF_WORKERS", "3"))

REPAIR_SYS = ("You fix a failing SQLite SELECT query. Given the schema, question, the previous SQL "
              "and its failure, output ONLY the corrected SQL (no prose).")


def _ddl(rng: random.Random | None) -> tuple[list[str], str]:
    """전체 스키마 DDL. rng 주면 테이블·컬럼 순서 셔플(후보 다양성)."""
    tables = sr.list_tables()
    if rng:
        rng.shuffle(tables)
    parts = []
    for t in tables:
        cols = list(sr.get_columns(t))
        if rng:
            rng.shuffle(cols)
        body = ",\n  ".join(f'"{n}" {d}' for n, d in cols)
        parts.append(f'CREATE TABLE "{t}" (\n  {body}\n)')
    return tables, "\n\n".join(parts)


def _schema(rec, rng) -> tuple[list[str], str]:
    tables, ddl = _ddl(rng)
    schema = ddl + "\n\n# Column notes\n" + _metadata_block(rec["db_id"], tables)
    ev = (rec.get("evidence") or "").strip()
    if EVID and ev:
        schema += "\n\n# Evidence (external knowledge)\n" + ev
    return tables, schema


def _gen(rec, schema, tables) -> tuple[str, int, int]:
    state = {"question": rec["question"], "schema": schema, "tables": tables,
             "difficulty": DIFF.get(rec["difficulty"], "medium"), "model": MODEL,
             "fewshot": _fewshot(int(rec["rid"])) if FEW else [], "iteration": 0}
    sql = generate(state)["sql"]
    p, c = llm.last_usage()
    return sql, p, c


def _vote(sqls: list[str], db_path: str) -> str:
    """후보 실행 → 결과셋 다수결. 전부 에러면 첫 후보 반환(수리로 넘김)."""
    buckets: list[tuple[frozenset, str]] = []
    for s in sqls:
        rows, err = evaluate._run(s, db_path, config.EXEC_TIMEOUT_S)
        if err is None:
            buckets.append((frozenset(rows), s))
    if not buckets:
        return sqls[0]
    top = Counter(k for k, _ in buckets).most_common(1)[0][0]
    return next(s for k, s in buckets if k == top)


def _repair(rec, schema, sql, db_path) -> tuple[str, int, int]:
    """에러/빈결과면 LLM 교정(최대 2회). 반환: (sql, ptok_add, ctok_add)."""
    pt = ct = 0
    for _ in range(2):
        rows, err = evaluate._run(sql, db_path, config.EXEC_TIMEOUT_S)
        if err is None and rows:
            break
        reason = err if err else "query returned no rows"
        res = llm.complete(MODEL, [
            {"role": "system", "content": REPAIR_SYS},
            {"role": "user", "content": f"Schema:\n{schema}\n\nQuestion: {rec['question']}\n\n"
                                        f"Previous SQL:\n{sql}\n\nFailure: {reason}\n\n"
                                        f"Output ONLY the corrected SQL."}], temperature=0.0)
        sql = _extract_sql(res.text)
        pt += res.prompt_tokens; ct += res.completion_tokens
    return sql, pt, ct


def run_one(rec) -> dict:
    db.set_target(_sqlite(rec["db_id"]))
    dbp = _sqlite(rec["db_id"])
    err, sql, pt, ct = None, "", 0, 0
    t0 = time.perf_counter()
    try:
        sqls = []
        for c in range(CAND):
            _, schema = _schema(rec, random.Random(c) if c else None)  # c=0 셔플 없음
            s, p, cc = _gen(rec, schema, sr.list_tables())
            sqls.append(s); pt += p; ct += cc
        sql = _vote(sqls, dbp) if CAND > 1 else sqls[0]
        _, schema0 = _schema(rec, None)
        if REPAIR:
            sql, rp, rc = _repair(rec, schema0, sql, dbp)
            pt += rp; ct += rc
    except Exception as e:  # noqa: BLE001
        err = str(e)[:200]
    latency = time.perf_counter() - t0
    db.set_target(None)
    ex = 0 if (err or not sql) else _official_ex(sql, rec["gold_sql"], dbp)
    return {"rid": rec["rid"], "db_id": rec["db_id"], "difficulty": rec["difficulty"], "ex": ex,
            "prompt_tokens": pt, "completion_tokens": ct,
            "cost_usd": config.price_usd(MODEL, pt, ct), "latency": round(latency, 3),
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
    print(f"[bird_full {TAG}] cand={CAND} repair={REPAIR} cte={CTE} evid={EVID} few={FEW} · 남은 {len(todo)} · 병렬 {WORKERS}")
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
    print(f"완료 {TAG}. ≈ ${spent[0]:.4f}")


def cmd_report() -> None:
    rows = {}
    for line in RESULTS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line); rows[o["rid"]] = o
    vals = list(rows.values())
    import collections
    by = collections.defaultdict(lambda: {"n": 0, "ex": 0})
    tot = {"n": 0, "ex": 0}
    for o in vals:
        e = int(o["ex"] or 0)
        by[o["difficulty"]]["n"] += 1; by[o["difficulty"]]["ex"] += e
        tot["n"] += 1; tot["ex"] += e
    print(f"\n## BIRD full [{TAG}] (공식 채점)\n")
    for lv in ["simple", "moderate", "challenging"]:
        b = by[lv]
        if b["n"]:
            print(f"  {lv:12s}: {b['ex']/b['n']*100:.1f}% ({b['ex']}/{b['n']})")
    print(f"  {'전체':12s}: {tot['ex']/tot['n']*100:.1f}% ({tot['ex']}/{tot['n']})")
    print(f"\n비용 ${sum(o['cost_usd'] for o in vals):.4f}")


if __name__ == "__main__":
    (cmd_report if "report" in sys.argv else cmd_run)()

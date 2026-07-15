"""BIRD 임베딩·정규화 사전 계산 (오프라인, app/ 미변경). solar-embedding-2 무료기간 활용.

app 파이프라인은 한 줄도 안 바꾼다. 도구 함수(schema_retriever._build_index,
value_retriever._categorical, normalize 노드, embeddings.*)를 **호출만** 해서
결과를 디스크에 얼려둔다(ablation 재현·속도·무료기간 대비).

3종 + 정규화 캐시 (모두 결과 raw + 로그 분리):
  1) 스키마 인덱스(테이블+컬럼)  → embeddings/schema/<db>.npz  + <db>.json
  2) 값 임베딩(categorical 컬럼)  → embeddings/values/<db>.npz  + <db>.json
  3) 질문 임베딩(raw+normalized)  → embeddings/questions.npz    + questions.json
  0) normalize(LLM) 출력 캐시      → normalized.jsonl (재개 가능; 레이트리밋 주의)
  로그: embeddings/logs/build.jsonl

실행:
  uv run python -m bench.build_embeddings normalize|schema|values|questions|all [db_id ...]
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

import numpy as np

from app.core import db, embeddings, llm
from app.graph.nodes.query_normalizer import _time_range  # 시간규칙(한국어) — 영어엔 {} 반환, 스코프 동일 유지
from app.repositories import schema_repository as sr
from app.tools import schema_retriever, value_retriever
from bench import config

# BIRD 는 영어라 한국어 튜닝 normalizer 가 번역·오매칭 → 동일 스코프의 영어 프롬프트로 대체(app/ 미변경).
# app.core.prompts.NORMALIZER 와 같은 일(질문 정리·리터럴 keyword·ambiguous)을 영어로 한다.
NORMALIZER_EN = (
    "You are an English database-query preprocessor. Reply ONLY with JSON:\n"
    '{"normalized_question": "a self-contained question with pronouns/ellipsis resolved", '
    '"keywords": ["only short literal proper nouns / codes / numbers that match DB cell values verbatim"], '
    '"ambiguous": false}\n\n'
    "keywords rules (important):\n"
    "- extract only actual values in the question (place/org names, status values, codes, numbers, "
    "proper nouns) exactly as they appear in the DB. 1-3 words each.\n"
    "- never include intent/summary clauses; if there is no matching cell value, drop it.\n"
    "- good: 'EUR', 'SME', 'LAM', '2012'\n"
    "- bad (do not include): 'gas consumption', 'ratio of customers', 'average monthly consumption'"
)


def _normalize_en(question: str) -> dict:
    """영어용 normalize — app normalize 노드와 동일 출력 구조/스코프, 프롬프트만 영어."""
    time_range = _time_range(question)  # 한국어 규칙 → 영어엔 {} (구조 동일 유지)
    res = llm.complete("solar-mini", [{"role": "system", "content": NORMALIZER_EN},
                                      {"role": "user", "content": question}], temperature=0.0)
    normalized, keywords, ambiguous = question, [], False
    try:
        obj = json.loads(res.text)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if isinstance(obj, dict):
        nq = obj.get("normalized_question")
        normalized = nq if isinstance(nq, str) and nq.strip() else question
        kw = obj.get("keywords")
        keywords = [k for k in kw if isinstance(k, str) and k.strip()] if isinstance(kw, list) else []
        ambiguous = obj.get("ambiguous") is True
    return {"normalized_question": normalized, "keywords": keywords,
            "time_range": time_range, "ambiguous": ambiguous}

BIRD_ROOT = config.BENCH_DIR / "bird/minidev/MINIDEV"
EMB_DIR = config.BENCH_DIR / "bird/embeddings"
LOG = EMB_DIR / "logs/build.jsonl"
NORM_CACHE = config.BENCH_DIR / "bird/normalized.jsonl"
WORKERS = 3  # normalize LLM 호출 레이트리밋 방어


def _recs() -> list[dict]:
    return json.loads((BIRD_ROOT / "mini_dev_sqlite.json").read_text(encoding="utf-8"))


def bird_dbs() -> list[str]:
    return sorted({r["db_id"] for r in _recs()})


def bird_sqlite(db_id: str) -> str:
    return str(BIRD_ROOT / "dev_databases" / db_id / f"{db_id}.sqlite")


def _log(**rec) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ── 0) normalize(LLM) 캐시 ────────────────────────────────────────────────
def _done_qids() -> set:
    if not NORM_CACHE.exists():
        return set()
    return {json.loads(l)["question_id"] for l in NORM_CACHE.read_text(encoding="utf-8").splitlines()
            if l.strip() and not json.loads(l).get("error")}


def build_normalize() -> None:
    recs = _recs()
    done = _done_qids()
    todo = [r for r in recs if r["question_id"] not in done]
    print(f"[normalize] {len(recs)}개 중 남은 {len(todo)} · 병렬 {WORKERS}")
    NORM_CACHE.parent.mkdir(parents=True, exist_ok=True)
    lock, n = Lock(), [0]
    with NORM_CACHE.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
        def work(r):
            t0 = time.perf_counter(); err = None; out = {}
            try:
                out = _normalize_en(r["question"])  # 영어용 (BIRD)
            except Exception as e:  # noqa: BLE001
                err = str(e)[:200]
            rec = {"question_id": r["question_id"], "db_id": r["db_id"], "question": r["question"],
                   "normalized_question": out.get("normalized_question", ""),
                   "keywords": out.get("keywords", []), "time_range": out.get("time_range", {}),
                   "latency": round(time.perf_counter() - t0, 3), "error": err}
            with lock:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
                n[0] += 1
                if n[0] % 50 == 0:
                    print(f"  {n[0]}/{len(todo)}")
        list(pool.map(work, todo))
    errs = sum(1 for l in NORM_CACHE.read_text(encoding="utf-8").splitlines()
               if l.strip() and json.loads(l).get("error"))
    print(f"[normalize] 완료 (에러 라인 {errs} — 재실행하면 재개)")
    _log(step="normalize", n=len(recs), errors=errs)


# ── 1) 스키마 인덱스 ───────────────────────────────────────────────────────
def build_schema(dbs: list[str]) -> None:
    out = EMB_DIR / "schema"; out.mkdir(parents=True, exist_ok=True)
    for d in dbs:
        if (out / f"{d}.npz").exists():
            print(f"[schema] {d} 스킵(존재)"); continue
        t0 = time.perf_counter()
        try:
            db.set_target(bird_sqlite(d))
            idx = schema_retriever._build_index()  # {tables, cols, tvecs, col_items, cvecs} — 도구 재사용
            db.set_target(None)
        except Exception as e:  # noqa: BLE001 — 레이트리밋 등 → 이 DB 건너뛰고 재실행으로 재개
            db.set_target(None)
            print(f"[schema] {d} 실패(재실행 시 재개): {str(e)[:120]}")
            _log(step="schema", db=d, error=str(e)[:200]); continue
        np.savez(out / f"{d}.npz", tvecs=idx["tvecs"], cvecs=idx["cvecs"])
        (out / f"{d}.json").write_text(json.dumps(
            {"tables": idx["tables"], "cols": idx["cols"], "col_items": idx["col_items"]},
            ensure_ascii=False), encoding="utf-8")
        dt = round(time.perf_counter() - t0, 2)
        print(f"[schema] {d}: 테이블 {len(idx['tables'])} · 컬럼벡터 {len(idx['col_items'])} ({dt}s)")
        _log(step="schema", db=d, tables=len(idx["tables"]), cols=len(idx["col_items"]), latency=dt)


# ── 2) 값 임베딩(categorical) ─────────────────────────────────────────────
def build_values(dbs: list[str]) -> None:
    out = EMB_DIR / "values"; out.mkdir(parents=True, exist_ok=True)
    for d in dbs:
        if (out / f"{d}.json").exists():
            print(f"[values] {d} 스킵(존재)"); continue
        t0 = time.perf_counter()
        try:
            db.set_target(bird_sqlite(d))
            catmap = value_retriever._categorical(sr.list_tables())  # {colkey: [values]} — 도구 재사용
            arrays, meta = {}, []
            for i, (colkey, vals) in enumerate(catmap.items()):
                m = np.asarray(embeddings.embed_passages(vals), dtype=float)
                m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)  # _emb 와 동일 정규화
                arrays[f"v{i}"] = m
                meta.append({"colkey": colkey, "values": vals})
                time.sleep(0.3)  # RPM 버스트 완화(수십 컬럼 연속 임베딩)
            db.set_target(None)
        except Exception as e:  # noqa: BLE001 — 레이트리밋 등 → 건너뛰고 재실행으로 재개
            db.set_target(None)
            print(f"[values] {d} 실패(재실행 시 재개): {str(e)[:120]}")
            _log(step="values", db=d, error=str(e)[:200]); continue
        np.savez(out / f"{d}.npz", **arrays)
        (out / f"{d}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        dt = round(time.perf_counter() - t0, 2)
        print(f"[values] {d}: categorical 컬럼 {len(meta)} ({dt}s)")
        _log(step="values", db=d, cat_cols=len(meta), latency=dt)


# ── 3) 질문 임베딩(raw + normalized) ──────────────────────────────────────
def build_questions() -> None:
    if not NORM_CACHE.exists():
        raise SystemExit("normalized.jsonl 없음 — 먼저 normalize 실행")
    norm = {json.loads(l)["question_id"]: json.loads(l)
            for l in NORM_CACHE.read_text(encoding="utf-8").splitlines() if l.strip()}
    recs = _recs()
    ids = [r["question_id"] for r in recs]
    raw_txt = [r["question"] for r in recs]
    norm_txt = [norm.get(r["question_id"], {}).get("normalized_question") or r["question"] for r in recs]
    t0 = time.perf_counter()
    raw_vec = np.asarray(embeddings._embed(embeddings.QUERY_MODEL, raw_txt), dtype=float)   # query 측 모델
    norm_vec = np.asarray(embeddings._embed(embeddings.QUERY_MODEL, norm_txt), dtype=float)
    EMB_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(EMB_DIR / "questions.npz", raw=raw_vec, norm=norm_vec)
    (EMB_DIR / "questions.json").write_text(json.dumps({"ids": ids}, ensure_ascii=False), encoding="utf-8")
    dt = round(time.perf_counter() - t0, 2)
    print(f"[questions] {len(ids)}개 raw+normalized 임베딩 ({dt}s)")
    _log(step="questions", n=len(ids), latency=dt)


def main() -> None:
    if not (BIRD_ROOT / "mini_dev_sqlite.json").exists():
        raise SystemExit("BIRD MiniDev 없음")
    args = sys.argv[1:] or ["all"]
    step = args[0]
    dbs = args[1:] or bird_dbs()
    if step in ("normalize", "all"):
        build_normalize()
    if step in ("schema", "all"):
        build_schema(dbs)
    if step in ("values", "all"):
        build_values(dbs)
    if step in ("questions", "all"):
        build_questions()
    print("완료.")


if __name__ == "__main__":
    main()

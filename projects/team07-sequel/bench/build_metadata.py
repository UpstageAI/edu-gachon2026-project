"""DB 메타데이터(프로파일링 + LLM 필드 설명) 오프라인 추출 — 논문 arXiv 2505.19988 방식.

컬럼별로 (1) 프로파일링 통계를 SQL 로 뽑고 (2) 그 통계를 solar-mini 에 줘서
"이 컬럼의 의미·값 형식" 을 한 문장으로 설명하게 한다. 쿼리당 비용이 아니라
**DB당 오프라인 1회** 생성·캐시(ablation 의 metadata 축 = 이걸 스키마에 주입할지 on/off).

출력 (모든 로그 따로 + 결과 raw):
  bench/bird/metadata/<db_id>.json        — 소비용 결과 (테이블→컬럼→{profile, description})
  bench/bird/metadata/logs/<db_id>.jsonl  — 원시 로그 (컬럼별 profile+프롬프트+응답+토큰+latency)
재개: 로그에 이미 있는 (table,column) 은 건너뜀.

실행:
  uv run python -m bench.build_metadata bird            # BIRD 11 DB 전부
  uv run python -m bench.build_metadata bird toxicology # 특정 DB 만
  uv run python -m bench.build_metadata supabase        # 실서비스 DB → app/static/column_notes.json
"""
from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from sqlalchemy import text

from app.core import db, llm
from app.repositories import schema_repository as sr
from bench import config

_EX_SAMPLE_LEN = 60  # column_notes.json 예시값 절단 길이 (16자는 이메일 등 형식이 깨짐)


def _truncate_sample(s: str, limit: int = _EX_SAMPLE_LEN) -> str:
    """예시값을 단어 중간이 아닌 경계에서 자르고, 잘렸으면 말줄임표를 붙인다."""
    s = str(s)
    if len(s) <= limit:
        return s
    cut = s[:limit].rsplit(" ", 1)[0] or s[:limit]  # 공백 없으면(단어/이메일 등) 그냥 절단
    return cut + "…"

BIRD_ROOT = config.BENCH_DIR / "bird/minidev/MINIDEV"
OUT_DIR = config.BENCH_DIR / "bird/metadata"
LOG_DIR = OUT_DIR / "logs"
WORKERS = 3          # solar-mini 설명 호출 — 레이트리밋 방어(낮게)
TOP_K = 5            # 컬럼별 최빈 샘플 값 개수
_MODEL = "solar-mini"

META_DESC_SYS = (
    "You write a ONE-sentence English description of a database column's meaning and value "
    "format, grounded in the given profile. Be specific about format when evident "
    "(e.g., 'YYYY-MM-DD dates', '14-character school codes', 'boolean 0/1'). "
    "Output only the sentence, no preamble."
)


def _q(name: str) -> str:
    """sqlite 식별자 안전 인용(예약어·공백·특수문자 대비)."""
    return '"' + name.replace('"', '""') + '"'


def _s(v) -> str:
    return "" if v is None else str(v)[:80]


def bird_dbs() -> list[str]:
    recs = json.loads((BIRD_ROOT / "mini_dev_sqlite.json").read_text(encoding="utf-8"))
    return sorted({r["db_id"] for r in recs})


def bird_sqlite(db_id: str) -> str:
    return str(BIRD_ROOT / "dev_databases" / db_id / f"{db_id}.sqlite")


def _profile(path: str, table: str, col: str, dtype: str, rows: int) -> dict:
    """컬럼 1개 프로파일링(SQL). distinct·non-null·min·max·최빈 top-k."""
    db.set_target(path)
    with db.get_engine().connect() as c:
        nd = c.execute(text(f"SELECT COUNT(DISTINCT {_q(col)}) FROM {_q(table)}")).scalar() or 0
        nn = c.execute(text(f"SELECT COUNT({_q(col)}) FROM {_q(table)}")).scalar() or 0
        mn, mx = c.execute(text(f"SELECT MIN({_q(col)}), MAX({_q(col)}) FROM {_q(table)}")).one()
        samples = [r[0] for r in c.execute(text(
            f"SELECT {_q(col)} FROM {_q(table)} WHERE {_q(col)} IS NOT NULL "
            f"GROUP BY {_q(col)} ORDER BY COUNT(*) DESC LIMIT {TOP_K}")).all()]
    return {"dtype": dtype, "rows": rows, "non_null": int(nn), "distinct": int(nd),
            "null_pct": round((1 - nn / rows) * 100, 1) if rows else 0.0,
            "min": _s(mn), "max": _s(mx), "samples": [_s(v) for v in samples]}


def _describe(db_id: str, table: str, col: str, prof: dict, siblings: list[str]) -> tuple[str, object]:
    """프로파일을 solar-mini 에 줘 한 문장 설명 생성."""
    user = (f"Database: {db_id}\nTable: {table}\nColumn: {col} (declared type: {prof['dtype']})\n"
            f"Sibling columns: {', '.join(siblings)}\n"
            f"Stats: rows={prof['rows']}, distinct={prof['distinct']}, null={prof['null_pct']}%, "
            f"min={prof['min']}, max={prof['max']}\nSample values: {prof['samples']}")
    res = llm.complete(_MODEL, [{"role": "system", "content": META_DESC_SYS},
                                {"role": "user", "content": user}], temperature=0.0, max_tokens=80)
    return user, res


def _one_column(path, db_id, table, col, dtype, siblings, rows) -> dict:
    """한 컬럼: 프로파일 + 설명 → 로그 레코드."""
    t0 = time.perf_counter()
    err = None
    prof, prompt, desc, ptok, ctok = {}, "", "", 0, 0
    try:
        prof = _profile(path, table, col, dtype, rows)
        prompt, res = _describe(db_id, table, col, prof, siblings)
        desc, ptok, ctok = res.text.strip(), res.prompt_tokens, res.completion_tokens
    except Exception as e:  # noqa: BLE001 — 한 컬럼 실패가 DB 전체를 죽이지 않게
        err = str(e)[:200]
    return {"db_id": db_id, "table": table, "column": col, "profile": prof,
            "prompt": prompt, "description": desc, "prompt_tokens": ptok,
            "completion_tokens": ctok, "cost_usd": config.price_usd(_MODEL, ptok, ctok),
            "latency": round(time.perf_counter() - t0, 3), "error": err}


def _done_keys(log_path: Path) -> set:
    if not log_path.exists():
        return set()
    done = set()
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if not o.get("error"):
                done.add((o["table"], o["column"]))
    return done


def _rebuild_json(db_id: str, log_path: Path) -> int:
    """로그(raw)에서 소비용 metadata json 재구성(부분 실행에도 일관)."""
    tables: dict = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        if o.get("error"):
            continue
        col = dict(o["profile"]); col["description"] = o["description"]
        tables.setdefault(o["table"], {}).setdefault("columns", {})[o["column"]] = col
    n = sum(len(t["columns"]) for t in tables.values())
    (OUT_DIR / f"{db_id}.json").write_text(
        json.dumps({"db_id": db_id, "n_columns": n, "tables": tables}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return n


def build_db(db_id: str) -> None:
    path = bird_sqlite(db_id)
    log_path = LOG_DIR / f"{db_id}.jsonl"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    done = _done_keys(log_path)

    db.set_target(path)
    tables = sr.list_tables()
    # 컬럼 작업목록 + 테이블별 행수(1회) 준비
    jobs = []
    with db.get_engine().connect() as c:
        for t in tables:
            cols = sr.get_columns(t)  # [(name, dtype)]
            names = [n for n, _ in cols]
            rows = c.execute(text(f"SELECT COUNT(*) FROM {_q(t)}")).scalar() or 0
            for name, dtype in cols:
                if (t, name) in done:
                    continue
                siblings = [n for n in names if n != name][:20]
                jobs.append((path, db_id, t, name, dtype, siblings, rows))
    db.set_target(None)

    print(f"[{db_id}] 테이블 {len(tables)} · 남은 컬럼 {len(jobs)} (완료 {len(done)}) · 병렬 {WORKERS}")
    if jobs:
        lock, spent, n = Lock(), [0.0], [0]
        with log_path.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
            def work(job):
                rec = _one_column(*job)
                with lock:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
                    spent[0] += rec["cost_usd"]; n[0] += 1
                    if n[0] % 25 == 0:
                        print(f"  {n[0]}/{len(jobs)}  ${spent[0]:.4f}")
            list(pool.map(work, jobs))
    n_cols = _rebuild_json(db_id, log_path)
    print(f"[{db_id}] 완료 → metadata/{db_id}.json ({n_cols} 컬럼)")


# ── 실서비스(Supabase) 모드 — 한국어 설명, app/static/column_notes.json 산출 ──
# 간결 명사구: M-Schema 는 테이블·컬럼명이 위치로 주어지므로 설명에서 반복하면 토큰 낭비
# (기존 문장형 설명은 평균 135자, 82/90 이 테이블명 재언급 → 전체 프롬프트의 82% 차지했음).
META_DESC_SYS_KO = (
    "주어진 프로파일에 근거해 이 컬럼의 의미를 한국어 25자 이내 명사구로 설명하라. "
    "테이블명·컬럼명을 반복하지 말 것. 값 형식이 특징적이면 포함"
    "(예: '주문 상태 코드(delivered 등)', 'YYYY-MM-DD 구매 시각'). 명사구만 출력."
)


def build_supabase() -> None:
    """기본 엔진(Supabase)을 프로파일링해 한국어 컬럼 설명을 생성.

    산출: app/static/column_notes.json  {table: {col: 설명}}  (슬림, 커밋 대상)
          bench/metadata_supabase_log.jsonl  (원시 로그, 재개용)
    """
    global META_DESC_SYS
    META_DESC_SYS = META_DESC_SYS_KO  # _describe 가 참조하는 시스템 프롬프트를 한국어로
    log_path = config.BENCH_DIR / "metadata_supabase_log.jsonl"
    done = _done_keys(log_path)

    from sqlalchemy import text as _text
    tables = sr.list_tables()
    jobs = []
    with db.get_engine().connect() as c:
        for t in tables:
            cols = sr.get_columns(t)
            names = [n for n, _ in cols]
            rows = c.execute(_text(f"SELECT COUNT(*) FROM {_q(t)}")).scalar() or 0
            for name, dtype in cols:
                if (t, name) in done:
                    continue
                jobs.append((None, "supabase", t, name, dtype, [n for n in names if n != name][:20], rows))

    print(f"[supabase] 테이블 {len(tables)} · 남은 컬럼 {len(jobs)} (완료 {len(done)}) · 병렬 {WORKERS}")
    if jobs:
        lock = Lock()
        with log_path.open("a", encoding="utf-8") as fout, ThreadPoolExecutor(max_workers=WORKERS) as pool:
            def work(job):
                rec = _one_column(*job)
                with lock:
                    fout.write(json.dumps(rec, ensure_ascii=False) + "\n"); fout.flush()
            list(pool.map(work, jobs))

    # 슬림 산출물 (런타임 소비용) — metadata_repository 가 읽는 신포맷과 통일:
    # {table: {col: {"d": 설명, "ex": [샘플<=2]}}}
    notes: dict[str, dict] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if not o.get("error") and o.get("description"):
                samples = (o.get("profile") or {}).get("samples") or []
                ex = [_truncate_sample(s) for s in samples[:2] if s]
                notes.setdefault(o["table"], {})[o["column"]] = {"d": o["description"], "ex": ex}
    out = config.BENCH_DIR.parent / "app/static/column_notes.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    n = sum(len(v) for v in notes.values())
    print(f"[supabase] 완료 → app/static/column_notes.json ({n} 컬럼)")


def rebuild_supabase_notes() -> None:
    """로그의 프로파일을 재사용(재프로파일링 없음)해 간결 설명만 재생성.

    산출: app/static/column_notes.json — 신포맷 {table: {col: {"d": 설명, "ex": [샘플<=2]}}}
    (M-Schema 조립용: 설명 + 예시값. metadata_repository 가 소비)
    """
    log_path = config.BENCH_DIR / "metadata_supabase_log.jsonl"
    if not log_path.exists():
        raise SystemExit("metadata_supabase_log.jsonl 없음 — 먼저 supabase 모드 실행")
    profs: dict[tuple, dict] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            o = json.loads(line)
            if not o.get("error") and o.get("profile"):
                profs[(o["table"], o["column"])] = o["profile"]
    print(f"[notes] 프로파일 {len(profs)}개 → 간결 설명 재생성 (병렬 {WORKERS})")

    notes: dict[str, dict] = {}
    lock = Lock()
    def work(item):
        (t, c), prof = item
        try:
            _, res = _describe("supabase", t, c, prof, [])
            desc = res.text.strip()
        except Exception as e:  # noqa: BLE001
            print(f"  실패 {t}.{c}: {str(e)[:80]}"); return
        ex = [_truncate_sample(s) for s in prof.get("samples", [])[:2] if s]
        with lock:
            notes.setdefault(t, {})[c] = {"d": desc, "ex": ex}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        list(pool.map(work, list(profs.items())))

    out = config.BENCH_DIR.parent / "app/static/column_notes.json"
    out.write_text(json.dumps(notes, ensure_ascii=False, indent=1), encoding="utf-8")
    n = sum(len(v) for v in notes.values())
    print(f"[notes] 완료 → app/static/column_notes.json ({n} 컬럼, 신포맷 d/ex)")


def main() -> None:
    if not llm.settings.upstage_api_key:  # type: ignore[attr-defined]
        raise SystemExit("UPSTAGE_API_KEY 필요")
    args = sys.argv[1:]
    if args and args[0] == "supabase-notes":
        global META_DESC_SYS
        META_DESC_SYS = META_DESC_SYS_KO
        rebuild_supabase_notes()
        return
    if args and args[0] == "supabase":
        build_supabase()
        return
    if not (BIRD_ROOT / "mini_dev_sqlite.json").exists():
        raise SystemExit("BIRD MiniDev 없음 — bench/bird/ 확인")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    if not args or args[0] != "bird":
        raise SystemExit("사용법: uv run python -m bench.build_metadata bird|supabase [db_id ...]")
    dbs = args[1:] or bird_dbs()
    print(f"대상 {len(dbs)} DB: {dbs}")
    for d in dbs:
        build_db(d)
    print("\n전체 완료.")


if __name__ == "__main__":
    main()

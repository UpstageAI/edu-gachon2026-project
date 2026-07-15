"""SQL 채점: EM(문자열 정확일치) + EX(실행결과 일치).

EX 가 실질 지표. gold/pred 를 같은 sqlite 에 실행해 결과셋을 비교한다.
결과 비교는 순서 무시(멀티셋)가 기본이며, gold 에 ORDER BY 가 있으면 순서까지 비교한다.

self-test:  uv run python -m bench.evaluate   (pred=gold 로 EM/EX 100% 확인)
"""
from __future__ import annotations

import re
import sqlite3
import time

_FENCE = re.compile(r"```(?:sql)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_WS = re.compile(r"\s+")


def extract_sql(text: str) -> str:
    """모델 응답에서 SQL 한 문장만 추출한다 (코드펜스/설명 제거)."""
    m = _FENCE.search(text)
    body = m.group(1) if m else text
    body = body.strip()
    # 첫 SELECT/WITH 부터 (설명 문장이 앞에 붙는 경우 방지)
    m2 = re.search(r"(?is)\b(select|with)\b", body)
    if m2:
        body = body[m2.start():]
    return body.strip().rstrip(";").strip()


def normalize_sql(sql: str) -> str:
    """EM 용 정규화: 소문자, 공백 축소, 끝 세미콜론/따옴표 제거."""
    s = sql.strip().rstrip(";").strip()
    s = _WS.sub(" ", s)
    return s.lower()


def exact_match(pred: str, gold: str) -> bool:
    return normalize_sql(pred) == normalize_sql(gold)


def _run(sql: str, db_path: str, timeout_s: float):
    """sqlite 실행. (rows, error). 폭주 쿼리는 progress handler 로 중단."""
    con = sqlite3.connect(db_path)
    deadline = time.time() + timeout_s
    # 콜백이 nonzero 반환 시 실행 중단 → 무한/과중 쿼리 가드
    con.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 10_000)
    try:
        rows = con.execute(sql).fetchall()
        return rows, None
    except Exception as e:  # 문법오류/타임아웃/존재하지않는 컬럼 등
        return None, str(e)
    finally:
        con.close()


def _canon(rows):
    # 각 행을 문자열 튜플로 정규화 (타입 차이로 인한 오탐 완화)
    return [tuple("" if v is None else str(v) for v in r) for r in rows]


def exec_match(pred: str, gold: str, db_path: str, timeout_s: float = 5.0):
    """실행결과 일치 여부. 반환: (matched, error_or_None)."""
    g_rows, g_err = _run(gold, db_path, timeout_s)
    if g_err is not None:
        return False, f"gold-error: {g_err}"  # gold 가 안 돌면 채점 불가
    p_rows, p_err = _run(pred, db_path, timeout_s)
    if p_err is not None:
        return False, p_err
    g, p = _canon(g_rows), _canon(p_rows)
    if re.search(r"(?i)\border\s+by\b", gold):
        return g == p, None            # 순서 의미 있음
    return sorted(g) == sorted(p), None  # 순서 무시


# ── 오프라인 self-test (API 불필요) ─────────────────────────────────────
def _self_test() -> None:
    import json
    from bench import config

    if not config.EVAL_SET.exists():
        print("eval_set.json 없음 — 먼저 `uv run python -m bench.build_eval_set` 실행")
        return
    data = json.loads(config.EVAL_SET.read_text(encoding="utf-8"))[:20]
    em_ok = ex_ok = 0
    for r in data:
        db = config.DB_DIR / f"{r['db_id']}.sqlite"
        assert exact_match(r["gold_sql"], r["gold_sql"]), "EM 자기일치 실패"
        em_ok += 1
        matched, err = exec_match(r["gold_sql"], r["gold_sql"], str(db), config.EXEC_TIMEOUT_S)
        assert matched, f"EX 자기일치 실패: {r['id']} {err}"
        ex_ok += 1
    print(f"self-test OK — EM {em_ok}/{len(data)}, EX {ex_ok}/{len(data)} (pred=gold 100% 기대)")


if __name__ == "__main__":
    _self_test()

"""schema-linker 조건 생성: 기존 eval_set 의 스키마 DDL 에 컬럼별 샘플 값을 덧붙인다.

value_retriever(셀 매칭) 대용 — 각 컬럼의 실제 값 예시를 줘서 모델이
"어느 컬럼에 이 값이 들어있는지 / 값 형식이 뭔지" 를 알게 한다.

산출물:
- eval_set_schema.json          (schema-linked, few-shot 없음)
- eval_set_schema_fewshot.json  (schema-linked + few-shot)

실행:  uv run python -m bench.build_schema_linked
"""
from __future__ import annotations

import json
import sqlite3

from bench import config


def _truncate(v, n=30) -> str:
    s = "" if v is None else str(v).replace("\n", " ")
    return s[:n] + "…" if len(s) > n else s


def _value_block(db_path) -> str:
    """각 테이블·컬럼의 distinct 샘플 값 K개를 블록 문자열로."""
    con = sqlite3.connect(db_path)
    lines = []
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            cols = [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]
            for c in cols:
                try:
                    vals = [r[0] for r in con.execute(
                        f'SELECT DISTINCT "{c}" FROM "{t}" '
                        f'WHERE "{c}" IS NOT NULL LIMIT {config.SCHEMA_VALUE_K}')]
                except sqlite3.Error:
                    vals = []
                shown = " | ".join(_truncate(v) for v in vals) if vals else "(비어있음)"
                lines.append(f"{t}.{c}: {shown}")
    finally:
        con.close()
    return "\n".join(lines)


def _join_hints(db_path) -> str:
    """FK 선언 + 공유 id 컬럼 추론으로 조인 경로(다중 테이블일 때만)."""
    con = sqlite3.connect(db_path)
    joins: set[str] = set()
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        if len(tables) < 2:
            return ""
        cols = {t: [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        for t in tables:  # 선언된 FK
            for fk in con.execute(f'PRAGMA foreign_key_list("{t}")'):
                joins.add(f"{t}.{fk[3]} = {fk[2]}.{fk[4]}")
        seen = sorted(tables)  # 공유 id 컬럼 추론
        for i, a in enumerate(seen):
            for b in seen[i + 1:]:
                for c in set(cols[a]) & set(cols[b]):
                    if c.lower().endswith("id") or c.lower().endswith("code"):
                        joins.add(f"{a}.{c} = {b}.{c}")
    finally:
        con.close()
    return "\n".join(sorted(joins))


def _enrich(records: list[dict]) -> list[dict]:
    vcache: dict[str, str] = {}
    jcache: dict[str, str] = {}
    out = []
    for r in records:
        db = r["db_id"]
        path = config.DB_DIR / f"{db}.sqlite"
        if db not in vcache:
            vcache[db] = _value_block(path)
            jcache[db] = _join_hints(path)
        schema = f"{r['schema']}\n\n# Column sample values\n{vcache[db]}"
        if jcache[db]:
            schema += f"\n\n# 조인(FK)\n{jcache[db]}"
        out.append({**r, "schema": schema})
    return out


def main() -> None:
    base = json.loads(config.EVAL_SET.read_text(encoding="utf-8"))
    fewshot = json.loads(config.CONDITIONS["few"][0].read_text(encoding="utf-8"))

    for records, out_path in [
        (base, config.CONDITIONS["schema"][0]),
        (fewshot, config.CONDITIONS["schema_few"][0]),
    ]:
        enriched = _enrich(records)
        out_path.write_text(json.dumps(enriched, ensure_ascii=False, indent=2), encoding="utf-8")
        avg_len = sum(len(r["schema"]) for r in enriched) / len(enriched)
        print(f"{len(enriched)} 문항 → {out_path.name} (평균 스키마 {avg_len:.0f}자)")


if __name__ == "__main__":
    main()

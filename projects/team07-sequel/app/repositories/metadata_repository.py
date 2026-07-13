"""metadata_repository — 오프라인 프로파일링 산출물로 M-Schema 블록을 만든다.

M-Schema(XiYan-SQL, arXiv 2411.08599): DDL 대신 컬럼당 한 줄
`(col: type, 간결설명, ex: 값)` 반구조 포맷. DDL 대비 4개 모델 평균 +2.03%
이면서 더 컴팩트(기존 DDL+설명 2중 구조는 컬럼명이 전부 중복돼 82% 낭비였음).

소스: app/static/column_notes.json — {table: {col: {"d": 설명, "ex": [샘플]}}}
      (bench/build_metadata.py supabase-notes 산출)

입력: tables(list[str])
출력: M-Schema 텍스트 블록 (메타데이터 없는 DB — 평가용 sqlite 등 — 면 "" → DDL 폴백)
"""
from __future__ import annotations

import json
from pathlib import Path

from app.repositories import schema_repository

_PATH = Path(__file__).resolve().parents[1] / "static/column_notes.json"
_cache: dict | None = None


def mschema(tables: list[str]) -> str:
    """링크된 테이블들의 M-Schema. 테이블명 매칭이라 다른 DB 엔 자연히 ""."""
    global _cache
    if _cache is None:
        _cache = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.exists() else {}
    if not any(t in _cache for t in tables):
        return ""
    lines: list[str] = []
    for t in tables:
        info = _cache.get(t, {})
        lines.append(f"# Table: {t}")
        for name, dtype in schema_repository.get_columns(t):
            m = info.get(name)
            if m and isinstance(m, dict):
                ex = ", ".join(v for v in m.get("ex", [])[:2] if v)
                desc = m.get("d", "")
                lines.append(f"({name}: {dtype}, {desc}" + (f", ex: {ex})" if ex else ")"))
            else:
                lines.append(f"({name}: {dtype})")
        lines.append("")
    return "\n".join(lines).strip()

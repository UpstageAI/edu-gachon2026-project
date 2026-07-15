"""schema_retriever 도구 — 양방향 임베딩 union + elbow 컷 + FK 보강.

- 양방향: 질문↔테이블 + 질문↔컬럼 을 따로 검색해 union (놓침 감소).
  테이블 점수 = max(테이블 sim, 그 테이블의 최고 컬럼 sim).
- elbow: 고정 k 대신 랭킹 점수 급락 지점에서 컷(질문마다 적응적). recall 우선이라
  min_k 는 넉넉히(테이블 하나 빠지면 SQL 불가, 여분은 무시되면 그만).
- FK 보강: 선택 후 조인 경로/브릿지 테이블 추가(마진과 무관, 필수).

읽기전용 DB라 pgvector 불가 → 인메모리 인덱스(1회). 튜닝값은 settings.link_*.
절대 임계 없음(query/passage 코사인이 낮아 랭킹만 신뢰).
TODO(확장): 다중 DB·대형 스키마 시 LSH/pgvector, 컬럼 설명 추가. TODO: score 를 Langfuse 로깅.

입력: question(정규화 질문 권장)
출력: SchemaRetrievalResult(tables, ddl, joins)
"""
from __future__ import annotations

from itertools import combinations

import numpy as np

from app.core import embeddings
from app.core.db import current_db_key
from app.core.settings import settings
from app.repositories import schema_repository
from app.tools.schemas import SchemaRetrievalResult

_MAX_BRIDGE = 2
_indices: dict[str, dict] = {}  # db_key -> 인메모리 인덱스


def _idlike(cols: set[str]) -> set[str]:
    return {c for c in cols if c.endswith("_id") or c.endswith("_prefix")}


def _norm(m) -> np.ndarray:
    m = np.asarray(m, dtype=float)
    return m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)


def _build_index() -> dict:
    tables = schema_repository.list_tables()
    cols = {t: [c for c, _ in schema_repository.get_columns(t)] for t in tables}
    tvecs = _norm(embeddings.embed_passages([f"{t}: {', '.join(cols[t])}" for t in tables]))
    col_items = [(t, c) for t in tables for c in cols[t]]
    cvecs = _norm(embeddings.embed_passages([f"{t}.{c}" for t, c in col_items]))
    return {"tables": tables, "cols": cols, "tvecs": tvecs, "col_items": col_items, "cvecs": cvecs}


def _get_index() -> dict:
    key = current_db_key()
    idx = _indices.get(key)
    if idx is None:
        idx = _build_index()          # 임베딩 호출 — 락 밖에서 (DB별 병렬 허용)
        _indices.setdefault(key, idx)
        idx = _indices[key]
    return idx


def _elbow(ranked: list[str], score: dict[str, float]) -> list[str]:
    lo = min(settings.link_table_min_k, len(ranked))
    hi = min(len(ranked), settings.link_table_max_k)
    k = lo
    for i in range(lo, hi):
        if score[ranked[i - 1]] - score[ranked[i]] > settings.link_elbow_gap:
            break
        k = i + 1
    return ranked[:k]


def _augment(selected: list[str], cols: dict[str, list[str]]) -> list[str]:
    """id 컬럼을 2개 이상 선택 테이블과 공유하는 브릿지 테이블 추가."""
    result, chosen, added = list(selected), set(selected), 0
    for t, tcols in cols.items():
        if t in chosen or added >= _MAX_BRIDGE:
            continue
        tids = _idlike(set(tcols))
        if sum(1 for s in selected if tids & _idlike(set(cols[s]))) >= 2:
            result.append(t)
            chosen.add(t)
            added += 1
    return result


def _infer_joins(tables: list[str], cols: dict[str, list[str]]) -> list[str]:
    joins = []
    for a, b in combinations(tables, 2):
        for c in _idlike(set(cols[a]) & set(cols[b])):
            joins.append(f"{a}.{c} = {b}.{c}")
    return joins


def retrieve_schema(question: str) -> SchemaRetrievalResult:
    # 소형 스키마는 전체가 컨텍스트에 들어감 → 임베딩 축소가 recall 손실만 냄(BIRD ablation -2.9pp).
    all_tables = schema_repository.list_tables()
    if len(all_tables) <= settings.link_full_schema_max:
        cols = {t: [c for c, _ in schema_repository.get_columns(t)] for t in all_tables}
        return SchemaRetrievalResult(
            tables=all_tables,
            ddl=schema_repository.get_ddl(all_tables),
            joins=_infer_joins(all_tables, cols),
        )

    idx = _get_index()
    q = np.asarray(embeddings.embed_query(question), dtype=float)
    q /= np.linalg.norm(q) + 1e-9
    tsims = idx["tvecs"] @ q
    csims = idx["cvecs"] @ q

    col_best: dict[str, float] = {}
    for (t, _c), s in zip(idx["col_items"], csims):
        col_best[t] = max(col_best.get(t, -1.0), float(s))
    combined = {t: max(float(tsims[i]), col_best.get(t, -1.0)) for i, t in enumerate(idx["tables"])}
    ranked = sorted(idx["tables"], key=lambda t: -combined[t])

    selected = _augment(_elbow(ranked, combined), idx["cols"])  # elbow → FK 보강(필수)
    joins = _infer_joins(selected, idx["cols"])
    return SchemaRetrievalResult(tables=selected, ddl=schema_repository.get_ddl(selected), joins=joins)

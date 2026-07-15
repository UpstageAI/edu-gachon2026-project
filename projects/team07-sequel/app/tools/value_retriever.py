"""value_retriever 도구 — 키워드를 실제 DB 값으로 해소.

폴백 체인: exact → synonym → fuzzy → embedding → not_found.
임베딩 단계(폴백에 도달한 hard case)만 컬럼 카디널리티로 다르게 판단:
  - enum 컬럼(유니크 <= link_enum_max_card): top-1 랭킹만(마진 불필요)
  - free-text: top1-top2 마진 >= value_emb_margin 이면 확정,
    미달이면 **버리지 않고** how="ambiguous" + candidates(top-2)로 되묻기 노출
  - sim < value_emb_floor: 정답 자체가 없다고 보고 통과시키지 않음(→ not_found)

튜닝값은 settings.value_*/link_enum_max_card (상수 박지 않음).
TODO: score 분포를 Langfuse 로깅해 재캘리브레이션. 회귀: tests/eval_linker.py.
TODO(성능): categorical 값·임베딩을 앱 시작 시 1회 인덱싱(현재 최초 요청 시 lazy 캐시).

입력: keywords(list[str]), tables(list[str])
출력: ValueRetrievalResult(hints, unresolved)
"""
from __future__ import annotations

import numpy as np
from rapidfuzz import fuzz, process

from app.core import embeddings
from app.core.db import current_db_key
from app.core.settings import settings
from app.repositories import schema_repository, value_repository
from app.tools.schemas import ValueHint, ValueRetrievalResult

# 사내 용어 → 실제 저장값. 늘면 임베딩으로 대체/보완.
SYNONYMS = {
    "취소": "canceled", "해지": "canceled",
    "배송완료": "delivered", "배송 완료": "delivered",
    "배송중": "shipped", "발송": "shipped",
}
_TEXT_TYPES = {"text", "character varying", "varchar", "character", "char"}
_cat_cache: dict[str, list[str]] = {}       # key -> categorical values ([] = 고카디널리티)
_emb_cache: dict[str, np.ndarray] = {}      # key -> 정규화된 값 임베딩 행렬
_name_cache: dict[str, np.ndarray] = {}     # key -> 컬럼명("t.c") 임베딩 (컬럼개념 필터용)

# normalizer 가 (프롬프트 위반으로) 구(clause)를 뽑아도 셀 값과 억지 매칭하지 않기 위한 방어적 가드.
# 너무 길거나(구/문장) 너무 짧은(1자, 조사 잔재 등) 키워드는 fuzzy/embedding 매칭을 스킵 → unresolved.
_MAX_KEYWORD_WORDS = 3
_MIN_KEYWORD_CHARS = 2


def _matchable(keyword: str) -> bool:
    return _MIN_KEYWORD_CHARS <= len(keyword) and len(keyword.split()) <= _MAX_KEYWORD_WORDS


def _is_text(dtype: str) -> bool:
    d = dtype.lower()
    return any(x in d for x in ("text", "char", "clob", "string"))


def _categorical(tables: list[str]) -> dict[str, list[str]]:
    dbk = current_db_key()
    out: dict[str, list[str]] = {}
    for t in tables:
        for name, dtype in schema_repository.get_columns(t):
            if not _is_text(dtype):
                continue
            colkey = f"{t}.{name}"
            ck = f"{dbk}::{colkey}"  # DB별 캐시 격리
            if ck not in _cat_cache:
                vals = value_repository.sample_values(t, name, settings.value_cat_limit + 1)
                _cat_cache[ck] = [str(v) for v in vals] if len(vals) <= settings.value_cat_limit else []
            if _cat_cache[ck]:
                out[colkey] = _cat_cache[ck]
    return out


def _emb(colkey: str, values: list[str]) -> np.ndarray:
    ck = f"{current_db_key()}::{colkey}"
    if ck not in _emb_cache:
        m = np.asarray(embeddings.embed_passages(values), dtype=float)
        _emb_cache[ck] = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    return _emb_cache[ck]


def _colname_vecs(colkeys: list[str]) -> np.ndarray:
    """catmap 컬럼명("t.c") 임베딩 행렬 (DB별 캐시). 컬럼개념 키워드 판별용."""
    dbk = current_db_key()
    missing = [k for k in colkeys if f"{dbk}::{k}" not in _name_cache]
    if missing:
        m = np.asarray(embeddings.embed_passages(missing), dtype=float)
        m = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
        for k, v in zip(missing, m):
            _name_cache[f"{dbk}::{k}"] = v
    return np.stack([_name_cache[f"{dbk}::{k}"] for k in colkeys])


def _embed_match(keyword: str, catmap: dict[str, list[str]]) -> ValueHint | None:
    qv = np.asarray(embeddings.embed_query(keyword), dtype=float)
    qv /= np.linalg.norm(qv) + 1e-9
    best: tuple | None = None  # (s1, key, value, candidates, how)
    for key, vals in catmap.items():
        sims = _emb(key, vals) @ qv
        order = np.argsort(-sims)
        s1 = float(sims[order[0]])
        s2 = float(sims[order[1]]) if len(order) > 1 else -1.0
        if s1 < settings.value_emb_floor:      # 정답 없음 방어
            continue
        enum = len(vals) <= settings.link_enum_max_card
        if enum or (s1 - s2) >= settings.value_emb_margin:
            cand = (s1, key, vals[order[0]], [], "embedding")
        else:                                  # 근접 후보 둘 → 되묻기
            cand = (s1, key, vals[order[0]], [vals[int(order[1])]], "ambiguous")
        if best is None or s1 > best[0]:
            best = cand
    if best is None:
        return None
    s1, key, val, cands, how = best
    # 컬럼개념 필터: 키워드가 최고 셀 값보다 어떤 컬럼명에 더 가까우면(+margin)
    # 값 리터럴이 아니라 스키마 개념("발행 연도" 등) → 억지 매칭하지 않고 통과.
    col_sim = float(np.max(_colname_vecs(list(catmap)) @ qv))
    if col_sim >= s1 + settings.value_colname_margin:
        return None
    return ValueHint(keyword=keyword, column=key, value=val, how=how, score=round(s1, 3), candidates=cands)


def retrieve_values(keywords: list[str], tables: list[str]) -> ValueRetrievalResult:
    if not keywords:
        return ValueRetrievalResult()
    catmap = _categorical(tables)

    # 키(원문·소문자) → (컬럼, 실제 저장값). 소문자 매칭이어도 DB 원본 대소문자를 돌려줘야
    # Postgres 대소문자 구분 비교에서 결과를 놓치지 않는다("canceled" 입력, 저장값 "Canceled").
    exact_idx: dict[str, tuple[str, str]] = {}
    for key, vals in catmap.items():
        for v in vals:
            exact_idx.setdefault(v, (key, v))
            exact_idx.setdefault(v.lower(), (key, v))

    hints: list[ValueHint] = []
    unresolved: list[str] = []
    for kw in keywords:
        # 1) exact
        if hit := (exact_idx.get(kw) or exact_idx.get(kw.lower())):
            col, val = hit
            hints.append(ValueHint(keyword=kw, column=col, value=val, how="exact"))
            continue
        # 2) synonym
        syn = SYNONYMS.get(kw)
        if syn and (hit := (exact_idx.get(syn) or exact_idx.get(syn.lower()))):
            col, val = hit
            hints.append(ValueHint(keyword=kw, column=col, value=val, how="synonym"))
            continue
        # 구(clause)/과도하게 짧은 키워드는 fuzzy·embedding 매칭 대상에서 제외(오매칭 방지)
        if not _matchable(kw):
            unresolved.append(kw)
            continue
        # 3) fuzzy (주로 한국어-한국어 오타/변형)
        best = None
        for key, vals in catmap.items():
            m = process.extractOne(kw, vals, scorer=fuzz.WRatio)
            if m and (best is None or m[1] > best[1]):
                best = (key, m[1], m[0])
        if best and best[1] >= settings.value_fuzzy_min:
            hints.append(ValueHint(keyword=kw, column=best[0], value=best[2], how="fuzzy", score=best[1]))
            continue
        # 4) embedding (카디널리티 인지 + floor + ambiguous)
        if catmap and (h := _embed_match(kw, catmap)):
            hints.append(h)
            continue
        # 5) not_found → 되묻기
        unresolved.append(kw)

    return ValueRetrievalResult(hints=hints, unresolved=unresolved)

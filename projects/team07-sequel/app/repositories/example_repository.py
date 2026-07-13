"""example_repository — few-shot 예시(질문→SQL) 풀 접근.

파인튜닝 대신 in-context few-shot. 벤치 근거: 정확도 최대 단일 레버
(한국어 zero 31%→few 73%, BIRD leave-one-out −10.8pp).

풀: app/static/examples.json (실행 검증된 시드 26개). 실전에선 승인된
쿼리 로그·SQL-to-text 역생성으로 풀이 늘어난다 — 파일에 추가하면 끝.
검색: solar-embedding 유사도 top-k (풀 임베딩은 프로세스당 1회 lazy 캐시).

입력: question(str), k(int)
출력: [{"question": str, "sql": str}, ...] 유사 예시 top-k (풀 없거나 임베딩 실패 시 [])
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.core import embeddings

_PATH = Path(__file__).resolve().parents[1] / "static/examples.json"
_pool: list[dict] | None = None
_vecs: np.ndarray | None = None


def _load() -> None:
    global _pool, _vecs
    if _pool is not None:
        return
    pool = json.loads(_PATH.read_text(encoding="utf-8")) if _PATH.exists() else []
    if pool:
        m = np.asarray(embeddings.embed_passages([e["question"] for e in pool]), dtype=float)
        _vecs = m / (np.linalg.norm(m, axis=1, keepdims=True) + 1e-9)
    _pool = pool  # 임베딩 성공 후 마지막에 세팅 — 중간에 예외 나면 다음 호출이 재시도하게


def retrieve_examples(question: str, k: int = 3) -> list[dict]:
    try:
        _load()
        if not _pool:
            return []
        q = np.asarray(embeddings.embed_query(question), dtype=float)
        q /= np.linalg.norm(q) + 1e-9
        order = np.argsort(-(_vecs @ q))[:k]
        return [{"question": _pool[i]["question"], "sql": _pool[i]["sql"]} for i in order]
    except Exception:  # noqa: BLE001 — few-shot 은 부가 기능: 실패해도 생성은 진행
        return []

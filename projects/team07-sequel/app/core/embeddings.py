"""Upstage Solar 임베딩 클라이언트 — 스키마/값 링킹용.

- solar-embedding-2-query   : 질문(검색 query 측) 임베딩
- solar-embedding-2-passage : 스키마/값(문서 passage 측) 임베딩
1024-dim, 8k 컨텍스트. (2026-07-20 까지 무료)

입력: text / list[str]
출력: list[float] / list[list[float]]
"""
from __future__ import annotations

import time

import httpx

from app.core.settings import settings

QUERY_MODEL = "solar-embedding-2-query"
PASSAGE_MODEL = "solar-embedding-2-passage"


_MAX_BATCH = 100      # Upstage embeddings 는 요청당 입력 100개 초과 시 400
_MAX_CHARS = 2000     # 과도하게 긴 입력(블롭 등)은 400 → 안전 절단


def _clean(t: str) -> str:
    """빈/공백 입력은 400 을 유발 → 플레이스홀더, 초장문은 절단(정상 입력엔 영향 없음)."""
    t = (t or "").strip()
    return t[:_MAX_CHARS] if t else "N/A"


def _post_batch(model: str, inputs: list[str]) -> list[list[float]]:
    """입력 <=100 배치 1회 호출 (429 백오프 재시도)."""
    last: Exception | None = None
    for attempt in range(5):  # 레이트리밋(429) 백오프 재시도
        try:
            r = httpx.post(
                f"{settings.upstage_base_url}/embeddings",
                headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
                json={"model": model, "input": inputs},
                timeout=30.0,
            )
            r.raise_for_status()
            data = sorted(r.json()["data"], key=lambda d: d["index"])
            return [d["embedding"] for d in data]
        except httpx.HTTPStatusError as e:
            last = e
            if e.response.status_code == 429:
                delay = 2.0 * (attempt + 1)
                ra = e.response.headers.get("retry-after")
                if ra:
                    try:
                        delay = float(ra)  # 초 단위. HTTP-date 형식이면 파싱 실패 → 백오프 사용
                    except ValueError:
                        pass
                time.sleep(delay)
            else:
                raise
        except httpx.HTTPError as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last  # type: ignore[misc]


def _embed(model: str, inputs: list[str]) -> list[list[float]]:
    """입력 정제(빈/초장문) + 100개 배치 청킹 → 임베딩. 순서 보존.

    wide 스키마(컬럼 100+)·dirty 값에서도 400 안 나게. 정상 소량 입력엔 동작 동일.
    """
    if not inputs:
        return []
    cleaned = [_clean(t) for t in inputs]
    out: list[list[float]] = []
    for i in range(0, len(cleaned), _MAX_BATCH):
        out.extend(_post_batch(model, cleaned[i:i + _MAX_BATCH]))
    return out


def embed_query(text: str) -> list[float]:
    """질문 1개 임베딩 (검색 query 측)."""
    return _embed(QUERY_MODEL, [text])[0]


def embed_passages(texts: list[str]) -> list[list[float]]:
    """문서/값 여러 개 임베딩 (passage 측). 인덱싱용, 배치 호출."""
    return _embed(PASSAGE_MODEL, texts)

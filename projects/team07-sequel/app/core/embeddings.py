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


def _embed(model: str, inputs: list[str]) -> list[list[float]]:
    if not inputs:
        return []
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


def embed_query(text: str) -> list[float]:
    """질문 1개 임베딩 (검색 query 측)."""
    return _embed(QUERY_MODEL, [text])[0]


def embed_passages(texts: list[str]) -> list[list[float]]:
    """문서/값 여러 개 임베딩 (passage 측). 인덱싱용, 배치 호출."""
    return _embed(PASSAGE_MODEL, texts)

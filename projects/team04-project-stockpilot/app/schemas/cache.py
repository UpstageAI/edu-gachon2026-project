"""사업보고서 배치 캐시 결과 스키마."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class CacheModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BusinessReportCacheItem(CacheModel):
    company: str
    status: Literal["cached", "skipped", "failed"]
    source_id: str | None = None
    chunks: int | None = None
    reason: str | None = None


class BusinessReportCacheSummary(CacheModel):
    total: int
    cached: int
    skipped: int
    failed: int
    items: list[BusinessReportCacheItem]

"""CardContent — analyze 노드 structured output = 카드 렌더 슬롯.
   (팀원 core/schemas.py TopicAnalysis/CardArtifact 와는 후속 정합화)"""
from __future__ import annotations

from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class CardContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str                          # GLOBAL|MARKET|DOMESTIC|CRYPTO|FX
    index_no: str = "00"
    subtitle: str = Field(max_length=20)
    headline: str = Field(max_length=20)
    lead: str = Field(max_length=45)
    body: str = Field(max_length=240)
    source: str
    disclaimer: str = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
    image_url: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)

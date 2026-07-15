"""Document Parse·Information Extract 입출력 스키마."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DocumentModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParsedDocument(DocumentModel):
    """Document Parse 또는 로컬 fallback으로 변환된 문서."""

    content: str = Field(min_length=1)
    parser: Literal["upstage-document-parse", "local-fallback"]
    output_format: Literal["markdown", "text"]
    page_count: int = Field(ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BusinessReportFacts(DocumentModel):
    """Information Extract로 사업보고서에서 추출할 핵심 정보."""

    company_name: str | None = Field(
        default=None,
        description="보고서의 회사명",
    )
    report_name: str | None = Field(
        default=None,
        description="사업보고서·분기보고서 등 문서 종류와 대상 기간",
    )
    report_period: str | None = Field(
        default=None,
        description="보고서 대상 기간",
    )
    business_summary: str | None = Field(
        default=None,
        description="회사의 주요 사업을 초보자도 이해할 수 있게 요약한 내용",
    )
    major_products: list[str] = Field(
        default_factory=list,
        description="주요 제품·서비스 목록",
    )
    risk_factors: list[str] = Field(
        default_factory=list,
        description="사업·재무·시장과 관련된 핵심 위험요인",
    )
    lawsuits: list[str] = Field(
        default_factory=list,
        description="중요한 소송·분쟁·우발부채",
    )
    regulatory_actions: list[str] = Field(
        default_factory=list,
        description="규제기관의 제재·행정조치",
    )
    audit_opinion: str | None = Field(
        default=None,
        description="회계감사인의 감사의견",
    )


class PreparedDocument(DocumentModel):
    parsed: ParsedDocument
    facts: BusinessReportFacts | None = None


class DocumentIngestionResult(DocumentModel):
    source_id: str
    chunks_saved: int = Field(ge=1)
    parser: str
    facts_saved: bool


def business_report_response_format() -> dict[str, Any]:
    """Universal Information Extract가 요구하는 JSON Schema 포맷."""
    properties = {
        "company_name": {
            "type": "string",
            "description": "보고서의 회사명. 없으면 빈 문자열",
        },
        "report_name": {
            "type": "string",
            "description": "문서 종류와 대상 기간. 없으면 빈 문자열",
        },
        "report_period": {
            "type": "string",
            "description": "보고서 대상 기간. 없으면 빈 문자열",
        },
        "business_summary": {
            "type": "string",
            "description": "주요 사업을 초보자도 이해할 수 있게 요약한 내용",
        },
        "major_products": {
            "type": "array",
            "items": {"type": "string"},
            "description": "주요 제품·서비스 목록. 없으면 빈 배열",
        },
        "risk_factors": {
            "type": "array",
            "items": {"type": "string"},
            "description": "사업·재무·시장 관련 핵심 위험요인",
        },
        "lawsuits": {
            "type": "array",
            "items": {"type": "string"},
            "description": "중요한 소송·분쟁·우발부채. 없으면 빈 배열",
        },
        "regulatory_actions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "규제기관의 제재·행정조치. 없으면 빈 배열",
        },
        "audit_opinion": {
            "type": "string",
            "description": "회계감사인의 감사의견. 없으면 빈 문자열",
        },
    }
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "business_report_facts",
            "schema": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }

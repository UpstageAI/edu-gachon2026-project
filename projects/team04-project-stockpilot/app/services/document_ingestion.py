"""문서 파싱·정보 추출·RAG 저장을 조율하는 서비스."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.document_ai import (
    extract_business_report_facts,
    parse_document,
    save_document_facts,
)
from app.repositories.rag import ingest_business_report, ingest_text_document
from app.schemas.documents import (
    DocumentIngestionResult,
    PreparedDocument,
)


async def prepare_document(
    path: Path,
    *,
    use_upstage: bool = True,
    fallback_to_local: bool = True,
    extract_facts: bool = False,
) -> PreparedDocument:
    """문서를 RAG 적재 직전 형태로 준비합니다."""
    parsed = await parse_document(
        path,
        use_upstage=use_upstage,
        fallback_to_local=fallback_to_local,
    )
    facts = await extract_business_report_facts(path) if extract_facts else None
    return PreparedDocument(parsed=parsed, facts=facts)


async def ingest_document(
    path: Path,
    *,
    source_id: str,
    metadata: dict[str, Any],
    document_type: str = "general",
    use_upstage: bool = True,
    fallback_to_local: bool = True,
    extract_facts: bool = False,
) -> DocumentIngestionResult:
    """문서를 파싱한 뒤 RAG 청크와 구조화 정보를 저장합니다."""
    prepared = await prepare_document(
        path,
        use_upstage=use_upstage,
        fallback_to_local=fallback_to_local,
        extract_facts=extract_facts,
    )
    enriched_metadata = {
        **metadata,
        "document_parser": prepared.parsed.parser,
        "document_format": prepared.parsed.output_format,
        "page_count": prepared.parsed.page_count,
    }

    if document_type == "business_report":
        saved = await ingest_business_report(
            source_id=source_id,
            content=prepared.parsed.content,
            metadata=enriched_metadata,
        )
    else:
        saved = await ingest_text_document(
            source_id=source_id,
            content=prepared.parsed.content,
            metadata=enriched_metadata,
        )

    if prepared.facts is not None:
        await save_document_facts(
            source_id=source_id,
            facts=prepared.facts,
            metadata=enriched_metadata,
        )

    return DocumentIngestionResult(
        source_id=source_id,
        chunks_saved=saved,
        parser=prepared.parsed.parser,
        facts_saved=prepared.facts is not None,
    )

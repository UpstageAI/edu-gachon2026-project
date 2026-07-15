"""Upstage Document Parse·Information Extract 접근 계층."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup
from loguru import logger
from pypdf import PdfReader

from app.core.config import settings
from app.repositories import get_supabase_client
from app.schemas.documents import (
    BusinessReportFacts,
    ParsedDocument,
    business_report_response_format,
)

_TEXT_SUFFIXES = {".txt", ".md"}
_HTML_SUFFIXES = {".html", ".htm", ".xml"}


async def parse_document(
    path: Path,
    *,
    use_upstage: bool = True,
    fallback_to_local: bool = True,
    loader_factory: Callable[..., Any] | None = None,
) -> ParsedDocument:
    """문서를 Markdown으로 변환하고, API 실패 시 로컬 파서로 대체합니다."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"문서 파일을 찾지 못했습니다: {path}")

    if path.suffix.lower() in _TEXT_SUFFIXES | _HTML_SUFFIXES:
        return await asyncio.to_thread(_parse_local_document, path)

    if use_upstage:
        if not settings.upstage_api_key:
            if not fallback_to_local:
                raise RuntimeError("UPSTAGE_API_KEY가 필요합니다.")
            logger.warning("UPSTAGE_API_KEY 미설정: 로컬 문서 파서로 대체")
        else:
            try:
                return await asyncio.to_thread(
                    _parse_with_upstage,
                    path,
                    loader_factory,
                )
            except Exception as exc:
                if not fallback_to_local:
                    raise
                logger.warning(
                    f"Document Parse 실패({type(exc).__name__}): 로컬 파서로 대체"
                )

    return await asyncio.to_thread(_parse_local_document, path)


async def extract_business_report_facts(
    path: Path,
    *,
    extractor_factory: Callable[..., Any] | None = None,
) -> BusinessReportFacts:
    """Universal Information Extract로 사업보고서 핵심 필드를 추출합니다."""
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"문서 파일을 찾지 못했습니다: {path}")
    if not settings.upstage_api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 필요합니다.")

    if extractor_factory is None:
        from langchain_upstage import UpstageUniversalInformationExtraction

        extractor_factory = UpstageUniversalInformationExtraction

    extractor = extractor_factory(api_key=settings.upstage_api_key)
    result = await extractor.ainvoke(
        {
            "image_urls": [str(path)],
            "response_format": business_report_response_format(),
            "pages_per_chunk": 5,
            "confidence": False,
            "doc_split": False,
            "location": False,
        }
    )
    return BusinessReportFacts.model_validate(result)


async def save_document_facts(
    *,
    source_id: str,
    facts: BusinessReportFacts,
    metadata: dict[str, Any],
) -> None:
    """문서 단위 구조화 정보를 Supabase에 upsert합니다."""
    client = await get_supabase_client()
    await (
        client.table("document_facts")
        .upsert(
            {
                "source_id": source_id,
                "facts": facts.model_dump(mode="json"),
                "metadata": metadata,
                "updated_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="source_id",
        )
        .execute()
    )


def _parse_with_upstage(
    path: Path,
    loader_factory: Callable[..., Any] | None,
) -> ParsedDocument:
    if loader_factory is None:
        from langchain_upstage import UpstageDocumentParseLoader

        loader_factory = UpstageDocumentParseLoader

    loader = loader_factory(
        file_path=path,
        api_key=settings.upstage_api_key,
        split="page",
        output_format="markdown",
        ocr="auto" if path.suffix.lower() == ".pdf" else "force",
        coordinates=False,
    )
    documents = loader.load()
    content = "\n\n".join(document.page_content.strip() for document in documents)
    if not content.strip():
        raise ValueError("Document Parse 결과가 비어 있습니다.")
    return ParsedDocument(
        content=content,
        parser="upstage-document-parse",
        output_format="markdown",
        page_count=max(len(documents), 1),
        metadata={
            "filename": path.name,
            "pages": [document.metadata for document in documents],
            "model": "document-parse",
        },
    )


def _parse_local_document(path: Path) -> ParsedDocument:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        content = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        page_count = max(len(reader.pages), 1)
    elif suffix in _TEXT_SUFFIXES:
        content = path.read_text(encoding="utf-8")
        page_count = 1
    elif suffix in _HTML_SUFFIXES:
        raw = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(raw, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        content = soup.get_text("\n")
        page_count = 1
    else:
        raise ValueError(f"로컬 fallback이 지원하지 않는 파일 형식입니다: {suffix}")

    content = content.strip()
    if not content:
        raise ValueError(f"문서에서 텍스트를 추출하지 못했습니다: {path.name}")
    return ParsedDocument(
        content=content,
        parser="local-fallback",
        output_format="text",
        page_count=page_count,
        metadata={"filename": path.name},
    )

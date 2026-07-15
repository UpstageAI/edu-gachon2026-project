"""RAG 문서 청킹·임베딩·Supabase pgvector 검색."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from langchain_upstage import UpstageEmbeddings
from loguru import logger
from pypdf import PdfReader

from app.core.config import settings
from app.repositories import get_supabase_client

_HEADING_RE = re.compile(
    r"^(?:제\s*\d+\s*[장절]\b|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.\s*|"
    r"[IVX]{1,8}\.\s+|\d{1,2}\.\s+\S|[가-하]\.\s+\S)"
)
_KNOWN_HEADINGS = (
    "회사의 개요",
    "사업의 내용",
    "사업의 개요",
    "주요 제품 및 서비스",
    "위험요인",
    "위험 요인",
    "재무에 관한 사항",
)
_RISK_SECTION_KEYWORDS = (
    "재무위험관리",
    "우발부채와 약정사항",
    "중요한 소송사건",
    "제재현황",
    "경영진단",
    "유동성 및 자금조달",
    "회계감사인의 감사의견",
    "파생상품 및 위험관리정책",
    "파생상품 및 풋백옵션",
    "법규상의 규제",
    "환경 관련 규제",
    "중요한 회계추정",
    "충당부채",
    "사채관리계약",
    "재무제표 재작성",
)
MAX_BUSINESS_REPORT_CHUNKS = 80
MIN_RISK_CHUNKS = 20


def get_embeddings() -> UpstageEmbeddings:
    if not settings.upstage_api_key:
        raise RuntimeError("UPSTAGE_API_KEY가 필요합니다.")
    return UpstageEmbeddings(
        api_key=settings.upstage_api_key,
        model=settings.embedding_model,
    )


def chunk_document(
    content: str,
    *,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None,
) -> list[dict]:
    """공시의 장·절 제목을 보존하면서 본문을 문자 단위로 청킹합니다."""
    chunk_size = chunk_size or settings.rag_chunk_size
    chunk_overlap = (
        settings.rag_chunk_overlap if chunk_overlap is None else chunk_overlap
    )
    if chunk_size <= 0:
        raise ValueError("chunk_size는 양수여야 합니다.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap은 0 이상 chunk_size 미만이어야 합니다.")

    sections = _split_sections(_normalize_text(content))
    chunks: list[dict] = []
    for section, lines in sections:
        section_text = "\n".join(lines).strip()
        start = 0
        while start < len(section_text):
            end = min(start + chunk_size, len(section_text))
            if end < len(section_text):
                boundary = max(
                    section_text.rfind("\n", start, end),
                    section_text.rfind("다. ", start, end),
                    section_text.rfind(". ", start, end),
                )
                if boundary > start + chunk_size // 2:
                    end = boundary + (
                        2 if section_text[boundary : boundary + 2] == "다." else 1
                    )
            piece = section_text[start:end].strip()
            if piece:
                chunks.append(_make_chunk(len(chunks), section, piece))
            if end >= len(section_text):
                break
            start = max(end - chunk_overlap, start + 1)

    chunks = _merge_small_chunks(chunks, chunk_size=chunk_size)
    if not chunks:
        raise ValueError("청크로 만들 수 있는 본문이 없습니다.")
    return chunks


def load_local_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        return _normalize_text(
            "\n".join(page.extract_text() or "" for page in reader.pages)
        )
    if suffix in {".txt", ".md"}:
        return _normalize_text(path.read_text(encoding="utf-8"))
    raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")


def load_glossary(path: Path) -> list[dict]:
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("glossary.json 최상위 값은 배열이어야 합니다.")
    required = {"term", "definition"}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict) or not required.issubset(entry):
            raise ValueError(f"용어 {index}에 term 또는 definition이 없습니다.")
    return entries


async def ingest_glossary(path: Path) -> int:
    entries = load_glossary(path)
    chunks = []
    for index, entry in enumerate(entries):
        aliases = ", ".join(entry.get("aliases", []))
        content = f"용어: {entry['term']}\n뜻: {entry['definition']}"
        if aliases:
            content += f"\n비슷한 표현: {aliases}"
        if entry.get("example"):
            content += f"\n초보자 예시: {entry['example']}"
        chunks.append(
            {
                "chunk_index": index,
                "section": entry["term"],
                "content": content,
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                "metadata": {
                    "term": entry["term"],
                    "aliases": entry.get("aliases", []),
                    "source_url": entry.get("source_url"),
                },
            }
        )
    return await save_chunks(
        source_id="glossary:v1",
        chunks=chunks,
        base_metadata={
            "source_type": "glossary",
            "title": "초보 투자자를 위한 투자 용어 사전",
            "status": "active",
        },
    )


async def ingest_text_document(
    *,
    source_id: str,
    content: str,
    metadata: dict[str, Any],
) -> int:
    chunks = chunk_document(content)
    return await save_chunks(
        source_id=source_id,
        chunks=chunks,
        base_metadata=metadata,
    )


async def ingest_business_report(
    *,
    source_id: str,
    content: str,
    metadata: dict[str, Any],
) -> int:
    """사업보고서에서 사업 설명 영역만 선별해 적재합니다."""
    chunks = select_business_report_chunks(chunk_document(content))
    return await save_chunks(
        source_id=source_id,
        chunks=chunks,
        base_metadata=metadata,
    )


def select_business_report_chunks(chunks: list[dict]) -> list[dict]:
    """사업 설명과 문서 후반의 핵심 위험 섹션을 함께 선택합니다."""
    start = next(
        (
            index
            for index, chunk in enumerate(chunks)
            if "사업의 개요" in chunk["section"]
        ),
        None,
    )
    if start is None:
        logger.warning("사업의 개요 경계를 찾지 못해 앞쪽 100개 청크만 적재합니다.")
        business_chunks = chunks[:100]
    else:
        end_markers = ("요약연결재무정보", "요약재무정보", "연결재무제표")
        end = next(
            (
                index
                for index, chunk in enumerate(chunks[start + 1 :], start + 1)
                if any(marker in chunk["section"] for marker in end_markers)
            ),
            min(len(chunks), start + 100),
        )
        business_chunks = chunks[start:end]

    risk_chunks = [
        chunk
        for chunk in chunks
        if any(keyword in chunk["section"] for keyword in _RISK_SECTION_KEYWORDS)
    ]
    selected_ids = {id(chunk) for chunk in business_chunks + risk_chunks}
    selected = [chunk for chunk in chunks if id(chunk) in selected_ids]

    if not selected:
        raise ValueError("사업보고서에서 적재할 사업 내용 청크를 찾지 못했습니다.")

    if len(selected) > MAX_BUSINESS_REPORT_CHUNKS:
        required_risk_ids = {id(chunk) for chunk in risk_chunks[:MIN_RISK_CHUNKS]}
        remaining_slots = MAX_BUSINESS_REPORT_CHUNKS - len(required_risk_ids)
        fill_ids = [
            id(chunk) for chunk in selected if id(chunk) not in required_risk_ids
        ][:remaining_slots]
        limited_ids = required_risk_ids | set(fill_ids)
        selected = [chunk for chunk in selected if id(chunk) in limited_ids]

    for index, chunk in enumerate(selected):
        chunk["chunk_index"] = index
    logger.info(
        "사업보고서 핵심 영역 선별: "
        f"전체={len(chunks)}, 사업={len(business_chunks)}, "
        f"위험={len(risk_chunks)}, 중복제거후={len(selected)} chunks"
    )
    return selected


async def save_chunks(
    *,
    source_id: str,
    chunks: list[dict],
    base_metadata: dict[str, Any],
) -> int:
    embeddings = get_embeddings()
    texts = [chunk["content"] for chunk in chunks]
    vectors: list[list[float]] = []
    logger.info(
        f"Solar 임베딩 시작: {len(texts)} chunks, "
        f"batch_size={settings.rag_embedding_batch_size}"
    )
    for start in range(0, len(texts), settings.rag_embedding_batch_size):
        batch = texts[start : start + settings.rag_embedding_batch_size]
        batch_vectors = await _embed_batch_with_retry(embeddings, batch)
        vectors.extend(batch_vectors)
        logger.info(
            f"Solar 임베딩 진행: {min(start + len(batch), len(texts))}/{len(texts)}"
        )
    if vectors and len(vectors[0]) != settings.embedding_dimension:
        raise RuntimeError(
            "임베딩 차원 불일치: "
            f"expected={settings.embedding_dimension}, actual={len(vectors[0])}"
        )

    rows = [
        {
            "source_id": source_id,
            "chunk_index": chunk["chunk_index"],
            "content": chunk["content"],
            "embedding": vector,
            "metadata": {
                **base_metadata,
                **chunk.get("metadata", {}),
                "section": chunk["section"],
                "content_hash": chunk["content_hash"],
            },
        }
        for chunk, vector in zip(chunks, vectors, strict=True)
    ]
    client = await get_supabase_client()
    for start in range(0, len(rows), 50):
        await (
            client.table("documents")
            .upsert(
                rows[start : start + 50],
                on_conflict="source_id,chunk_index",
            )
            .execute()
        )
    await (
        client.table("documents")
        .delete()
        .eq("source_id", source_id)
        .gte("chunk_index", len(rows))
        .execute()
    )
    logger.info(f"RAG 적재 완료: source_id={source_id}, chunks={len(rows)}")
    return len(rows)


async def source_exists(source_id: str) -> bool:
    """동일한 원문이 이미 RAG 테이블에 적재됐는지 확인합니다."""
    client = await get_supabase_client()
    result = await (
        client.table("documents")
        .select("id")
        .eq("source_id", source_id)
        .limit(1)
        .execute()
    )
    return bool(result.data)


async def _embed_batch_with_retry(
    embeddings: UpstageEmbeddings,
    batch: list[str],
    *,
    attempts: int = 3,
) -> list[list[float]]:
    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(
                embeddings.aembed_documents(batch),
                timeout=120,
            )
        except Exception as exc:
            if attempt == attempts:
                raise
            logger.warning(
                f"임베딩 배치 실패({type(exc).__name__}), {attempt}/{attempts}회 재시도"
            )
            await asyncio.sleep(2 ** (attempt - 1))
    raise RuntimeError("임베딩 재시도 횟수를 초과했습니다.")


async def search_documents(
    query: str,
    top_k: int = 4,
    *,
    corp_code: str | None = None,
    source_type: str | None = None,
    threshold: float = 0.3,
) -> list[dict]:
    """팀원 A의 rag_node가 호출할 검색 인터페이스."""
    if not query.strip():
        return []
    query_embedding = await get_embeddings().aembed_query(query)
    client = await get_supabase_client()
    result = await client.rpc(
        "match_documents",
        {
            "query_embedding": query_embedding,
            "match_count": top_k,
            "match_threshold": threshold,
            "filter_corp_code": corp_code,
            "filter_source_type": source_type,
        },
    ).execute()
    return result.data or []


class RAGRepository:
    async def search_similar(
        self,
        query: str,
        *,
        k: int = 4,
        corp_code: str | None = None,
        source_type: str | None = None,
        threshold: float = 0.3,
    ) -> list[dict]:
        return await search_documents(
            query,
            top_k=k,
            corp_code=corp_code,
            source_type=source_type,
            threshold=threshold,
        )


_rag_repository: RAGRepository | None = None


def get_rag_repository() -> RAGRepository:
    global _rag_repository
    if _rag_repository is None:
        _rag_repository = RAGRepository()
    return _rag_repository


def _normalize_text(text: str) -> str:
    lines: list[str] = []
    previous = ""
    for raw_line in text.replace("\u00a0", " ").replace("\u200b", "").splitlines():
        line = re.sub(r"[ \t]+", " ", raw_line).strip()
        if not line or line == previous or re.fullmatch(r"-?\s*\d+\s*-?", line):
            continue
        lines.append(line)
        previous = line
    return "\n".join(lines)


def _is_heading(line: str) -> bool:
    normalized = re.sub(r"^#{1,6}\s*", "", line).strip()
    if len(normalized) > 100:
        return False
    compact = normalized.replace(" ", "")
    return bool(_HEADING_RE.match(normalized)) or any(
        heading.replace(" ", "") in compact for heading in _KNOWN_HEADINGS
    )


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    title = "본문"
    lines: list[str] = []
    for line in text.splitlines():
        if _is_heading(line):
            if lines:
                sections.append((title, lines))
            title = re.sub(r"^#{1,6}\s*", "", line).strip()[:100]
            lines = []
        else:
            lines.append(line)
    if lines:
        sections.append((title, lines))
    return sections or [("본문", text.splitlines())]


def _make_chunk(index: int, section: str, content: str) -> dict:
    return {
        "chunk_index": index,
        "section": section,
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "metadata": {},
    }


def _merge_small_chunks(chunks: list[dict], *, chunk_size: int) -> list[dict]:
    merged: list[dict] = []
    for chunk in chunks:
        if (
            merged
            and len(merged[-1]["content"]) < 80
            and len(merged[-1]["content"]) + len(chunk["content"]) + 1 <= chunk_size
        ):
            prefix = merged.pop()["content"]
            chunk["content"] = f"{prefix}\n{chunk['content']}"
            chunk["content_hash"] = hashlib.sha256(
                chunk["content"].encode()
            ).hexdigest()
        elif (
            merged
            and len(chunk["content"]) < 80
            and len(merged[-1]["content"]) + len(chunk["content"]) + 1 <= chunk_size
        ):
            merged[-1]["content"] += f"\n{chunk['content']}"
            merged[-1]["content_hash"] = hashlib.sha256(
                merged[-1]["content"].encode()
            ).hexdigest()
            continue
        merged.append(chunk)
    for index, chunk in enumerate(merged):
        chunk["chunk_index"] = index
    return merged

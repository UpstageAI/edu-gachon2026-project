"""Structured investment glossary storage and lookup.

The vector RAG table is still useful for fuzzy explanations, but glossary terms
are dictionary-like data.  This repository keeps them in a dedicated Supabase
table so tools can do exact/alias lookup before falling back to document RAG.
"""

from __future__ import annotations

from datetime import UTC, datetime
from functools import lru_cache
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from loguru import logger

from app.core.config import settings
from app.repositories import get_supabase_client


NAVER_ENCYC_URL = "https://openapi.naver.com/v1/search/encyc.json"

GLOSSARY_COLUMNS = (
    "id,term,definition,category,aliases,difficulty,example,source_url,metadata,"
    "created_at,updated_at"
)

_INVESTMENT_RESEARCH_HINTS = (
    "주식",
    "증권",
    "투자",
    "상장",
    "공모",
    "청약",
    "IPO",
    "공시",
    "재무",
    "회계",
    "시장",
)

_SPECIAL_TERMS_ENDING_WITH_PARTICLE = ("목표주가", "적정주가", "주가")
_DEFINITION_PHRASE = (
    r"뭐야|뭔데|무슨\s*뜻|무슨\s*의미|뭔\s*의미|"
    r"뜻이야|뜻은|뜻|의미야|의미냐고|의미|설명해|설명"
)


def load_glossary_terms(path: Path) -> list[dict[str, Any]]:
    """Load glossary source JSON and validate the minimum contract."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise ValueError("glossary.json must contain a list of term entries.")

    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"glossary entry {index} must be an object.")
        if not entry.get("term") or not entry.get("definition"):
            raise ValueError(f"glossary entry {index} needs term and definition.")
    return entries


@lru_cache(maxsize=1)
def load_local_glossary_rows() -> list[dict[str, Any]]:
    """Load bundled glossary JSON as a safe fallback when Supabase is sparse."""
    path = Path(__file__).resolve().parents[2] / "data" / "glossary.json"
    try:
        return [
            _entry_to_row(entry, updated_at="")
            for entry in load_glossary_terms(path)
        ]
    except Exception as exc:
        logger.warning(f"로컬 용어 사전 로드 실패: {type(exc).__name__}: {exc}")
        return []


async def ingest_glossary_terms(path: Path) -> int:
    """Upsert glossary JSON into the dedicated glossary_terms table."""
    entries = load_glossary_terms(path)
    now = datetime.now(UTC).isoformat()
    rows = [_entry_to_row(entry, updated_at=now) for entry in entries]
    if not rows:
        return 0

    client = await get_supabase_client()
    await (
        client.table("glossary_terms")
        .upsert(rows, on_conflict="term")
        .execute()
    )
    return len(rows)


async def search_terms(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Search terms by exact term/alias first, then lightweight local ranking."""
    if not query.strip():
        return []

    rows: list[dict[str, Any]] = []
    try:
        client = await get_supabase_client()
        result = await (
            client.table("glossary_terms")
            .select(GLOSSARY_COLUMNS)
            .limit(1000)
            .execute()
        )
        rows = [_normalize_row(row) for row in (result.data or [])]
    except Exception as exc:
        logger.warning(f"Supabase 용어 사전 조회 실패, 로컬 사전으로 대체: {type(exc).__name__}: {exc}")

    existing_terms = {str(row.get("term") or "").casefold() for row in rows}
    rows.extend(
        row
        for row in load_local_glossary_rows()
        if str(row.get("term") or "").casefold() not in existing_terms
    )
    return rank_glossary_terms(rows, query, limit=limit)


async def search_or_research_terms(
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Search glossary first; if missing, fetch an external definition and cache it.

    This keeps normal glossary answers fast while letting the app learn a new
    investment term when the structured table and vector RAG are sparse.
    """
    matches = await search_terms(query, limit=limit)
    if matches:
        return matches

    researched = await research_and_cache_term(query)
    return [researched] if researched else []


async def get_term(term: str) -> dict[str, Any] | None:
    """Return the best glossary match for a single term-like query."""
    matches = await search_terms(term, limit=1)
    return matches[0] if matches else None


async def research_and_cache_term(query: str) -> dict[str, Any] | None:
    """Fetch a missing investment term from an external source and persist it."""
    entry = await research_external_term(query)
    if entry is None:
        return None

    saved = await upsert_glossary_entry(entry)
    try:
        await cache_glossary_entry_to_rag(saved)
    except Exception as exc:  # RAG cache must not block the user's answer.
        logger.warning(
            f"External glossary term saved but RAG cache failed: "
            f"term={saved.get('term')}, error={type(exc).__name__}: {exc}"
        )
    return saved


async def research_external_term(
    query: str,
    *,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any] | None:
    """Use Naver encyclopedia search to find a concise investment-term definition."""
    term = extract_term_from_query(query)
    if not term:
        return None
    if not settings.naver_client_id or not settings.naver_client_secret:
        return None

    params = {
        "query": f"{term} 주식 투자",
        "display": 5,
        "start": 1,
    }
    headers = {
        "X-Naver-Client-Id": settings.naver_client_id,
        "X-Naver-Client-Secret": settings.naver_client_secret,
    }
    if client is None:
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            response = await http_client.get(
                NAVER_ENCYC_URL,
                headers=headers,
                params=params,
            )
    else:
        response = await client.get(NAVER_ENCYC_URL, headers=headers, params=params)

    if response.status_code != 200:
        logger.warning(f"Naver encyclopedia lookup failed: HTTP {response.status_code}")
        return None

    candidates = [
        _normalize_external_item(item, term)
        for item in response.json().get("items", [])
    ]
    candidates = [item for item in candidates if item is not None]
    if not candidates:
        return None

    candidates.sort(key=lambda item: item["score"], reverse=True)
    best = candidates[0]
    if best["score"] < 2:
        return None

    now = datetime.now(UTC).isoformat()
    return {
        "term": term,
        "definition": best["definition"],
        "category": "investment",
        "aliases": [term],
        "difficulty": "beginner",
        "example": f"{term}은 투자 기사나 공시를 읽을 때 자주 나오는 개념입니다.",
        "source_url": best["source_url"],
        "metadata": {
            "source_type": "external_glossary",
            "provider": "naver_encyclopedia",
            "external_title": best["title"],
            "domain": best["domain"],
            "cached_at": now,
        },
    }


async def upsert_glossary_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Upsert one glossary entry and return a normalized row-like dictionary."""
    now = datetime.now(UTC).isoformat()
    row = _entry_to_row(entry, updated_at=now)
    client = await get_supabase_client()
    result = await (
        client.table("glossary_terms")
        .upsert([row], on_conflict="term")
        .execute()
    )
    saved = _normalize_row((result.data or [row])[0])
    saved["match_score"] = 80
    return saved


async def cache_glossary_entry_to_rag(entry: dict[str, Any]) -> int:
    """Persist an externally researched term as a tiny RAG document chunk."""
    from app.repositories import rag

    term = entry.get("term") or ""
    definition = entry.get("definition") or ""
    source_url = entry.get("source_url")
    content = f"용어: {term}\n뜻: {definition}"
    if source_url:
        content += f"\n출처: {source_url}"
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    source_hash = hashlib.sha1(term.casefold().encode("utf-8")).hexdigest()[:12]
    return await rag.save_chunks(
        source_id=f"glossary-external:{source_hash}",
        chunks=[
            {
                "chunk_index": 0,
                "section": term,
                "content": content,
                "content_hash": content_hash,
                "metadata": {
                    "term": term,
                    "aliases": entry.get("aliases") or [],
                    "source_url": source_url,
                },
            }
        ],
        base_metadata={
            "source_type": "external_glossary",
            "title": f"외부 검색 투자 용어: {term}",
            "status": "active",
        },
    )


def extract_term_from_query(query: str) -> str | None:
    """Extract the likely term from questions like '상장이 뭐야?' or 'PER 뜻'."""
    text = re.sub(r"\s+", " ", query.strip())
    text = text.strip(" ?!.,。！？")
    if not text:
        return None

    for term in _SPECIAL_TERMS_ENDING_WITH_PARTICLE:
        if re.search(
            rf"{re.escape(term)}\s*(?:{_DEFINITION_PHRASE})",
            text,
            flags=re.IGNORECASE,
        ):
            return term

    patterns = (
        rf"^(.+?)(?:이라는|라는|이란|란)?\s*단어(?:가|는|은)?\s*(?:{_DEFINITION_PHRASE})",
        rf"^(.+?)(?:이|가|은|는)?\s*(?:{_DEFINITION_PHRASE})",
        rf"^(?:주식|투자|증권)\s+(.+?)\s*(?:{_DEFINITION_PHRASE})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_extracted_term(match.group(1))

    if len(text) <= 30 and any(hint in text for hint in _INVESTMENT_RESEARCH_HINTS):
        return _clean_extracted_term(text)
    return None


def _clean_extracted_term(value: str) -> str | None:
    cleaned = value.strip(" ?!.,。！？\"'“”‘’")
    cleaned = re.sub(r"^(주식|투자|증권|금융)\s+", "", cleaned)
    cleaned = re.sub(r"\s*(?:이라는|라는|이란|란)?\s*단어$", "", cleaned).strip()
    cleaned = re.sub(r"(이라는|라는|이란|란|은|는)$", "", cleaned).strip()
    if not cleaned or len(cleaned) > 40:
        return None
    return cleaned


def _normalize_external_item(
    item: dict[str, Any],
    term: str,
) -> dict[str, Any] | None:
    title = _clean_html(item.get("title") or "")
    description = _clean_html(item.get("description") or "")
    source_url = item.get("link") or ""
    if not description:
        return None

    haystack = f"{title} {description}".casefold()
    term_key = term.casefold()
    score = 0
    if term_key in title.casefold():
        score += 3
    if term_key in description.casefold():
        score += 2
    score += sum(1 for hint in _INVESTMENT_RESEARCH_HINTS if hint.casefold() in haystack)

    return {
        "title": title or term,
        "definition": description,
        "source_url": source_url,
        "domain": urlsplit(source_url).netloc.lower(),
        "score": score,
    }


def _clean_html(value: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", value)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


async def list_all_terms() -> list[dict[str, Any]]:
    """전체 용어 목록을 반환합니다 (답변 텍스트 내 용어 매칭용)."""
    rows: list[dict[str, Any]] = []
    try:
        client = await get_supabase_client()
        result = await (
            client.table("glossary_terms")
            .select(GLOSSARY_COLUMNS)
            .limit(1000)
            .execute()
        )
        rows = [_normalize_row(row) for row in (result.data or [])]
    except Exception as exc:
        logger.warning(f"Supabase 전체 용어 조회 실패, 로컬 사전으로 대체: {type(exc).__name__}: {exc}")

    existing_terms = {str(row.get("term") or "").casefold() for row in rows}
    rows.extend(
        row
        for row in load_local_glossary_rows()
        if str(row.get("term") or "").casefold() not in existing_terms
    )
    return rows


def find_terms_in_text(
    text: str,
    terms: list[dict[str, Any]],
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """답변 텍스트 안에 등장하는 용어(사전 표제어·별칭)를 찾아냅니다.

    나무위키식 밑줄 각주에 쓸 수 있게, 실제로 본문에 등장한 표기(matched_text)와
    정의를 함께 돌려준다. 같은 자리에 여러 용어가 겹치면 더 긴 표기를 우선한다.
    """
    if not text.strip() or not terms:
        return []

    # (표기, term row) 후보를 만들고 긴 표기부터 검사해 부분 문자열 중복을 줄인다.
    candidates: list[tuple[str, dict[str, Any]]] = []
    for row in terms:
        surface_forms = {row.get("term", "")} | set(row.get("aliases") or [])
        for surface in surface_forms:
            surface = (surface or "").strip()
            if len(surface) >= 2:
                candidates.append((surface, row))
    candidates.sort(key=lambda pair: len(pair[0]), reverse=True)

    matched: dict[str, dict[str, Any]] = {}
    occupied: list[tuple[int, int]] = []

    for surface, row in candidates:
        term_key = row.get("term", "")
        if term_key in matched:
            continue
        span = _find_surface_span(text, surface)
        if span is None:
            continue
        start, end = span
        end = start + len(surface)
        if any(start < o_end and end > o_start for o_start, o_end in occupied):
            continue
        occupied.append((start, end))
        matched[term_key] = {
            "term": term_key,
            "matched_text": surface,
            "definition": row.get("definition", ""),
            "category": row.get("category"),
            "example": row.get("example"),
        }
        if len(matched) >= limit:
            break

    return list(matched.values())


def _find_surface_span(text: str, surface: str) -> tuple[int, int] | None:
    start = text.find(surface)
    while start >= 0:
        end = start + len(surface)
        if _is_valid_surface_match(text, start, end, surface):
            return start, end
        start = text.find(surface, start + 1)
    return None


def _is_valid_surface_match(text: str, start: int, end: int, surface: str) -> bool:
    """Avoid matching short English aliases inside longer tokens, e.g. CB in PCB."""
    if not _needs_ascii_word_boundary(surface):
        return True
    before = text[start - 1] if start > 0 else ""
    after = text[end] if end < len(text) else ""
    return not _is_ascii_token_char(before) and not _is_ascii_token_char(after)


def _needs_ascii_word_boundary(surface: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]", surface)) and not re.search(r"[가-힣]", surface)


def _is_ascii_token_char(char: str) -> bool:
    return bool(char and re.match(r"[A-Za-z0-9]", char))


def rank_glossary_terms(
    rows: list[dict[str, Any]],
    query: str,
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Rank loaded glossary rows without depending on Supabase.

    This is intentionally simple and deterministic so tests and mocks can share
    the same contract as production.
    """
    normalized_query = _normalize_key(query)
    query_tokens = [token for token in re.split(r"\s+", query.lower()) if token]
    scored: list[tuple[int, dict[str, Any]]] = []

    for row in rows:
        score = _score_row(row, normalized_query, query_tokens)
        if score > 0:
            item = dict(row)
            item["match_score"] = score
            scored.append((score, item))

    scored.sort(key=lambda pair: (pair[0], pair[1]["term"].lower()), reverse=True)
    return [item for _, item in scored[: max(1, min(limit, 20))]]


def _entry_to_row(entry: dict[str, Any], *, updated_at: str) -> dict[str, Any]:
    aliases = entry.get("aliases") or []
    if not isinstance(aliases, list):
        aliases = [str(aliases)]

    return {
        "term": str(entry["term"]).strip(),
        "definition": str(entry["definition"]).strip(),
        "category": entry.get("category") or _infer_category(str(entry["term"])),
        "aliases": [str(alias).strip() for alias in aliases if str(alias).strip()],
        "difficulty": entry.get("difficulty") or "beginner",
        "example": entry.get("example"),
        "source_url": entry.get("source_url"),
        "metadata": entry.get("metadata") or {},
        "updated_at": updated_at,
    }


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "term": row.get("term") or "",
        "definition": row.get("definition") or "",
        "category": row.get("category"),
        "aliases": row.get("aliases") or [],
        "difficulty": row.get("difficulty") or "beginner",
        "example": row.get("example"),
        "source_url": row.get("source_url"),
        "metadata": row.get("metadata") or {},
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def _score_row(
    row: dict[str, Any],
    normalized_query: str,
    query_tokens: list[str],
) -> int:
    term = row.get("term") or ""
    aliases = row.get("aliases") or []
    definition = row.get("definition") or ""
    category = row.get("category") or ""

    term_key = _normalize_key(term)
    alias_keys = [_normalize_key(alias) for alias in aliases]
    definition_lower = definition.lower()
    category_lower = str(category).lower()

    if term_key and term_key == normalized_query:
        return 100
    if term_key and term_key in normalized_query:
        return 95
    if any(alias_key and alias_key == normalized_query for alias_key in alias_keys):
        return 90
    if any(alias_key and alias_key in normalized_query for alias_key in alias_keys):
        return 85
    if term_key and normalized_query and normalized_query in term_key:
        return 70
    if any(token in definition_lower for token in query_tokens if len(token) >= 2):
        return 35
    if any(token in category_lower for token in query_tokens if len(token) >= 2):
        return 25
    return 0


def _normalize_key(value: str) -> str:
    return re.sub(r"[\W_]+", "", value.casefold())


def _infer_category(term: str) -> str:
    if term.upper() in {"PER", "PBR", "ROE", "EPS", "BPS"}:
        return "valuation"
    if term.lower() in {"cb"}:
        return "disclosure"
    return "investment"

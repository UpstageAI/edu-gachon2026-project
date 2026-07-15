"""RSS feed normalization helpers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable

from app.core.config import Settings, get_settings
from app.core.schemas import NewsDocument


@dataclass(frozen=True, slots=True)
class RawFeedEntry:
    source: str
    title: str
    link: str
    published_at: str | datetime | None
    summary: str | None = None
    tags: tuple[str, ...] = ()


def _parse_datetime(value: str | datetime | None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            parsed = parsedate_to_datetime(text)
    else:
        parsed = datetime.now(timezone.utc)

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _news_id_from_url(url: str) -> str:
    return f"news_{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}"


def normalize_feed_entry(entry: RawFeedEntry) -> NewsDocument:
    """Convert a raw feed entry into a stable NewsDocument."""

    return NewsDocument(
        news_id=_news_id_from_url(entry.link),
        title=entry.title.strip(),
        source=entry.source.strip() or "rss",
        url=entry.link.strip(),
        published_at=_parse_datetime(entry.published_at),
        summary=(entry.summary or "").strip() or None,
        tags=sorted(set(tag.strip() for tag in entry.tags if tag.strip())),
    )


def deduplicate_news_items(items: Iterable[NewsDocument]) -> list[NewsDocument]:
    """Deduplicate news by URL while preserving first-seen order."""

    seen_urls: set[str] = set()
    deduplicated: list[NewsDocument] = []
    for item in items:
        url = str(item.url)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        deduplicated.append(item)
    return deduplicated


def filter_recent_news(
    items: Iterable[NewsDocument],
    *,
    since: datetime,
    min_text_length: int = 8,
) -> list[NewsDocument]:
    """Keep recent news with enough title/summary text for RAG."""

    since_utc = _parse_datetime(since)
    filtered: list[NewsDocument] = []
    for item in items:
        published_at = _parse_datetime(item.published_at)
        text = f"{item.title} {item.summary or ''}".strip()
        if published_at < since_utc:
            continue
        if len(text) < min_text_length:
            continue
        filtered.append(item)
    return filtered


def _entry_to_raw(source: str, entry: Any) -> RawFeedEntry:
    tags = tuple(
        tag.get("term", "")
        for tag in getattr(entry, "tags", []) or entry.get("tags", [])
        if isinstance(tag, dict)
    )
    return RawFeedEntry(
        source=source,
        title=getattr(entry, "title", None) or entry.get("title", ""),
        link=getattr(entry, "link", None) or entry.get("link", ""),
        published_at=(
            getattr(entry, "published", None)
            or entry.get("published")
            or getattr(entry, "updated", None)
            or entry.get("updated")
        ),
        summary=getattr(entry, "summary", None) or entry.get("summary"),
        tags=tags,
    )


def fetch_rss_news(
    *,
    settings: Settings | None = None,
    max_items_per_feed: int = 30,
) -> list[NewsDocument]:
    """Fetch configured RSS feeds if feedparser is installed."""

    runtime_settings = settings or get_settings()
    if not runtime_settings.news_rss_urls:
        return []

    try:
        import feedparser
    except ImportError:
        return []

    documents: list[NewsDocument] = []
    for feed_url in runtime_settings.news_rss_urls:
        feed = feedparser.parse(str(feed_url))
        source = getattr(feed.feed, "title", None) or feed.feed.get("title", str(feed_url))
        for entry in list(feed.entries)[:max_items_per_feed]:
            raw = _entry_to_raw(source, entry)
            if raw.title and raw.link:
                documents.append(normalize_feed_entry(raw))
    return deduplicate_news_items(documents)

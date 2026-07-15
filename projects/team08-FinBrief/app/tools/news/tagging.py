"""Topic keyword tagging for news documents."""

from __future__ import annotations

from app.core.schemas import NewsDocument, Topic


def topic_keywords(topic: Topic) -> list[str]:
    """Return unique topic news keywords sorted for stable output."""

    keywords: set[str] = set()
    for mapping in topic.source_mapping:
        keywords.update(keyword.strip() for keyword in mapping.news_keywords if keyword.strip())
    return sorted(keywords)


def tag_news_for_topics(
    documents: list[NewsDocument],
    topics: list[Topic],
    *,
    include_general_market: bool = False,
) -> list[NewsDocument]:
    """Tag news by matching topic keywords against title and summary."""

    tagged_documents: list[NewsDocument] = []
    for document in documents:
        text = f"{document.title} {document.summary or ''}".casefold()
        tags = set(document.tags)
        for topic in topics:
            for keyword in topic_keywords(topic):
                if keyword.casefold() in text:
                    tags.add(keyword)

        if include_general_market and not tags:
            tags.add("general_market")

        tagged_documents.append(document.model_copy(update={"tags": sorted(tags)}))
    return tagged_documents

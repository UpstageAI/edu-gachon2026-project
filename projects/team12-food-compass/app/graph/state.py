from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    user_query: str
    region: str | None
    unit: str | None
    route: str
    items: list[str]
    price_data: list[dict[str, Any]]
    judgment: list[dict[str, Any]]
    knowledge_result: str
    substitutes: list[str]
    comparison: dict[str, Any] | None
    processed_prices: list[dict[str, Any]]
    answer: str

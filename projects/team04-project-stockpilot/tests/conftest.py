"""Shared pytest fixtures for deterministic, network-free tests."""

import pytest


@pytest.fixture(autouse=True)
def disable_llm_router_network_by_default(monkeypatch):
    """Avoid real Solar router calls unless a test explicitly monkeypatches it."""

    async def fake_llm_route(query: str, **kwargs):
        return None

    monkeypatch.setattr("app.graph.nodes._llm_route_query", fake_llm_route)

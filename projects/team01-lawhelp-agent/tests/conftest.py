import pytest

from app.repositories.mock_law_repository import search_law_qa as mock_search_law_qa


@pytest.fixture(autouse=True)
def use_mock_search_for_chat_flow(monkeypatch):
    def search_with_distance(query: str, top_k: int = 3):
        return [
            document.model_copy(update={"distance": 0.0})
            if document.distance is None
            else document
            for document in mock_search_law_qa(query, top_k=top_k)
        ]

    monkeypatch.setattr("app.agents.nodes._search_law_qa", search_with_distance)
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", search_with_distance)

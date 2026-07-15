from fastapi.testclient import TestClient
import pytest

from app.core import observability
from app.main import app
from app.schemas.document import RetrievedDocument


client = TestClient(app)


class FakeObservation:
    def __init__(self, record):
        self.record = record

    def update(self, **kwargs):
        self.record["updates"].append(kwargs)


class FakeObservationContext:
    def __init__(self, record):
        self.record = record

    def __enter__(self):
        self.record["entered"] = True
        return FakeObservation(self.record)

    def __exit__(self, exc_type, exc, traceback):
        self.record["exit_type"] = exc_type.__name__ if exc_type else None
        return False


class FakeLangfuseClient:
    def __init__(self):
        self.records = []
        self.flushed = False

    def start_as_current_observation(self, **kwargs):
        record = {"kwargs": kwargs, "updates": []}
        self.records.append(record)
        return FakeObservationContext(record)

    def flush(self):
        self.flushed = True


def _fake_documents():
    return [
        RetrievedDocument(
            id="rent_001",
            category="임대차",
            question="월세 계약 전에 무엇을 확인해야 하나요?",
            answer="등기부등본과 계약 상대방을 확인합니다.",
            distance=0.4,
        )
    ]


@pytest.fixture
def fake_langfuse(monkeypatch):
    fake = FakeLangfuseClient()
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: fake)
    return fake


@pytest.fixture
def fake_completion(monkeypatch):
    def _fake_completion(messages, stream):
        if stream:
            return iter(
                [
                    {"choices": [{"delta": {"content": "첫 "}}]},
                    {"choices": [{"delta": {"content": "응답"}}]},
                ]
            )
        return {
            "choices": [{"message": {"content": "테스트 LLM 응답입니다."}}],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 4,
                "total_tokens": 7,
            },
        }

    monkeypatch.setattr("app.core.llm._completion", _fake_completion)


def test_langfuse_disabled_does_not_break_sync(monkeypatch, fake_completion):
    monkeypatch.setattr("app.agents.nodes._search_law_qa", lambda query: _fake_documents())
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", lambda query: _fake_documents())
    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: None)

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 확인할 점은?"})

    assert response.status_code == 200
    assert response.json()["guardrail_blocked"] is False


def test_missing_langfuse_keys_disables_tracing(monkeypatch):
    settings = type(
        "Settings",
        (),
        {
            "langfuse_enabled": True,
            "langfuse_public_key": "",
            "langfuse_secret_key": "",
        },
    )()
    monkeypatch.setattr(observability, "settings", settings)

    assert observability.is_langfuse_configured() is False


def test_chat_sync_records_request_guardrail_retrieval_and_generation(
    monkeypatch,
    fake_langfuse,
    fake_completion,
):
    monkeypatch.setattr("app.agents.nodes._search_law_qa", lambda query: _fake_documents())
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", lambda query: _fake_documents())

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 확인할 점은?"})

    assert response.status_code == 200
    names = [record["kwargs"]["name"] for record in fake_langfuse.records]
    assert "law-help-chat-sync" in names
    assert "guardrail" in names
    assert "retrieval" in names
    assert "generation" in names

    root_record = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "law-help-chat-sync"
    )
    root_update = root_record["updates"][-1]
    assert root_update["metadata"]["response_type"] == "grounded_rag"
    assert root_update["metadata"]["retrieved_count"] == 1
    assert root_update["metadata"]["best_distance"] == 0.4
    from app.core.routing import EXACT_DISTANCE_THRESHOLD, RELATED_DISTANCE_THRESHOLD

    assert root_update["metadata"]["exact_threshold"] == EXACT_DISTANCE_THRESHOLD
    assert root_update["metadata"]["related_threshold"] == RELATED_DISTANCE_THRESHOLD
    assert root_update["metadata"]["exact_document_count"] == 1
    assert root_update["metadata"]["related_document_count"] == 0
    assert root_update["metadata"]["grounded"] is True
    assert root_update["metadata"]["llm_general_knowledge_used"] is False
    assert root_update["metadata"]["suggestion_count"] == 0

    generation_record = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "generation"
    )
    generation_update = generation_record["updates"][-1]
    assert generation_record["kwargs"]["as_type"] == "generation"
    assert generation_update["usage_details"] == {"input": 3, "output": 4, "total": 7}


def test_blocked_sync_does_not_run_retrieval_or_generation(monkeypatch, fake_langfuse):
    from app.agents.nodes import DANGEROUS_PHRASES

    def fail_search(query):
        raise AssertionError("retrieval should not run for blocked input")

    monkeypatch.setattr("app.agents.nodes._search_law_qa", fail_search)
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", fail_search)

    response = client.post("/chat/sync", json={"message": DANGEROUS_PHRASES[0]})

    assert response.status_code == 200
    names = [record["kwargs"]["name"] for record in fake_langfuse.records]
    assert "law-help-chat-sync" in names
    assert "guardrail" in names
    assert "retrieval" not in names
    assert "generation" not in names

    root_record = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "law-help-chat-sync"
    )
    root_update = root_record["updates"][-1]
    assert root_update["metadata"]["response_type"] == "out_of_scope"


def test_no_result_sync_records_no_result(monkeypatch, fake_langfuse):
    def fail_completion(messages, stream):
        raise AssertionError("generation should not run without retrieved documents")

    monkeypatch.setattr("app.agents.nodes._search_law_qa", lambda query: [])
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", lambda query: [])
    monkeypatch.setattr("app.core.llm._completion", fail_completion)

    response = client.post("/chat/sync", json={"message": "관련 없는 질문"})

    assert response.status_code == 200
    names = [record["kwargs"]["name"] for record in fake_langfuse.records]
    assert "retrieval" in names
    assert "generation" not in names

    root_record = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "law-help-chat-sync"
    )
    root_update = root_record["updates"][-1]
    assert root_update["metadata"]["response_type"] == "out_of_scope"


def test_chat_stream_records_final_output(monkeypatch, fake_langfuse, fake_completion):
    monkeypatch.setattr("app.agents.nodes._search_law_qa", lambda query: _fake_documents())
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", lambda query: _fake_documents())

    response = client.post("/chat/stream", json={"message": "월세 계약 전에 확인할 점은?"})

    assert response.status_code == 200
    assert "event: done" in response.text

    root_record = next(
        record for record in fake_langfuse.records if record["kwargs"]["name"] == "law-help-chat-stream"
    )
    root_update = root_record["updates"][-1]
    assert root_update["metadata"]["response_type"] == "grounded_rag"
    assert root_update["metadata"]["best_distance"] == 0.4
    assert root_update["metadata"]["grounded"] is True
    assert root_update["metadata"]["llm_general_knowledge_used"] is False
    assert "첫 응답" in root_update["output"]["answer"]


def test_langfuse_observation_error_does_not_break_response(monkeypatch, fake_completion):
    class BrokenLangfuseClient:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse is down")

    monkeypatch.setattr(observability, "_get_langfuse_client", lambda: BrokenLangfuseClient())
    monkeypatch.setattr("app.agents.nodes._search_law_qa", lambda query: _fake_documents())

    response = client.post("/chat/sync", json={"message": "월세 계약 전에 확인할 점은?"})

    assert response.status_code == 200
    assert response.json()["guardrail_blocked"] is False


def test_sensitive_values_are_masked():
    masked = observability.mask_sensitive_text(
        "email test@example.com phone 010-1234-5678 rrn 900101-1234567"
    )

    assert "test@example.com" not in masked
    assert "010-1234-5678" not in masked
    assert "900101-1234567" not in masked

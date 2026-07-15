import json

from fastapi.testclient import TestClient

from app.agents.nodes import (
    GENERAL_KNOWLEDGE_WARNING,
    LEGAL_NOTICE,
    RELATED_SUGGESTION_INTRO,
)
from app.main import app
from app.schemas.document import RetrievedDocument


client = TestClient(app)


def _document(document_id: str, distance: float, question: str) -> RetrievedDocument:
    return RetrievedDocument(
        id=document_id,
        category="부동산/임대차",
        question=question,
        answer="테스트 답변",
        distance=distance,
    )


def _sse_data(response_text: str, event_name: str) -> list[dict]:
    marker = f"event: {event_name}\ndata: "
    values = []
    for block in response_text.split("\n\n"):
        if block.startswith(marker):
            values.append(json.loads(block[len(marker) :]))
    return values


def test_chat_stream_normal_question_returns_token_metadata_and_done(monkeypatch):
    def fake_stream_text(prompt: str, system=None):
        yield "첫 "
        yield "답변"

    monkeypatch.setattr("app.api.chat.stream_text", fake_stream_text)

    response = client.post(
        "/chat/stream",
        json={"message": "월세 계약 전에 뭘 확인해야 하나요?"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert 'event: token\ndata: {"text": "첫 "}' in response.text
    assert 'event: token\ndata: {"text": "답변"}' in response.text
    assert response.text.count("event: metadata") == 1
    assert response.text.index("event: metadata") < response.text.index("event: done")
    assert _sse_data(response.text, "metadata")[0]["response_type"] == "grounded_rag"
    assert "event: done\ndata: {}" in response.text


def test_chat_stream_blocked_question_returns_token_metadata_and_done(monkeypatch):
    def fail_stream_text(prompt: str, system=None):
        raise AssertionError("stream_text should not be called")

    monkeypatch.setattr("app.api.chat.stream_text", fail_stream_text)

    response = client.post(
        "/chat/stream",
        json={"message": "제가 소송하면 이길 수 있을까요? 소장 좀 써주세요"},
    )

    assert response.status_code == 200
    assert response.text.count("event: token") == 1
    assert response.text.count("event: metadata") == 1
    assert _sse_data(response.text, "metadata")[0]["response_type"] == "out_of_scope"
    assert "event: done\ndata: {}" in response.text
    assert "개별 사건의 승소 가능성 판단" in response.text


def test_chat_stream_out_of_scope_question_returns_token_metadata_and_done(monkeypatch):
    def fail_stream_text(prompt: str, system=None):
        raise AssertionError("stream_text should not be called")

    monkeypatch.setattr("app.api.chat.stream_text", fail_stream_text)

    response = client.post(
        "/chat/stream",
        json={"message": "상속 포기 절차가 궁금해요"},
    )

    assert response.status_code == 200
    assert response.text.count("event: token") == 1
    assert response.text.count("event: metadata") == 1
    assert _sse_data(response.text, "metadata")[0]["response_type"] == "out_of_scope"
    assert "event: done\ndata: {}" in response.text
    assert "지원 범위 밖" in response.text


def test_chat_stream_llm_error_returns_error_event(monkeypatch):
    from app.core.llm import LLMError

    def fail_stream_text(prompt: str, system=None):
        raise LLMError("stream failed")
        yield ""

    monkeypatch.setattr("app.api.chat.stream_text", fail_stream_text)

    response = client.post(
        "/chat/stream",
        json={"message": "월세 계약 전에 뭘 확인해야 하나요?"},
    )

    assert response.status_code == 200
    assert 'event: error\ndata: {"message": "stream failed"}' in response.text
    assert "event: metadata" not in response.text
    assert "event: done" not in response.text


def test_chat_stream_related_hybrid_sends_warning_suggestions_and_metadata(monkeypatch):
    def fake_stream_text(prompt: str, system=None):
        yield "일반 안내입니다."

    monkeypatch.setattr("app.api.chat.stream_text", fake_stream_text)
    monkeypatch.setattr(
        "app.agents.nodes._search_law_qa_raw",
        lambda query: [
            _document("law_related_1", 0.55, "전세 보증금을 지키려면 어떻게 해야 하나요?")
        ],
    )

    response = client.post(
        "/chat/stream",
        json={"message": "전세 계약 전에 뭘 확인해야 하나요?"},
    )

    assert response.status_code == 200
    assert GENERAL_KNOWLEDGE_WARNING in response.text
    assert response.text.index(GENERAL_KNOWLEDGE_WARNING) < response.text.index("일반 안내입니다.")
    assert RELATED_SUGGESTION_INTRO in response.text
    assert "전세 보증금을 지키려면 어떻게 해야 하나요?" in response.text
    assert LEGAL_NOTICE in response.text

    metadata = _sse_data(response.text, "metadata")[0]
    assert metadata["response_type"] == "related_hybrid"
    assert metadata["warning"] == GENERAL_KNOWLEDGE_WARNING
    assert metadata["suggested_questions"]
    assert metadata["suggested_questions"][0]["source_document_id"] == "law_related_1"
    assert response.text.index("event: metadata") < response.text.index("event: done")
    assert "event: done\ndata: {}" in response.text


def test_chat_stream_llm_only_sends_warning_without_suggestions(monkeypatch):
    def fake_stream_text(prompt: str, system=None):
        yield "신청 자격을 공식 기관에서 확인해 주세요."

    monkeypatch.setattr("app.api.chat.stream_text", fake_stream_text)
    monkeypatch.setattr("app.agents.nodes._search_law_qa_raw", lambda query: [])

    response = client.post(
        "/chat/stream",
        json={"message": "장애인연금은 어떤 조건으로 받을 수 있나요?"},
    )

    assert response.status_code == 200
    assert GENERAL_KNOWLEDGE_WARNING in response.text
    assert response.text.index(GENERAL_KNOWLEDGE_WARNING) < response.text.index("신청 자격")
    assert RELATED_SUGGESTION_INTRO not in response.text
    assert "보건복지부" in response.text
    assert LEGAL_NOTICE in response.text

    metadata = _sse_data(response.text, "metadata")[0]
    assert metadata["response_type"] == "llm_only"
    assert metadata["warning"] == GENERAL_KNOWLEDGE_WARNING
    assert metadata["suggested_questions"] == []
    assert metadata["sources"] == []
    assert "event: done\ndata: {}" in response.text

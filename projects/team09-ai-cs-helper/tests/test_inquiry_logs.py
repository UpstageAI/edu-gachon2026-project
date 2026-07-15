import json

from app.clients import inquiry_logs


def test_append_inquiry_log_sends_structured_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(inquiry_logs, "supabase_url", lambda *args: "https://example.test/logs")
    monkeypatch.setattr(inquiry_logs, "supabase_headers", lambda *args: {})

    def fake_read_json(request):
        captured.update(json.loads(request.data.decode("utf-8")))

    monkeypatch.setattr(inquiry_logs, "read_json", fake_read_json)

    saved = inquiry_logs.append_inquiry_log(
        "inq-1",
        stage="review",
        event="review_failed",
        title="AI 답변 검수 반려",
        attempt=1,
        duration_ms=120,
        data={"next_node": "router"},
    )

    assert saved is True
    assert captured["inquiry_id"] == "inq-1"
    assert captured["stage"] == "review"
    assert captured["attempt"] == 1
    assert captured["data"] == {"next_node": "router"}


def test_append_inquiry_log_failure_does_not_raise(monkeypatch):
    def broken_url(*args):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(inquiry_logs, "supabase_url", broken_url)

    saved = inquiry_logs.append_inquiry_log(
        "inq-1",
        stage="rag",
        event="failed",
        title="RAG 실패",
    )

    assert saved is False


def test_list_inquiry_logs_requests_sequence_order(monkeypatch):
    captured = {}

    def fake_url(path, query):
        captured.update(query)
        return "https://example.test/logs"

    monkeypatch.setattr(inquiry_logs, "supabase_url", fake_url)
    monkeypatch.setattr(inquiry_logs, "supabase_headers", lambda *args: {})
    monkeypatch.setattr(inquiry_logs, "read_json", lambda request: [{"sequence": 1}])

    rows = inquiry_logs.list_inquiry_logs("inq-1")

    assert rows == [{"sequence": 1}]
    assert captured["inquiry_id"] == "eq.inq-1"
    assert captured["order"] == "sequence.asc"

import json

import pytest

from app.clients import embedding, http, supabase
from app.rag import search


def test_vector_literal_formats_pgvector_value():
    assert supabase.vector_literal([1.0, 2.5, -3.0]) == "[1.0,2.5,-3.0]"


def test_parse_embedding_accepts_json_string():
    assert supabase.parse_embedding("[1, 2.5, -3]") == [1.0, 2.5, -3.0]


def test_parse_embedding_accepts_list():
    assert supabase.parse_embedding([1, "2.5", -3]) == [1.0, 2.5, -3.0]


def test_cosine_similarity_returns_one_for_same_direction():
    result = search.cosine_similarity([1, 2, 3], [1, 2, 3])
    assert result == pytest.approx(1.0)


def test_cosine_similarity_returns_zero_for_zero_vector():
    assert search.cosine_similarity([0, 0], [1, 2]) == 0.0


def test_documents_table_uses_default_when_env_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_DOCUMENTS_TABLE", raising=False)
    assert supabase.documents_table() == "documents"


def test_documents_table_uses_env_value(monkeypatch):
    monkeypatch.setenv("SUPABASE_DOCUMENTS_TABLE", "custom_documents")
    assert supabase.documents_table() == "custom_documents"


def test_supabase_headers_includes_auth(monkeypatch):
    monkeypatch.setenv("SUPABASE_KEY", "secret-key")
    headers = supabase.supabase_headers()
    assert headers["apikey"] == "secret-key"
    assert headers["Authorization"] == "Bearer secret-key"


def test_supabase_url_builds_query_string(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    url = supabase.supabase_url("documents", {"select": "id,content"})
    assert url == "https://example.supabase.co/rest/v1/documents?select=id%2Ccontent"


def test_env_raises_when_value_missing(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_ENV", raising=False)

    with pytest.raises(RuntimeError, match="Missing environment variable"):
        http.env("MISSING_TEST_ENV")


def test_post_json_sends_json_payload(monkeypatch):
    captured = {}

    def fake_read_json(request, timeout=None):
        captured["method"] = request.get_method()
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return {"ok": True}

    monkeypatch.setattr(http, "read_json", fake_read_json)

    response = http.post_json(
        "https://example.com",
        {"Content-Type": "application/json"},
        {"hello": "world"},
    )

    assert response == {"ok": True}
    assert captured["method"] == "POST"
    assert captured["body"] == {"hello": "world"}


def test_embed_returns_embedding_from_api_response(monkeypatch):
    def fake_embedding_config(kind):
        assert kind == "query"
        return "https://api.example.com/v1", "test-key", "embedding-query"

    def fake_post_json(url, headers, payload):
        assert url == "https://api.example.com/v1/embeddings"
        assert headers["Authorization"] == "Bearer test-key"
        assert payload == {"model": "embedding-query", "input": "hello"}
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr(embedding, "embedding_config", fake_embedding_config)
    monkeypatch.setattr(embedding, "post_json", fake_post_json)

    assert embedding.embed("hello", "query") == [0.1, 0.2, 0.3]


def test_embed_with_usage_returns_model_and_tokens(monkeypatch):
    monkeypatch.setattr(
        embedding,
        "embedding_config",
        lambda kind: ("https://api.example.com/v1", "test-key", "embedding-query"),
    )
    monkeypatch.setattr(
        embedding,
        "post_json",
        lambda *args, **kwargs: {
            "model": "embedding-query-v1",
            "data": [{"embedding": [0.1, 0.2]}],
            "usage": {"prompt_tokens": 8, "total_tokens": 8},
        },
    )

    result = embedding.embed_with_usage("hello", "query")

    assert result.vector == [0.1, 0.2]
    assert result.model == "embedding-query-v1"
    assert result.token_usage == {"prompt_tokens": 8, "total_tokens": 8}


@pytest.mark.parametrize(
    ("ai_answer", "final_answer", "expected_reviewer"),
    [
        ("AI가 만든 답변", "AI가 만든 답변", "ai"),
        ("AI가 만든 답변", "수정한 답변", "human"),
        ("", "상담원이 작성한 답변", "human"),
        (None, "상담원이 작성한 답변", "human"),
    ],
)
def test_update_final_answer_assigns_reviewer(
    monkeypatch, ai_answer, final_answer, expected_reviewer
):
    captured = {}
    monkeypatch.setattr(
        supabase,
        "get_inquiry",
        lambda inquiry_id: {"inquiry_id": inquiry_id, "ai_answer": ai_answer},
    )
    monkeypatch.setattr(supabase, "supabase_url", lambda *args: "https://example.test")
    monkeypatch.setattr(supabase, "supabase_headers", lambda *args: {})

    def fake_read_json(request):
        captured.update(json.loads(request.data.decode("utf-8")))
        return [{"inquiry_id": "inq-1", **captured}]

    monkeypatch.setattr(supabase, "read_json", fake_read_json)
    # update_final_answer는 내부에서 inquiry_logs.append_inquiry_log를 호출한다.
    # 목킹하지 않으면 실제 Supabase로 POST가 나가므로(모듈이 자기 read_json을 씀) 차단한다.
    monkeypatch.setattr("app.clients.inquiry_logs.append_inquiry_log", lambda *a, **k: True)

    updated = supabase.update_final_answer("inq-1", final_answer)

    assert captured["reviewer_type"] == expected_reviewer
    assert updated["reviewer_type"] == expected_reviewer

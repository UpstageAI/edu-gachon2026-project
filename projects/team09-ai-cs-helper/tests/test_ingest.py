from app.rag import ingest


class NoWaitLimiter:
    def wait(self, text):
        pass


def test_build_regulation_rows_embeds_each_regulation(monkeypatch):
    monkeypatch.setattr(ingest, "embed", lambda text, kind: [0.1, 0.2, 0.3])

    rows = ingest.build_regulation_rows(limiter=NoWaitLimiter())

    assert len(rows) == len(ingest.REGULATIONS)
    first = rows[0]
    assert first["metadata"] == {"source": "regulation", "regulation_id": 1}
    assert first["embedding"] == "[0.1,0.2,0.3]"
    assert first["content"] == ingest.REGULATIONS[1]


def test_build_regulation_rows_uses_passage_kind(monkeypatch):
    seen = {}

    def fake_embed(text, kind):
        seen["kind"] = kind
        return [0.0]

    monkeypatch.setattr(ingest, "embed", fake_embed)
    ingest.build_regulation_rows(limiter=NoWaitLimiter())

    assert seen["kind"] == "passage"


def test_embedding_retries_connection_failure(monkeypatch):
    attempts = []

    def flaky_embed(text, kind):
        attempts.append((text, kind))
        if len(attempts) == 1:
            raise RuntimeError("Connection failed: temporary DNS failure")
        return [0.5]

    monkeypatch.setattr(ingest, "embed", flaky_embed)
    monkeypatch.setattr(ingest.time, "sleep", lambda seconds: None)

    result = ingest._embed_with_retry("규정", NoWaitLimiter())

    assert result == [0.5]
    assert len(attempts) == 2


def test_embedding_does_not_retry_other_errors(monkeypatch):
    def broken_embed(text, kind):
        raise RuntimeError("HTTP 401: invalid API key")

    monkeypatch.setattr(ingest, "embed", broken_embed)

    try:
        ingest._embed_with_retry("규정", NoWaitLimiter())
    except RuntimeError as exc:
        assert "HTTP 401" in str(exc)
    else:
        raise AssertionError("RuntimeError was not raised")


def test_store_documents_uses_batches(monkeypatch):
    batch_sizes = []
    monkeypatch.setattr(ingest, "SUPABASE_BATCH_SIZE", 2)
    monkeypatch.setattr(
        ingest,
        "_store_document_batch",
        lambda rows: batch_sizes.append(len(rows)),
    )

    ingest.store_documents([{"id": number} for number in range(5)])

    assert batch_sizes == [2, 2, 1]


def test_storage_timeout_splits_batch(monkeypatch):
    stored_sizes = []

    def fake_post_json(url, headers, rows):
        stored_sizes.append(len(rows))
        if len(rows) > 1:
            raise RuntimeError('HTTP 500: {"code":"57014"}')

    monkeypatch.setattr(ingest, "post_json", fake_post_json)
    monkeypatch.setattr(ingest, "supabase_url", lambda *args: "https://example.test")
    monkeypatch.setattr(ingest, "supabase_headers", lambda *args: {})

    ingest._store_document_batch([{"id": number} for number in range(4)])

    assert stored_sizes == [4, 2, 1, 1, 2, 1, 1]

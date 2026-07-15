from app.core.config import Settings
from app.core import observability


def test_observability_disabled_is_noop(monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_OTEL_HOST", raising=False)
    settings = Settings(langfuse_enabled=False)

    assert observability.langfuse_ready(settings) is False
    assert observability.trace_id_for_run("run_disabled", settings) == "local_mock_trace_run_disabled"

    with observability.span("finbrief.test", settings=settings) as span:
        span.update(output={"ok": True})
        span.score_trace(name="safety", value=1)


def test_observability_maps_langfuse_host_aliases(monkeypatch):
    monkeypatch.delenv("LANGFUSE_BASE_URL", raising=False)
    monkeypatch.delenv("LANGFUSE_OTEL_HOST", raising=False)
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    settings = Settings(
        langfuse_enabled=True,
        langfuse_public_key="pk-test",
        langfuse_secret_key="sk-test",
        langfuse_host="https://langfuse.example.test",
    )

    assert observability.configure_langfuse_environment(settings) is True

    assert observability.langfuse_ready(settings) is True
    assert observability.os.environ["LANGFUSE_BASE_URL"] == "https://langfuse.example.test"
    assert observability.os.environ["LANGFUSE_OTEL_HOST"] == "https://langfuse.example.test"
    assert observability.os.environ["LANGFUSE_PUBLIC_KEY"] == "pk-test"
    assert observability.os.environ["LANGFUSE_SECRET_KEY"] == "sk-test"


def test_observability_sanitizes_sensitive_metadata():
    metadata = observability.sanitize_metadata(
        {
            "run_id": "run_safe",
            "api_key": "must-not-leak",
            "nested": {
                "webhook_url": "https://example.invalid/hook",
                "count": 2,
            },
        }
    )

    assert metadata["run_id"] == "run_safe"
    assert metadata["api_key"] == "[redacted]"
    assert metadata["nested"]["webhook_url"] == "[redacted]"
    assert metadata["nested"]["count"] == 2


def test_observability_builds_litellm_metadata():
    metadata = observability.build_llm_metadata(
        trace_id="trace-abc",
        run_id="run_abc",
        topic_id="topic_btc",
        node="analyze_card",
        tags=["finbrief", "test"],
        extra={"secret_token": "hidden", "evidence_count": 3},
    )

    assert metadata["trace_id"] == "trace-abc"
    assert metadata["session_id"] == "run_abc"
    assert metadata["generation_name"] == "analyze_card:topic_btc"
    assert metadata["topic_id"] == "topic_btc"
    assert metadata["node"] == "analyze_card"
    assert metadata["tags"] == ["finbrief", "test"]
    assert metadata["secret_token"] == "[redacted]"
    assert metadata["evidence_count"] == 3

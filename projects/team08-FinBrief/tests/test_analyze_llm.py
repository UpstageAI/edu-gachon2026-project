import json
from app.agents import nodes
from app.agents.card_schema import CardContent
from app.core.config import get_settings

def test_analyze_llm_path(monkeypatch):
    import litellm

    class _R:
        class _C:
            class _M:
                content = json.dumps({"headline": "나스닥 사흘째 상승세 지속 랠리",
                                      "lead": "AI 기대 기술주 강세", "body": "본문 내용", "source": "예시통신"})
            message = _M()
        choices = [_C()]

    monkeypatch.setattr(litellm, "completion", lambda **kw: _R())
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)

    out = nodes._analyze({"topic_id": "nasdaq", "name": "나스닥", "category": "MARKET"},
                         {"value": 18120.3, "change_pct": 0.78, "unit": "pt"},
                         [{"title": "t", "snippet": "s"}])
    CardContent(**out)                 # 재검증
    assert len(out["headline"]) <= 20  # 클립 확인


def test_chat_json_passes_langfuse_metadata(monkeypatch):
    from app.core import llm
    from app.core.config import get_settings
    import litellm

    calls = {}

    class _R:
        class _C:
            class _M:
                content = json.dumps({
                    "headline": "비트코인 반등",
                    "lead": "위험자산 선호 회복",
                    "body": "본문 내용",
                    "source": "예시통신",
                })
            message = _M()
        choices = [_C()]

    def _completion(**kwargs):
        calls.update(kwargs)
        return _R()

    monkeypatch.setattr(litellm, "callbacks", [])
    monkeypatch.setattr(litellm, "completion", _completion)

    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://langfuse.example.test")
    get_settings.cache_clear()

    result = llm.chat_json(
        "system",
        "user",
        metadata={
            "trace_id": "trace-abc",
            "session_id": "run_abc",
            "generation_name": "analyze_card:topic_btc",
            "tags": ["finbrief", "test"],
            "secret_token": "hidden",
        },
    )

    assert result["headline"] == "비트코인 반등"
    assert calls["metadata"]["trace_id"] == "trace-abc"
    assert calls["metadata"]["session_id"] == "run_abc"
    assert calls["metadata"]["generation_name"] == "analyze_card:topic_btc"
    assert calls["metadata"]["tags"] == ["finbrief", "test"]
    assert calls["metadata"]["secret_token"] == "[redacted]"
    assert "langfuse_otel" in litellm.callbacks

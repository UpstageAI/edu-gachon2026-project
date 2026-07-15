import json


def test_chat_json_applies_configured_timeout_retry_fallback_and_metadata(monkeypatch):
    from app.core import llm
    from app.core.config import get_settings
    import litellm

    calls = {}

    class _R:
        class _C:
            class _M:
                content = json.dumps({
                    "headline": "나스닥 반등",
                    "lead": "기술주 중심 회복",
                    "body": "뉴스 근거를 바탕으로 변동성을 설명합니다.",
                    "source": "예시통신",
                })
            message = _M()
        choices = [_C()]

    def _completion(**kwargs):
        calls.update(kwargs)
        return _R()

    monkeypatch.setattr(litellm, "completion", _completion)
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")
    monkeypatch.setenv("LITELLM_FALLBACK_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("FINBRIEF_LLM_TIMEOUT_SECONDS", "9")
    monkeypatch.setenv("FINBRIEF_LLM_NUM_RETRIES", "1")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    get_settings.cache_clear()

    result = llm.chat_json(
        "system",
        "user",
        metadata={"trace_id": "trace-1"},
        guardrail_profile="card",
    )

    assert result["headline"] == "나스닥 반등"
    assert calls["timeout"] == 9
    assert calls["num_retries"] == 1
    assert calls["fallbacks"] == [{"model": "openai/gpt-4o-mini"}]
    assert calls["metadata"]["trace_id"] == "trace-1"
    assert calls["metadata"]["llm_fallback_model"] == "openai/gpt-4o-mini"
    assert calls["metadata"]["guardrail_enabled"] is True
    get_settings.cache_clear()


def test_chat_json_raises_guardrail_violation_for_forbidden_output(monkeypatch):
    from app.core import llm
    from app.core.config import get_settings
    from app.core.llm_guardrails import GuardrailViolation
    import litellm
    import pytest

    class _R:
        class _C:
            class _M:
                content = json.dumps({
                    "headline": "지금 매수",
                    "lead": "목표가 상향",
                    "body": "반드시 수익이 난다고 단정합니다.",
                    "source": "예시통신",
                })
            message = _M()
        choices = [_C()]

    monkeypatch.setattr(litellm, "completion", lambda **_: _R())
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-key")
    monkeypatch.delenv("FINBRIEF_LLM_STUB", raising=False)
    get_settings.cache_clear()

    try:
        try:
            llm.chat_json("system", "user", guardrail_profile="card")
        except GuardrailViolation as exc:
            assert exc.reason == "forbidden_terms"
        else:
            raise AssertionError("forbidden card output must raise GuardrailViolation")
    finally:
        get_settings.cache_clear()


def test_analyze_uses_local_fallback_when_llm_guardrail_blocks(monkeypatch):
    from app.agents import nodes
    from app.core.llm_guardrails import GuardrailViolation

    monkeypatch.setattr(nodes.llm, "use_llm", lambda: True)

    def _blocked(*_, **__):
        raise GuardrailViolation("forbidden_terms", {"terms": ["매수"]})

    monkeypatch.setattr(nodes.llm, "chat_json", _blocked)

    result = nodes._analyze(
        {"topic_id": "nasdaq", "name": "나스닥", "category": "MARKET"},
        {"value": 18120.3, "change_pct": 0.78, "unit": "pt"},
        [{"title": "기술주 반등", "snippet": "AI 기대감", "source": "예시통신"}],
    )

    assert result["subtitle"] == "나스닥"
    assert "투자 조언이 아닌" in result["disclaimer"]
    assert "매수" not in result["headline"]

from app.clients import llm


def test_litellm_base_url_uses_external_base_url(monkeypatch):
    monkeypatch.delenv("LITELLM_LOCAL_BASE_URL", raising=False)
    monkeypatch.setenv("LITELLM_BASE_URL", "https://litellm.example.com/v1")

    assert llm.litellm_base_url() == "https://litellm.example.com/v1"


def test_litellm_base_url_default_when_unset(monkeypatch):
    monkeypatch.delenv("LITELLM_LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)

    assert llm.litellm_base_url() == "http://localhost:4000/v1"


def test_ask_returns_message_content(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "master-key")
    monkeypatch.setenv("LITELLM_CHAT_MODEL", "gpt-test")
    monkeypatch.delenv("LITELLM_LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)

    def fake_post_json(url, headers, payload, timeout=None):
        assert url == "http://localhost:4000/v1/chat/completions"
        assert payload["model"] == "gpt-test"
        assert payload["messages"] == [{"role": "user", "content": "안녕"}]
        return {"choices": [{"message": {"content": "안녕하세요!"}}]}

    monkeypatch.setattr(llm, "post_json", fake_post_json)

    assert llm.ask_with_usage("안녕").content == "안녕하세요!"


def test_ask_with_usage_returns_actual_model_and_tokens(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "master-key")
    monkeypatch.setenv("LITELLM_CHAT_MODEL", "cs-chat")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)

    monkeypatch.setattr(
        llm,
        "post_json",
        lambda *args, **kwargs: {
            "model": "upstage/solar-pro",
            "choices": [{"message": {"content": "답변"}}],
            "usage": {
                "prompt_tokens": 120,
                "completion_tokens": 30,
                "total_tokens": 150,
            },
        },
    )

    result = llm.ask_with_usage("문의")

    assert result.content == "답변"
    assert result.model == "upstage/solar-pro"
    assert result.token_usage == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
    }


def test_ask_with_usage_keeps_missing_usage_as_none(monkeypatch):
    monkeypatch.setenv("LITELLM_MASTER_KEY", "master-key")
    monkeypatch.setenv("LITELLM_CHAT_MODEL", "cs-chat")
    monkeypatch.delenv("LITELLM_BASE_URL", raising=False)
    monkeypatch.setattr(
        llm,
        "post_json",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "답변"}}]},
    )

    assert llm.ask_with_usage("문의").token_usage is None

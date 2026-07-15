from app.core.config import Settings


def test_settings_load_default_local_values():
    settings = Settings()

    assert settings.app_name == "FinBrief"
    assert settings.app_version == "0.1.0"
    assert settings.app_env == "local"
    assert settings.api_v1_prefix == "/api/v1"
    assert settings.enable_mock_data is True
    assert settings.delivery_dry_run is True
    assert settings.finbrief_llm_timeout_seconds == 30
    assert settings.finbrief_llm_num_retries == 4
    assert settings.finbrief_llm_guardrail_enabled is True
    assert settings.finbrief_llm_pii_masking is True
    assert "반드시 수익" in settings.finbrief_llm_forbidden_terms
    assert "지금 매수" in settings.finbrief_llm_forbidden_terms
    assert "매수" not in settings.finbrief_llm_forbidden_terms


def test_settings_support_environment_overrides(monkeypatch):
    monkeypatch.setenv("APP_NAME", "FinBrief Test")
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("ENABLE_MOCK_DATA", "false")

    settings = Settings()

    assert settings.app_name == "FinBrief Test"
    assert settings.app_env == "test"
    assert settings.enable_mock_data is False


def test_settings_parse_news_rss_urls_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv(
        "NEWS_RSS_URLS",
        "https://example.com/rss, https://news.example.com/feed",
    )

    settings = Settings()

    assert settings.news_rss_urls == [
        "https://example.com/rss",
        "https://news.example.com/feed",
    ]


def test_settings_parse_llm_forbidden_terms_from_comma_separated_env(monkeypatch):
    monkeypatch.setenv(
        "FINBRIEF_LLM_FORBIDDEN_TERMS",
        "매수, 목표가, 반드시 수익",
    )

    settings = Settings()

    assert settings.finbrief_llm_forbidden_terms == [
        "매수",
        "목표가",
        "반드시 수익",
    ]


def test_settings_reject_api_prefix_without_leading_slash():
    try:
        Settings(api_v1_prefix="api/v1")
    except ValueError as exc:
        assert "api_v1_prefix" in str(exc)
    else:
        raise AssertionError("Settings must reject an API prefix without a leading slash")


def test_public_settings_exclude_secret_values():
    settings = Settings(upstage_api_key="secret-token")

    public_data = settings.public_dict()

    assert "secret-token" not in str(public_data)
    assert "discord_webhook_url" not in public_data

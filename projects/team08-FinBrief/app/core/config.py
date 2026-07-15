"""Runtime configuration for the FinBrief API."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "FinBrief"
    app_version: str = "0.1.0"
    app_env: Literal["local", "test", "dev", "prod"] = "local"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"
    default_timezone: str = "Asia/Seoul"
    enable_mock_data: bool = True

    supabase_url: str | None = None
    supabase_anon_key: SecretStr | None = None
    supabase_service_role_key: SecretStr | None = None
    supabase_db_schema: str = "public"

    litellm_model: str = "upstage/solar-pro"
    litellm_fallback_model: str | None = None
    litellm_proxy_url: str | None = None
    litellm_master_key: SecretStr | None = None
    litellm_guardrails: Annotated[list[str], NoDecode] = Field(default_factory=list)
    upstage_api_key: SecretStr | None = None
    finbrief_llm_stub: bool = True
    finbrief_llm_timeout_seconds: int = Field(default=30, gt=0)
    finbrief_llm_num_retries: int = Field(default=4, ge=0)   # 병렬 카드 생성 시 레이트리밋 버스트 대비
    finbrief_llm_guardrail_enabled: bool = True
    finbrief_llm_require_json: bool = True
    finbrief_llm_require_disclaimer: bool = True
    finbrief_llm_forbidden_terms: Annotated[list[str], NoDecode] = Field(
        # 투자'조언'을 나타내는 구(phrase)만 금지. "매수/매도/보유" 맨 단어는 사실 보도
        # 뉴스(달러 매수세·외환 보유 등)에도 흔히 나와 오탐→카드 폴백을 유발하므로 제외.
        default_factory=lambda: [
            "매수 추천",
            "매도 추천",
            "매수하세요",
            "매도하세요",
            "매수 타이밍",
            "매도 타이밍",
            "보유 추천",
            "지금 매수",
            "지금 매도",
            "지금 사야",
            "지금 팔아야",
            "확정 수익",
            "무조건 상승",
            "반드시 수익",
            "강력 추천",
            "손실 없음",
            "보장 수익",
            "수익 보장",
            "원금 보장",
            "무조건 매수",
            "무조건 매도",
        ]
    )
    finbrief_llm_pii_masking: bool = True

    langfuse_enabled: bool = False
    langfuse_public_key: str | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "https://cloud.langfuse.com"
    langfuse_capture_io: bool = True
    langfuse_flush_on_shutdown: bool = False
    finbrief_trace_salt: SecretStr | None = None

    fred_api_key: SecretStr | None = None
    ecos_api_key: SecretStr | None = None
    news_rss_urls: Annotated[list[str], NoDecode] = Field(default_factory=list)

    delivery_dry_run: bool = True

    @field_validator("api_v1_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("api_v1_prefix must start with '/'")
        return value.rstrip("/") or "/"

    @field_validator("news_rss_urls", mode="before")
    @classmethod
    def split_news_rss_urls(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("finbrief_llm_forbidden_terms", "litellm_guardrails", mode="before")
    @classmethod
    def split_comma_separated_list(cls, value: object) -> object:
        if value is None or value == "":
            return []
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    def public_dict(self) -> dict[str, object]:
        """Return non-secret settings that are safe to expose in API responses."""

        return {
            "app_name": self.app_name,
            "app_version": self.app_version,
            "app_env": self.app_env,
            "api_v1_prefix": self.api_v1_prefix,
            "log_level": self.log_level,
            "default_timezone": self.default_timezone,
            "enable_mock_data": self.enable_mock_data,
            "langfuse_enabled": self.langfuse_enabled,
            "langfuse_capture_io": self.langfuse_capture_io,
            "delivery_dry_run": self.delivery_dry_run,
            "finbrief_llm_stub": self.finbrief_llm_stub,
            "finbrief_llm_guardrail_enabled": self.finbrief_llm_guardrail_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    """Return cached runtime settings."""

    return Settings()

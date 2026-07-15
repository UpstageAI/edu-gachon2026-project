from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# The graph is deliberately bounded to two source attempts and one answer
# revision. A successful search turn can therefore make at most four serial
# LLM requests (router, profile extraction, answer, revised answer) and two
# serial source calls. Keep these constants beside the timeout validation so
# changing either graph bound cannot silently create an impossible deadline.
MAX_LLM_REQUESTS_PER_TURN = 4
MAX_SOURCE_ATTEMPTS_PER_TURN = 2
TURN_RUNTIME_RESERVE_SECONDS = 8.0


def minimum_agent_turn_timeout(
    *,
    llm_request_timeout_seconds: float,
    source_search_timeout_seconds: float,
) -> float:
    """Return the minimum deadline that contains the bounded worst case."""

    return (
        MAX_LLM_REQUESTS_PER_TURN * llm_request_timeout_seconds
        + MAX_SOURCE_ATTEMPTS_PER_TURN * source_search_timeout_seconds
        + TURN_RUNTIME_RESERVE_SECONDS
    )


def source_http_timeout(settings: object) -> float:
    """Read the repository timeout, with a fallback for lightweight test fakes."""

    return float(getattr(settings, "source_http_timeout_seconds", 9.0))


class Settings(BaseSettings):
    """애플리케이션 설정.

    .env 파일 또는 환경변수에서 값을 읽는다. LLM/외부 API 키가 없어도
    앱이 정상적으로 기동되고, 각 계층에서 규칙 기반 fallback으로
    동작하도록 설계했다 (데모/CI 환경에서도 키 없이 실행 가능).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "정책나침반 (Policy Compass)"
    app_env: str = "local"
    log_level: str = "INFO"
    agent_turn_timeout_seconds: float = Field(default=60.0, ge=1.0, le=120.0)
    llm_request_timeout_seconds: float = Field(default=8.0, ge=1.0, le=20.0)
    source_search_timeout_seconds: float = Field(default=10.0, ge=1.0, le=30.0)
    source_http_timeout_seconds: float = Field(default=9.0, ge=0.5, le=29.0)
    chat_session_rate_limit_per_minute: int = Field(default=20, ge=1, le=300)
    chat_ip_rate_limit_per_minute: int = Field(default=120, ge=1, le=3000)
    feedback_session_rate_limit_per_minute: int = Field(default=30, ge=1, le=300)
    feedback_ip_rate_limit_per_minute: int = Field(default=120, ge=1, le=3000)

    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # LLM (Upstage Solar) - 미설정 시 규칙 기반 휴리스틱으로 자동 폴백
    upstage_api_key: str | None = None
    upstage_base_url: str = "https://api.upstage.ai/v1"
    upstage_model: str = "solar-pro2"

    # 온통청년 청년정책 API
    youthcenter_policy_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("YOUTHCENTER_POLICY_API_KEY", "YOUTHCENTER_API_KEY"),
    )
    youthcenter_policy_api_url: str = Field(
        default="https://www.youthcenter.go.kr/go/ythip/getPlcy",
        validation_alias=AliasChoices("YOUTHCENTER_POLICY_API_URL", "YOUTHCENTER_API_URL"),
    )

    # 고용24/HRD-Net 국민내일배움카드 훈련과정 API
    employment24_training_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMPLOYMENT24_TRAINING_API_KEY", "EMPLOYMENT24_API_KEY"),
    )
    employment24_training_api_url: str = Field(
        default="https://www.work24.go.kr/cm/openApi/call/hr/callOpenApiSvcInfo310L01.do",
        validation_alias=AliasChoices("EMPLOYMENT24_TRAINING_API_URL"),
    )

    # 고용24 채용행사·공채속보 API. 무필터 기업정보 endpoint는 사용하지 않는다.
    employment24_job_api_key: str | None = None
    employment24_job_event_api_url: str = Field(
        default="https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L11.do",
        validation_alias=AliasChoices("EMPLOYMENT24_JOB_EVENT_API_URL"),
    )
    employment24_open_recruitment_api_url: str = Field(
        default="https://www.work24.go.kr/cm/openApi/call/wk/callOpenApiSvcInfo210L21.do",
        validation_alias=AliasChoices("EMPLOYMENT24_OPEN_RECRUITMENT_API_URL"),
    )
    # Supabase - 대화 메모리와 training_courses fallback 캐시 공용
    supabase_url: str | None = None
    supabase_key: str | None = None

    # Langfuse - 키가 모두 있을 때만 LangGraph tracing 활성화
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str = "https://cloud.langfuse.com"
    langfuse_tracing_environment: str = "development"

    data_dir: Path = BASE_DIR / "data"

    @model_validator(mode="after")
    def validate_timeout_budget(self) -> Settings:
        """Fail fast when nested timeouts cannot fit inside their parent."""

        if self.source_http_timeout_seconds >= self.source_search_timeout_seconds:
            raise ValueError(
                "SOURCE_HTTP_TIMEOUT_SECONDS must be smaller than "
                "SOURCE_SEARCH_TIMEOUT_SECONDS so the graph owns cancellation"
            )

        minimum_turn_timeout = minimum_agent_turn_timeout(
            llm_request_timeout_seconds=self.llm_request_timeout_seconds,
            source_search_timeout_seconds=self.source_search_timeout_seconds,
        )
        if self.agent_turn_timeout_seconds < minimum_turn_timeout:
            raise ValueError(
                "AGENT_TURN_TIMEOUT_SECONDS is too small for the bounded worst case: "
                f"requires at least {minimum_turn_timeout:g}s "
                f"({MAX_LLM_REQUESTS_PER_TURN} LLM calls, "
                f"{MAX_SOURCE_ATTEMPTS_PER_TURN} source attempts, "
                f"{TURN_RUNTIME_RESERVE_SECONDS:g}s reserve)"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()

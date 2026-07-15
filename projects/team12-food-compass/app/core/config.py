"""pydantic-settings 기반 전역 설정 관리."""
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = True

    upstage_api_key: str = ""
    llm_model: str = "solar-pro3"
    # [2026-07-15] 주 모델(llm_model=solar-pro3) 호출이 실패할 때 대비하는 백업 모델.
    # LiteLLM 같은 게이트웨이 없이 app/core/llm.py에서 코드로 직접 폴백 처리.
    # 주 모델과 반드시 "다른" 모델이어야 폴백 의미가 있음(주 모델과 같으면 장애 시
    # 같은 모델로 재시도라 무의미). 값이 비어있으면 폴백 없이 주 모델만 사용.
    llm_fallback_model: str = "solar-pro2"

    supabase_url: str = ""
    supabase_key: str = ""

    database_url: str = ""

    # [2026-07-14] LLMOps 트레이싱(선택 가점) — langfuse 패키지는 pyproject.toml의
    # "stretch"(선택) 그룹에 있어 CI/팀원 환경엔 기본 설치가 안 됨. 값이 비어있으면
    # app/core/tracing.py가 트레이싱 없이 조용히 넘어감(§0-1 CI 검증에 영향 없음).
    langfuse_tracing_enabled: bool = True
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # langfuse SDK v4 Langfuse(...)의 생성자 인자명이 base_url이라 필드명도 맞춤
    # (구 필드명 langfuse_host였으나 v4에서 host= 인자가 없어 TypeError로 트레이싱이
    # 조용히 비활성화되고 있었음 — 이 필드명은 .env의 LANGFUSE_BASE_URL과 그대로 매핑됨).
    langfuse_base_url: str = ""

    host: str = "0.0.0.0"
    port: int = 8000

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def _disable_noop_fallback(self) -> "Settings":
        """[2026-07-15 코드리뷰 반영] llm_fallback_model이 llm_model과 같은 값으로
        설정되면(.env 오타/오버라이드 등) app/core/llm.py가 장애 시 "같은 죽은 모델"로
        재시도하게 돼 폴백 목적이 무의미해짐 — 이 경우 폴백을 명시적으로 비활성화(빈
        문자열)해 기존 "빈 값이면 폴백 없음" 동작으로 안전하게 수렴시킨다. 앱을 통째로
        거부(예외)시키지 않는 이유: 이 값은 배포 환경변수라 기동 자체를 막기보다
        조용히 무해한 상태로 되돌리는 편이 안전함.
        """
        if self.llm_fallback_model and self.llm_fallback_model == self.llm_model:
            print(
                f"[config] llm_fallback_model이 llm_model과 동일({self.llm_model!r})해 "
                "폴백을 비활성화합니다."
            )
            self.llm_fallback_model = ""
        return self


def get_settings() -> Settings:
    return Settings()


settings = get_settings()

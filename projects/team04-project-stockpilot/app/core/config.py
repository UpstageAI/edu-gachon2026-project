"""애플리케이션 설정.

.env 파일과 환경변수에서 값을 읽어 타입 안전하게 관리한다.
- 다른 모듈에서는 `from app.core.config import settings` 로 사용한다.
- API 키들은 선택(Optional)이라 비어 있어도 서버는 뜬다(Mock 개발 단계 대비).
  실제 연동 단계(Day3)에서 .env에 값을 채운다.
"""
from functools import lru_cache
from typing import Literal

from loguru import logger
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """환경변수 설정 스키마.

    환경변수 이름은 대소문자 구분 없이 필드명과 매핑된다.
    예) UPSTAGE_API_KEY  ->  upstage_api_key
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",          # .env에 모르는 키가 있어도 무시
        case_sensitive=False,
    )

    # ── 실행 환경 ──────────────────────────────
    environment: Literal["development", "staging", "production", "test"] = "development"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    # ── LLM / 임베딩 (Upstage Solar) ───────────
    upstage_api_key: str | None = None
    llm_model: str = "solar-pro3"
    embedding_model: str = "solar-embedding-1-large"
    embedding_dimension: int = 4096

    # ── 뉴스 (네이버 검색 API) ─────────────────
    naver_client_id: str | None = None
    naver_client_secret: str | None = None

    # ── 공시 (OpenDART) ───────────────────────
    dart_api_key: str | None = None

    # pykrx 재무지표·임의 종목명 검색에 사용하는 KRX 로그인
    krx_id: str | None = None
    krx_pw: str | None = None

    # ── RAG / 저장 (Supabase) ─────────────────
    supabase_url: str | None = None
    supabase_key: str | None = None
    rag_chunk_size: int = 1600
    rag_chunk_overlap: int = 200
    rag_embedding_batch_size: int = 16

    # ── 인증 (JWT / 로그인) ───────────────
    jwt_secret: str = "dev-secret-change-me"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7일

    # ── 추가 LLM 제공자 (모델 라우팅/폴백용) ──
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    anthropic_api_key: str | None = None
    llm_guardrails_enabled: bool = True

    # ── 관측(Langfuse LLM 트레이싱) ──
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str | None = None


@lru_cache
def get_settings() -> Settings:
    """설정 싱글톤 반환. lru_cache로 한 번만 생성해 재사용한다."""
    return Settings()


# 전역 설정 객체 — 다른 모듈에서 `from app.core.config import settings`
settings = get_settings()


def warn_missing_keys() -> None:
    """필수 키 누락 시 경고만 남긴다(서버는 계속 실행). 서버 시작 시 호출 예정."""
    missing = [
        name
        for name, value in {
            "UPSTAGE_API_KEY": settings.upstage_api_key,
            "NAVER_CLIENT_ID": settings.naver_client_id,
            "DART_API_KEY": settings.dart_api_key,
            "SUPABASE_URL": settings.supabase_url,
        }.items()
        if not value
    ]
    if missing:
        logger.warning(f"환경변수 미설정(현재 Mock 개발 가능): {', '.join(missing)}")

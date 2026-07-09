import os


class Settings:
    """환경변수 로드. 실제 값은 .env 파일(팀원과 공유 중)에서 채워짐."""

    SUPABASE_DB_URL: str = os.environ.get("SUPABASE_DB_URL", "")
    PORT: int = int(os.environ.get("PORT", "8080"))

    # AI agent가 별도 서비스로 분리될 때 사용할 주소 (아직 미정 — 정해지면 채우기)
    AI_AGENT_BASE_URL: str = os.environ.get("AI_AGENT_BASE_URL", "")


settings = Settings()

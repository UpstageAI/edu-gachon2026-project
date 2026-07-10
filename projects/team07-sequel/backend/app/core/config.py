import os

# 배포된 프론트엔드 실제 URL + 로컬 개발용 Vite dev server 주소.
# CORS_ALLOWED_ORIGINS 환경변수로 덮어쓸 수 있다 (콤마로 구분).
_DEFAULT_CORS_ORIGINS = (
    "https://text2sql-frontend-bfkt3wk5mq-du.a.run.app,"
    "http://localhost:5173"
)


class Settings:
    """환경변수 로드. 실제 값은 .env 파일(팀원과 공유 중)에서 채워짐."""

    SUPABASE_DB_URL: str = os.environ.get("SUPABASE_DB_URL", "")
    PORT: int = int(os.environ.get("PORT", "8080"))

    # AI agent가 별도 서비스로 분리될 때 사용할 주소 (아직 미정 — 정해지면 채우기)
    AI_AGENT_BASE_URL: str = os.environ.get("AI_AGENT_BASE_URL", "")

    # CORS 허용 origin 목록. 기본값은 실제 배포된 프론트엔드 URL + 로컬 개발용 주소.
    # 필요하면 배포 환경에서 환경변수로 덮어쓸 수 있다.
    CORS_ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ]


settings = Settings()

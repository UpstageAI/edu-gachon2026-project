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

    # AI agent(팀원 담당, 별도 Cloud Run 서비스) 실제 배포 주소.
    # 2026-07-10: 팀원의 aiagent 브랜치가 main에 병합되고 CI/CD로 실제 배포된 걸 확인,
    # agent_client.py를 mock에서 실제 HTTP 연동으로 교체하면서 기본값을 채움.
    AI_AGENT_BASE_URL: str = os.environ.get(
        "AI_AGENT_BASE_URL", "https://text2sql-agent-bfkt3wk5mq-du.a.run.app"
    )

    # CORS 허용 origin 목록. 기본값은 실제 배포된 프론트엔드 URL + 로컬 개발용 주소.
    # 필요하면 배포 환경에서 환경변수로 덮어쓸 수 있다.
    CORS_ALLOWED_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")
        if origin.strip()
    ]


settings = Settings()

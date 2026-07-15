from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    supabase_url: str = ""
    supabase_key: str = ""
    database_url_readonly: str = ""
    sql_statement_timeout_ms: int = 5000
    upstage_api_key: str = ""
    upstage_model: str = "solar-pro2"
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 30
    redis_url: str = "redis://localhost:6379/0"
    refresh_token_expire_days: int = 14
    cookie_secure: bool = False
    cors_origins: str = "http://localhost:5173"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_base_url: str = "https://cloud.langfuse.com"

    class Config:
        env_file = ".env"


settings = Settings()

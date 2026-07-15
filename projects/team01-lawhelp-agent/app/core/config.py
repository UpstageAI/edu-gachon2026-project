from dataclasses import dataclass
from os import getenv

from dotenv import load_dotenv


load_dotenv()


def _get_bool(name: str, default: bool = False) -> bool:
    value = getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    environment: str = getenv("ENVIRONMENT", "development")
    debug: bool = _get_bool("DEBUG", False)
    upstage_api_key: str = getenv("UPSTAGE_API_KEY", "")
    llm_model: str = getenv("LLM_MODEL", "solar-pro3")
    langfuse_enabled: bool = _get_bool("LANGFUSE_ENABLED", False)
    langfuse_public_key: str = getenv("LANGFUSE_PUBLIC_KEY", "")
    langfuse_secret_key: str = getenv("LANGFUSE_SECRET_KEY", "")
    langfuse_base_url: str = getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")


settings = Settings()

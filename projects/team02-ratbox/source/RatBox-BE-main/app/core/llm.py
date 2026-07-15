"""LLM 클라이언트 팩토리. Upstage Solar Pro(function calling) 연동."""

from functools import lru_cache

from langchain_upstage import ChatUpstage

from app.core.config import settings


@lru_cache
def get_llm() -> ChatUpstage:
    if not settings.upstage_api_key:
        raise RuntimeError("UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.")
    return ChatUpstage(model=settings.upstage_model, api_key=settings.upstage_api_key)

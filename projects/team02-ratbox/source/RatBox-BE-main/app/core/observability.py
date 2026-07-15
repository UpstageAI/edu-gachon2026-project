"""Langfuse 트레이싱 초기화.

langchain_core만 쓰고(전체 langchain 미설치) 그래프 노드가 일반 파이썬 함수라서,
langfuse.langchain.CallbackHandler 대신 OTel 기반 @observe() 데코레이터로 직접
LLM 호출 지점(generate_sql/classify/find_substitutes/react_agent)을 감싼다.

키가 설정되지 않으면 Langfuse client가 자동으로 비활성화 상태로 생성되므로,
로컬 개발/테스트 환경에서 키 없이도 에러 없이 동작한다.
"""

from langfuse import Langfuse

from app.core.config import settings


def init_langfuse() -> None:
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return

    Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        base_url=settings.langfuse_base_url,
    )

"""Upstage Solar LLM 클라이언트."""

from collections.abc import Iterator
from functools import lru_cache

from openai import OpenAI

from app import config


@lru_cache(maxsize=1)
def _get_client() -> OpenAI:
    """OpenAI 호환 클라이언트를 지연 생성한다(최초 사용 시 1회).

    모듈 로드만으로 API 키를 요구하지 않도록(키 없는 CI에서도 import 가능),
    실제 호출 시점까지 생성을 미룬다. embeddings.py와 동일한 패턴."""
    return OpenAI(api_key=config.UPSTAGE_API_KEY, base_url=config.UPSTAGE_BASE_URL)


def chat(messages: list[dict], temperature: float = 0.0) -> str:
    """Solar 채팅 완성. messages=[{role, content}, ...]"""
    resp = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content


def chat_stream(messages: list[dict], temperature: float = 0.0) -> Iterator[str]:
    """Solar 채팅 응답을 토큰 단위로 스트리밍."""
    stream = _get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        stream=True,
    )

    for chunk in stream:
        if not chunk.choices:
            continue

        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)

        if content:
            yield content

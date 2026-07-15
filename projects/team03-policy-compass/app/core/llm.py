"""Upstage Solar API 클라이언트.

API 키가 없거나 호출이 실패하면 LLMUnavailableError 를 발생시켜, 상위
LangGraph 노드가 규칙 기반 fallback 로직으로 안전하게 전환할 수 있도록 한다.
"""

from __future__ import annotations

import json
import logging
import re
from contextlib import nullcontext

import httpx

from app.core.config import get_settings
from app.core.observability import get_langfuse_client

logger = logging.getLogger(__name__)


class LLMUnavailableError(RuntimeError):
    """LLM API 키가 없거나 호출이 불가능한 상태."""


class SolarLLMClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.upstage_api_key)

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.3,
        response_format_json: bool = False,
        operation_name: str = "solar-chat",
    ) -> str:
        if not self.is_configured:
            raise LLMUnavailableError("UPSTAGE_API_KEY 가 설정되지 않았습니다.")

        payload: dict = {
            "model": self._settings.upstage_model,
            "messages": messages,
            "temperature": temperature,
        }
        if response_format_json:
            payload["response_format"] = {"type": "json_object"}

        headers = {"Authorization": f"Bearer {self._settings.upstage_api_key}"}
        url = f"{self._settings.upstage_base_url}/chat/completions"

        langfuse = get_langfuse_client()
        observation = (
            langfuse.start_as_current_observation(
                name=operation_name,
                as_type="generation",
                input={"message_count": len(messages)},
                model=self._settings.upstage_model,
                model_parameters={
                    "temperature": temperature,
                    "response_format": "json_object" if response_format_json else "text",
                },
            )
            if langfuse is not None
            else nullcontext(None)
        )
        with observation as generation:
            async with httpx.AsyncClient(timeout=self._settings.llm_request_timeout_seconds) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
            content = data["choices"][0]["message"]["content"]
            if generation is not None:
                usage = data.get("usage") or {}
                generation.update(
                    output={"characters": len(content)},
                    usage_details={
                        "input": int(usage.get("prompt_tokens") or 0),
                        "output": int(usage.get("completion_tokens") or 0),
                        "total": int(usage.get("total_tokens") or 0),
                    },
                    metadata={"stage": operation_name},
                )
            return content


def extract_json(text: str) -> dict:
    """LLM 응답에서 JSON 블록만 추출한다. 실패 시 빈 dict 반환."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return {}
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        # 모델 원문에는 사용자 프로필과 대화 문맥이 포함될 수 있으므로 로그에 남기지 않는다.
        logger.warning("LLM 응답에서 JSON 파싱에 실패했습니다.")
        return {}

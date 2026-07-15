"""Experimental ReAct-style agent for StockPilot.

The production path still uses the existing LangGraph router/tool/response
pipeline.  This module is intentionally opt-in so we can demonstrate a true
Reasoning + Acting loop without destabilising the current MVP flow.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from app.core.guardrails import sanitize_llm_output
from app.core.llm import ainvoke_with_fallback
from app.tools.executor import ToolExecutor

READ_ONLY_REACT_TOOLS = {
    "get_stock_price",
    "get_news",
    "get_disclosure",
    "find_positive_news_stocks",
    "lookup_glossary_term",
}
MAX_REACT_STEPS = 4

_EXECUTOR = ToolExecutor()
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

REACT_SYSTEM_PROMPT = """너는 StockPilot의 ReAct(Reasoning + Acting) 실험 에이전트다.
사용자 질문을 해결하기 위해 필요한 경우 도구를 하나씩 선택하고, 관찰 결과를 바탕으로 다음 행동을 정한다.

반드시 JSON 객체 하나만 반환한다. 마크다운 코드블록은 쓰지 않는다.

사용 가능한 action:
- get_stock_price: 특정 종목의 현재가, 등락률, 일봉 차트, 재무지표 조회
  args 예시: {"ticker": "삼성전자", "period": "3m"}
- get_news: 특정 기업 관련 뉴스 조회
  args 예시: {"company": "삼성전자", "direction": "down", "days": 7, "limit": 10}
- get_disclosure: 특정 기업의 최근 OpenDART 공시 조회
  args 예시: {"ticker": "삼성전자", "limit": 8}
- find_positive_news_stocks: 최근 호재/상승 근거가 있는 종목 탐색
  args 예시: {"days": 3, "limit": 5}
- lookup_glossary_term: 투자 용어 설명 검색
  args 예시: {"query": "공시", "limit": 5}
- final: 충분한 관찰 결과가 있을 때 최종 답변 작성

응답 형식:
{
  "thought": "다음 행동을 고른 이유를 한 문장으로 쓴다.",
  "action": "위 action 중 하나",
  "args": {},
  "final": "action이 final일 때만 최종 답변"
}

안전 규칙:
- 특정 종목을 사라/팔라, 매수/매도 추천, 목표주가, 미래 주가 예측은 절대 하지 않는다.
- add_watchlist처럼 사용자의 데이터를 바꾸는 쓰기 도구는 이 ReAct 루프에서 선택하지 않는다.
- 도구 결과에 없는 사실은 만들지 않는다.
- 충분한 근거가 없으면 '확인 가능한 근거가 제한적'이라고 말한다.
- 최종 답변은 초보 투자자도 이해할 수 있게 쉽고 짧게 쓴다."""

FINAL_SYSTEM_PROMPT = """너는 StockPilot의 최종 답변 작성자다.
아래 ReAct 관찰 결과만 근거로 사용자 질문에 답한다.
특정 종목의 매수/매도 추천, 목표주가, 미래 주가 예측은 금지한다.
근거가 부족하면 부족하다고 말하고, 확인 가능한 출처/근거 중심으로 답한다."""


@dataclass
class ReactAgentResult:
    """Final ReAct execution result returned to chat routes."""

    answer: str
    tool_used: str | None = None
    used_model: str | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)


def _parse_react_json(content: str) -> dict[str, Any] | None:
    """Parse the JSON action object from an LLM response."""

    if not content:
        return None

    match = _JSON_RE.search(content.strip())
    raw = match.group(0) if match else content.strip()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ReAct planner returned non-JSON output")
        return None

    action = parsed.get("action")
    if action != "final" and action not in READ_ONLY_REACT_TOOLS:
        logger.warning(f"ReAct planner selected unsupported action: {action}")
        return None

    return {
        "thought": str(parsed.get("thought") or "").strip(),
        "action": action,
        "args": parsed.get("args") if isinstance(parsed.get("args"), dict) else {},
        "final": str(parsed.get("final") or "").strip(),
    }


def _compact_tool_result(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Keep observations small enough for the next ReAct planning step."""

    if not result.get("success"):
        return {
            "success": False,
            "error": result.get("error"),
            "error_type": result.get("error_type"),
        }

    data = result.get("data") or {}
    if tool_name == "get_stock_price":
        return {
            "success": True,
            "name": data.get("name"),
            "ticker": data.get("ticker"),
            "current_price": data.get("current_price"),
            "change_pct": data.get("change_pct"),
            "as_of": data.get("as_of"),
            "snapshot_at": data.get("snapshot_at"),
            "period": data.get("period"),
            "fundamentals_available": data.get("fundamentals_available"),
            "ohlcv_count": len(data.get("ohlcv") or []),
        }

    if tool_name == "get_news":
        return {
            "success": True,
            "company": data.get("company"),
            "direction": data.get("direction"),
            "news": [
                {
                    "title": item.get("title"),
                    "source": item.get("source_domain") or item.get("source"),
                    "url": item.get("original_link") or item.get("link") or item.get("url"),
                    "reason": item.get("reason"),
                    "direction_keywords": item.get("direction_keywords") or [],
                    "market_session": item.get("market_session"),
                }
                for item in (data.get("news") or [])[:5]
            ],
        }

    if tool_name == "get_disclosure":
        return {
            "success": True,
            "ticker": data.get("ticker"),
            "disclosures": [
                {
                    "title": item.get("report_name") or item.get("title"),
                    "date": item.get("received_date") or item.get("date"),
                    "corp": item.get("corp_name"),
                    "url": item.get("source_url") or item.get("url"),
                }
                for item in (data.get("disclosures") or [])[:5]
            ],
        }

    if tool_name == "find_positive_news_stocks":
        return {
            "success": True,
            "stocks": [
                {
                    "ticker": item.get("ticker"),
                    "change_pct": item.get("change_pct"),
                    "top_news": item.get("top_news"),
                    "url": item.get("url"),
                }
                for item in (data.get("stocks") or [])[:5]
            ],
        }

    if tool_name == "lookup_glossary_term":
        return {
            "success": True,
            "query": data.get("query"),
            "terms": [
                {
                    "term": item.get("term"),
                    "definition": item.get("definition"),
                    "aliases": item.get("aliases") or [],
                    "example": item.get("example"),
                    "source_url": item.get("source_url"),
                }
                for item in (data.get("terms") or [])[:5]
            ],
        }

    return {"success": True, "data": data}


def _tool_stream_payload(tool_name: str, result: dict[str, Any]) -> dict[str, Any]:
    """Shape ReAct tool observations into the same SSE-friendly card buckets."""

    data = result.get("data") or {}
    payload: dict[str, Any] = {"react_observation": _compact_tool_result(tool_name, result)}
    if tool_name == "get_stock_price":
        payload["price"] = data
    elif tool_name == "get_news":
        payload["news"] = data.get("news") or []
    elif tool_name == "get_disclosure":
        payload["disclosures"] = data.get("disclosures") or []
    elif tool_name == "find_positive_news_stocks":
        payload["stocks"] = data.get("stocks") or []
    elif tool_name == "lookup_glossary_term":
        payload["terms"] = data.get("terms") or []
    return payload


def _history_prompt(user_message: str, steps: list[dict[str, Any]]) -> str:
    """Build the compact ReAct scratchpad sent to the planner."""

    lines = [f"사용자 질문: {user_message}", "", "지금까지의 관찰:"]
    if not steps:
        lines.append("- 아직 도구를 사용하지 않음")
    for index, step in enumerate(steps, start=1):
        lines.append(
            f"{index}. thought={step.get('thought')}; "
            f"action={step.get('action')}; args={json.dumps(step.get('args') or {}, ensure_ascii=False)}; "
            f"observation={json.dumps(step.get('observation') or {}, ensure_ascii=False)}"
        )
    lines.append("")
    lines.append("다음에 할 행동을 JSON 하나로 반환해라.")
    return "\n".join(lines)


async def _plan_next_action(
    *,
    user_message: str,
    steps: list[dict[str, Any]],
    model_id: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """Ask the LLM which action to take next."""

    result = await ainvoke_with_fallback(
        [
            SystemMessage(content=REACT_SYSTEM_PROMPT),
            HumanMessage(content=_history_prompt(user_message, steps)),
        ],
        model_id=model_id,
        timeout_seconds=25,
    )
    parsed = _parse_react_json(result.message.content or "")
    used_model = result.model_name or result.model_id
    return parsed, used_model


async def _forced_final_answer(
    *,
    user_message: str,
    steps: list[dict[str, Any]],
    model_id: str | None,
) -> tuple[str, str | None]:
    """Generate a final answer from observations when the planner did not stop."""

    result = await ainvoke_with_fallback(
        [
            SystemMessage(content=FINAL_SYSTEM_PROMPT),
            HumanMessage(content=_history_prompt(user_message, steps)),
        ],
        model_id=model_id,
        timeout_seconds=35,
    )
    return (result.message.content or "").strip(), result.model_name or result.model_id


async def run_react_agent(
    *,
    message: str,
    session_id: str,
    model_id: str | None = None,
) -> ReactAgentResult:
    """Run a bounded ReAct loop and return the final answer."""

    steps: list[dict[str, Any]] = []
    used_model: str | None = None
    tool_names: list[str] = []

    for _ in range(MAX_REACT_STEPS):
        plan, plan_model = await _plan_next_action(
            user_message=message,
            steps=steps,
            model_id=model_id,
        )
        used_model = plan_model or used_model
        if not plan:
            break

        action = plan["action"]
        if action == "final":
            answer = sanitize_llm_output(plan.get("final") or "")
            return ReactAgentResult(
                answer=answer or "확인 가능한 근거가 부족해 답변을 만들지 못했습니다.",
                tool_used=",".join(tool_names) or None,
                used_model=used_model,
                steps=steps,
            )

        result = await _EXECUTOR.execute(action, plan.get("args") or {}, session_id=session_id)
        observation = _compact_tool_result(action, result)
        steps.append(
            {
                "thought": plan.get("thought"),
                "action": action,
                "args": plan.get("args") or {},
                "observation": observation,
            }
        )
        tool_names.append(action)

    answer, final_model = await _forced_final_answer(
        user_message=message,
        steps=steps,
        model_id=model_id,
    )
    used_model = final_model or used_model
    return ReactAgentResult(
        answer=sanitize_llm_output(answer or "확인 가능한 근거가 부족해 답변을 만들지 못했습니다."),
        tool_used=",".join(tool_names) or None,
        used_model=used_model,
        steps=steps,
    )


async def stream_react_agent(
    *,
    message: str,
    session_id: str,
    model_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Stream ReAct progress events as dictionaries for the chat SSE route."""

    steps: list[dict[str, Any]] = []
    used_model: str | None = None
    tool_names: list[str] = []

    for _ in range(MAX_REACT_STEPS):
        yield {
            "type": "thinking",
            "node": "react",
            "content": "다음에 사용할 근거 도구를 판단하고 있어요...",
        }
        plan, plan_model = await _plan_next_action(
            user_message=message,
            steps=steps,
            model_id=model_id,
        )
        used_model = plan_model or used_model
        if not plan:
            break

        thought = plan.get("thought") or "근거 확인이 필요합니다."
        yield {"type": "thinking", "node": "react", "content": thought}

        action = plan["action"]
        if action == "final":
            answer = sanitize_llm_output(plan.get("final") or "")
            yield {
                "type": "response",
                "node": "react",
                "content": answer or "확인 가능한 근거가 부족해 답변을 만들지 못했습니다.",
                "tool_used": ",".join(tool_names) or None,
                "model": used_model,
            }
            return

        result = await _EXECUTOR.execute(action, plan.get("args") or {}, session_id=session_id)
        observation = _compact_tool_result(action, result)
        steps.append(
            {
                "thought": thought,
                "action": action,
                "args": plan.get("args") or {},
                "observation": observation,
            }
        )
        tool_names.append(action)
        yield {
            "type": "tool",
            "node": "react",
            "tool_name": action,
            "tool_result": _tool_stream_payload(action, result),
        }

    yield {
        "type": "thinking",
        "node": "react",
        "content": "수집한 근거를 바탕으로 최종 답변을 정리하고 있어요...",
    }
    answer, final_model = await _forced_final_answer(
        user_message=message,
        steps=steps,
        model_id=model_id,
    )
    used_model = final_model or used_model
    yield {
        "type": "response",
        "node": "react",
        "content": sanitize_llm_output(answer or "확인 가능한 근거가 부족해 답변을 만들지 못했습니다."),
        "tool_used": ",".join(tool_names) or None,
        "model": used_model,
    }

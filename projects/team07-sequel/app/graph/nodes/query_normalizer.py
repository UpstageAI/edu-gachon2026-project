"""query_normalizer 노드 — 한국어 질문 전처리 (SQL 링킹 앞단).

한국어 질문은 조사·상대시간·후속참조가 섞여 그대로 매칭하기 어렵다. 이를
뒤 단계(schema linker)가 다루기 쉬운 형태로 정리한다.

- 시간 표현 정규화: 규칙(코드) — "지난달" → 실제 날짜 범위 (LLM 아님, 정확·저렴)
- 키워드 추출 + 후속질문 병합 + 모호어 판정: LLM(게이트웨이)
- 의미 보존: 원문(question)은 그대로 두고 파생값만 추가

입력(state): question, history(옵션)
출력(state): normalized_question, keywords, time_range, ambiguous
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta

from app.core import prompts
from app.core.llm import complete
from app.graph.state import AgentState


def _time_range(text: str) -> dict:
    """상대 시간 표현 → {"start","end"} (오늘 기준). 없으면 {}."""
    today = date.today()

    def r(s: date, e: date) -> dict:
        return {"start": s.isoformat(), "end": e.isoformat()}

    if "지난달" in text or "저번달" in text:
        first_this = today.replace(day=1)
        last_prev = first_this - timedelta(days=1)
        return r(last_prev.replace(day=1), last_prev)
    if "이번달" in text or "이번 달" in text:
        return r(today.replace(day=1), today)
    if "올해" in text:
        return r(date(today.year, 1, 1), today)
    if "작년" in text:
        return r(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    if m := re.search(r"최근\s*(\d+)\s*일", text):
        days = min(int(m.group(1)), 3650)  # 상한 ~10년: OverflowError·비현실 범위 방어
        return r(today - timedelta(days=days), today)
    if "어제" in text:
        y = today - timedelta(days=1)
        return r(y, y)
    if "오늘" in text:
        return r(today, today)
    return {}


def normalize(state: AgentState) -> dict:
    question = state["question"]
    time_range = _time_range(question)

    ctx = question
    history = state.get("history") or []
    if history:
        prev = "; ".join(h.get("q", "") for h in history[-2:])
        ctx = f"이전 질문: {prev}\n현재 질문: {question}"

    res = complete("solar-mini", [
        {"role": "system", "content": prompts.NORMALIZER},
        {"role": "user", "content": ctx},
    ], temperature=0.0)

    normalized, keywords, ambiguous = question, [], False
    try:
        obj = json.loads(res.text)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if isinstance(obj, dict):  # LLM 이 계약을 어겨도(타입 위반) 안전 기본값 유지
        nq = obj.get("normalized_question")
        normalized = nq if isinstance(nq, str) and nq.strip() else question
        kw = obj.get("keywords")
        keywords = [k for k in kw if isinstance(k, str) and k.strip()] if isinstance(kw, list) else []
        ambiguous = obj.get("ambiguous") is True  # bool("false")==True 회피: 엄격 비교

    return {
        "normalized_question": normalized,
        "keywords": keywords,
        "time_range": time_range,
        "ambiguous": ambiguous,
    }

from __future__ import annotations

import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import ainvoke_structured_with_fallback
from app.prompts.prompts import ROUTER_SYSTEM_PROMPT, VALIDATION_SYSTEM_PROMPT
from app.schemas import ParseQuery, ValidateQuery

from .state import AgentState

# 가격 관련 키워드 (keyword fallback 전용)
_PRICE_KEYWORDS: set[str] = {
    "비싸", "비싼", "싸다", "저렴", "시세", "가격", "얼마", "원",
    "사도", "사야", "구매", "살만", "요즘", "지금", "할만", "비쌈", "쌈",
}

# 식품 품목 목록 (keyword fallback 전용)
_FOOD_ITEMS: set[str] = {
    "상추", "배추", "오이", "당근", "깻잎", "파", "마늘", "감자", "고추",
    "양파", "무", "시금치", "브로콜리", "양배추", "애호박", "가지", "토마토",
    "사과", "딸기", "바나나", "수박", "참외", "포도", "복숭아",
    "쌀", "고구마", "콩나물", "두부",
    # [시나리오 1: 쌀 vs 즉석밥] 가공식품 별칭 — app/tools/item_alias.py와 이름을 맞춤
    "즉석밥", "햇반",
}

# 품목명 뒤에 붙어도 식품 언급으로 인정할 한국어 조사 목록
_PARTICLES = {
    "가", "이", "는", "은", "을", "를", "의", "도", "에", "로", "으로",
    "와", "과", "랑", "이랑", "에서", "이나", "나", "하고", "만",
    "까지", "부터", "마저", "조차", "이며", "며", "이고", "고",
}

def _item_in_query(item: str, query: str) -> bool:
    """품목명이 공백 분리 토큰 안에서 온전히 포함되는지 확인.

    - "오이랑" → "오이" + 조사 "랑" → 매칭
    - "파이썬" → "파" + "이썬"(조사 아님) → 미매칭
    """
    for token in re.split(r"[\s?!.,~]", query):
        if not token.startswith(item):
            continue
        remainder = token[len(item):]
        if remainder == "" or remainder in _PARTICLES:
            return True
    return False

def _keyword_router(query: str) -> ParseQuery:
    """키워드 기반 Fallback 라우터 — LLM 오류 시 사용."""
    found_items = [item for item in _FOOD_ITEMS if _item_in_query(item, query)]
    has_price_keyword = any(kw in query for kw in _PRICE_KEYWORDS)
    if found_items or has_price_keyword:
        return ParseQuery(intent="price", items=found_items)
    return ParseQuery(intent="off-topic", items=[])


async def _llm_router(query: str) -> ParseQuery:
    """Upstage Solar LLM 구조화 출력 라우터. 주/백업 모델 모두 실패 시 keyword fallback."""
    try:
        messages = [
            SystemMessage(content=ROUTER_SYSTEM_PROMPT),
            HumanMessage(content=f"사용자 질문: {query}"),
        ]
        result = await ainvoke_structured_with_fallback(ParseQuery, messages)
        print(f"[Router] 의도: {result.intent}, 품목: {result.items}")
        return result
    except Exception as e:
        print(f"[Router] LLM 오류 → keyword fallback: {e}")
        return _keyword_router(query)


async def router_node(state: AgentState) -> dict[str, Any]:
    query = state["user_query"]
    result = await _llm_router(query)
    return {"route": result.intent, "items": result.items}


async def validate_request_node(state: AgentState) -> dict[str, Any]:
    """[2차 방어] Router가 price/knowledge/hybrid로 분류하고 품목을 추출했더라도,
    실제로는 장난·롤플레잉 대사체 문장에 식품 키워드가 우연히 섞여 있을 뿐인 경우를
    걸러낸다(예: "햄부기 북딱스 상추 인 더 버거를 대령해오거라. 얼마인가?" — "상추"가
    추출돼 price로 분류되지만 진짜 가격 질문이 아님, 2026-07-14 사용자 재현 확인).

    Router와 같은 LLM 호출에 필드만 추가하면 이미 내린 결론을 그대로 반복할 위험이
    있어, 독립된 LLM 호출로 "1차 분류·품목 추출이 실제로 타당한가"만 다시 판단한다.
    검증 자체가 실패(타임아웃 등)하면 안전하게 1차 분류를 그대로 통과시킨다 — 이
    노드는 오탐(false positive) 방지용 방어선이지, 정상 요청까지 막는 게 목적이 아님.
    """
    try:
        messages = [
            SystemMessage(content=VALIDATION_SYSTEM_PROMPT),
            HumanMessage(
                content=(
                    f"질문: {state['user_query']!r} "
                    f"(1차 분류: {state.get('route')}, 품목: {state.get('items', [])})"
                )
            ),
        ]
        result = await ainvoke_structured_with_fallback(ValidateQuery, messages)
        print(f"[validate_request] is_valid={result.is_valid}, reason={result.reason}")
        if not result.is_valid:
            return {"route": "off-topic", "items": []}
        return {}
    except Exception as e:
        print(f"[validate_request] 검증 LLM 오류 → 1차 분류 그대로 통과: {e}")
        return {}
from __future__ import annotations

import json
from typing import Any

from langchain_upstage import ChatUpstage

from app.core.config import settings
from app.graph.state import AgentState

_EXTRACTION_SYSTEM_PROMPT = """당신은 사용자 문장에서 "지역명"과 "물가 계산 단위"를 추출하는 파서입니다.

규칙:
- region: 대한민국 광역시/도 단위로 정규화해서 반환하세요. (예: "경기", "판교" → "경기도" / "서울", "강남" → "서울특별시")
  문장에 지역 정보가 없으면 null로 반환하세요.
- unit: 물가 계산 단위를 숫자+단위 형태 그대로 추출하세요. (예: "100g", "1kg", "1개", "1공기")
  문장에 단위 정보가 없으면 null로 반환하세요.
- 반드시 아래 JSON 형식으로만 응답하세요. 다른 설명, 마크다운 코드블록(```)을 절대 포함하지 마세요.

{"region": "string 또는 null", "unit": "string 또는 null"}
"""


def _get_llm() -> ChatUpstage:
    print(f"[debug] api_key set: {bool(settings.upstage_api_key)}")
    return ChatUpstage(
        api_key=settings.upstage_api_key,
        model=settings.llm_model,
        timeout=30,
        max_retries=2,
        # [2026-07-15 추가] app/core/llm.py의 build_llm()과 동일한 이유(퇴화된 반복
        # 생성 방어) — 이 함수는 region/unit만 담은 짧은 JSON을 반환해야 하므로 더
        # 짧게 제한.
        max_tokens=200,
        frequency_penalty=0.4,
    )
llm = _get_llm()


def _parse_llm_json(raw_text: str) -> dict[str, Any]:
    """LLM이 반환한 텍스트를 안전하게 JSON으로 파싱.

    혹시 모델이 ```json 코드블록으로 감싸거나 앞뒤에 설명을 붙이는 경우를 대비해
    가장 바깥쪽 {}만 추출해서 파싱을 시도한다.
    """
    text = raw_text.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start > end:
        return {"region": None, "unit": None}

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {"region": None, "unit": None}

    return {
        "region": parsed.get("region") or None,
        "unit": parsed.get("unit") or None,
    }


def user_input_node(state: AgentState) -> dict[str, Any]:
    """사용자 입력에서 지역명과 물가 계산 단위를 확보.

    프론트엔드에서 이미 selectbox로 확정된 region/unit이 넘어온 경우
    LLM 호출 없이 그대로 통과시키고, 없는 경우(예: 텍스트로만 질문한 경우)에만
    LLM으로 사용자 발화에서 추출을 시도한다.

    [2026-07-15 코드리뷰 반영] 기존엔 region/unit 중 하나만 있어도(예: region만
    있고 unit은 없는 경우) 둘 다 없는 것으로 보고 LLM 추출 결과로 전체를 덮어써서,
    이미 확보된 필드까지 LLM이 못 찾으면 None으로 지워버리는 문제가 있었음 — 필드별로
    이미 있는 값은 그대로 유지하고, 누락된 필드만 LLM 추출 결과로 보완하도록 수정.
    """
    existing_region = state.get("region")
    existing_unit = state.get("unit")

    if existing_region and existing_unit:
        print(f"[user_input_node] 프론트에서 전달받은 값 사용: region={existing_region!r}, unit={existing_unit!r}")
        return {"region": existing_region, "unit": existing_unit}

    query = state.get("user_query", "")

    if not query.strip():
        print("[user_input_node] 사용자 입력이 비어있음")
        return {"region": existing_region, "unit": existing_unit}

    try:
        response = llm.invoke(
            [
                ("system", _EXTRACTION_SYSTEM_PROMPT),
                ("human", query),
            ]
        )
        result = _parse_llm_json(response.content)
    except Exception as e:
        print(f"[user_input_node] LLM 추출 실패: {type(e).__name__}: {e}")
        return {"region": existing_region, "unit": existing_unit}

    region = existing_region or result["region"]
    unit = existing_unit or result["unit"]
    print(f"[user_input_node] 필드별 병합 결과: region={region!r}, unit={unit!r}")

    return {"region": region, "unit": unit}
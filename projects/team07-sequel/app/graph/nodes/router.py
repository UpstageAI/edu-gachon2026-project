"""router 노드 — 안전성(injection) + 난이도(하/중/상/최상) 를 LLM 1콜로 판정, 모델 선택.

기존 가드·분류 2콜을 ROUTER_JUDGE 1콜로 병합(질의당 mini 호출·지연 절감).
난이도 기준은 AI Hub hardness 역산(docs/difficulty_criteria.md). 앞단 schema_link 가
링크한 스키마를 함께 줘 조인 필요 여부를 판단하게 한다.

fail-closed: ok 가 엄격히 boolean True 일 때만 통과. bool("false")==True 같은
강제변환·ok 누락·파싱 실패는 전부 차단으로 본다(하드 게이트는 sqlglot validator).

입력(state): normalized_question(없으면 question), schema
출력(state): difficulty(str), model(str), safety({"ok": bool, "reason": str})
"""
import json

from app.core import prompts
from app.core.llm import complete
from app.core.settings import settings
from app.graph.state import AgentState, Difficulty

_JUDGE_MODEL = "solar-mini"  # 판정은 저렴한 모델로 (생성 모델과 별개)
_VALID = {d.value for d in Difficulty}
_BLOCK_MSG = "안전성을 확인할 수 없어 요청을 차단했어요. 질문을 바꿔 다시 시도해 주세요."


def route(state: AgentState) -> dict:
    question = state.get("normalized_question") or state["question"]
    schema = state.get("schema", "")
    # 하드 절단 금지: M-Schema 도입 후 스키마가 길어져(§6) 앞부분만 자르면 정작 필요한
    # 테이블이 잘려 LLM 이 "관련 테이블 없음"을 안전성 문제로 오판해 정상 질문을 차단하는
    # 회귀가 있었다(예: freight_value 가 2296번째 글자라 [:1500] 밖). 전체를 준다.
    user = f"# 관련 스키마(참고)\n{schema}\n\n# 질문\n{question}" if schema else question
    res = complete(_JUDGE_MODEL, [
        {"role": "system", "content": prompts.ROUTER_JUDGE},
        {"role": "user", "content": user},
    ], temperature=0.0)

    try:
        obj = json.loads(res.text)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if not (isinstance(obj, dict) and obj.get("ok") is True):
        reason = obj.get("reason") if isinstance(obj, dict) else ""
        return {"safety": {"ok": False, "reason": reason or _BLOCK_MSG}, "difficulty": "", "model": ""}

    d = obj.get("difficulty")
    difficulty = d if d in _VALID else Difficulty.MEDIUM.value  # 파싱 실패 시 안전 폴백
    # route_force_model 이 있으면(런칭 안정화 = 전부 pro2) 그 값으로, 없으면 검증된 난이도 라우팅.
    model = settings.route_force_model or settings.model_by_difficulty[difficulty]
    return {"difficulty": difficulty, "model": model, "safety": {"ok": True, "reason": ""}}

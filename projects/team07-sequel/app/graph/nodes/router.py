"""router 노드 — 난이도(하/중/상/최상) 분류 + solar 모델 선택 + injection 가드레일.

난이도 기준은 데이터셋(AI Hub hardness) 역산 결과 = SQL 구성요소 기준
(하:단순조회 / 중:집계 / 상:정렬·랭킹 / 최상:JOIN·서브쿼리). 근거: docs/difficulty_criteria.md.
SQL 생성 전이라 질문으로 예측하되, 앞단 schema_link 가 링크한 스키마를 함께 줘
LLM 이 조인 필요 여부를 판단하게 한다. 분류 모델 문자열은 settings.model_by_difficulty.
(게이트웨이: core.llm / 프롬프트: core.prompts.ROUTER_CLASSIFY, INJECTION_GUARD)

입력(state): normalized_question(없으면 question), schema
출력(state): difficulty(str), model(str), safety({"ok": bool, "reason": str})
"""
import json

from app.core import prompts
from app.core.llm import complete
from app.core.settings import settings
from app.graph.state import AgentState, Difficulty

_CLASSIFY_MODEL = "solar-mini"  # 분류/가드는 저렴한 모델로 (생성 모델과 별개)
_VALID = {d.value for d in Difficulty}


def _classify(question: str, schema: str) -> str:
    """난이도 분류. 파싱 실패 시 medium 으로 안전 폴백."""
    user = f"# 관련 스키마(참고)\n{schema[:1500]}\n\n# 질문\n{question}" if schema else question
    res = complete(_CLASSIFY_MODEL, [
        {"role": "system", "content": prompts.ROUTER_CLASSIFY},
        {"role": "user", "content": user},
    ], temperature=0.0)
    try:
        d = json.loads(res.text).get("difficulty")
    except (json.JSONDecodeError, AttributeError):
        d = None
    return d if d in _VALID else Difficulty.MEDIUM.value


def _guard(question: str) -> dict:
    """injection/위험 판정. ok 가 엄격히 boolean True 일 때만 통과(fail-closed).

    bool("false")==True 같은 강제변환·ok 누락·파싱 실패는 전부 차단으로 본다.
    (하드 게이트는 sqlglot validator 지만, 가드도 검증 불가 시 통과시키지 않는다.)
    """
    res = complete(_CLASSIFY_MODEL, [
        {"role": "system", "content": prompts.INJECTION_GUARD},
        {"role": "user", "content": question},
    ], temperature=0.0)
    try:
        obj = json.loads(res.text)
    except (json.JSONDecodeError, TypeError):
        obj = None
    if isinstance(obj, dict) and obj.get("ok") is True:
        return {"ok": True, "reason": ""}
    reason = obj.get("reason") if isinstance(obj, dict) else ""
    return {"ok": False, "reason": reason or "안전성을 확인할 수 없어 요청을 차단했어요. 질문을 바꿔 다시 시도해 주세요."}


def route(state: AgentState) -> dict:
    question = state.get("normalized_question") or state["question"]
    safety = _guard(question)
    if not safety["ok"]:
        return {"safety": safety, "difficulty": "", "model": ""}
    difficulty = _classify(question, state.get("schema", ""))
    # route_force_model 이 있으면(런칭 안정화 = 전부 pro2) 그 값으로, 없으면 검증된 난이도 라우팅.
    model = settings.route_force_model or settings.model_by_difficulty[difficulty]
    return {"difficulty": difficulty, "model": model, "safety": safety}

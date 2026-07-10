"""formatter 노드 — 실행 결과를 표 + 자연어 요약으로 만든다.

결론 먼저(숫자·근거 명시), SQL 원문 함께 제공. 안전성 거절/검증 실패/결과 없음은
각각 고정 안내 메시지로 분기. 정상 결과는 LLM 으로 요약.
(게이트웨이: core.llm / 프롬프트: core.prompts.SUMMARY)

입력(state): question, result, sql, validation, safety
출력(state): answer({"summary", "table", "sql", "disclaimer"})
"""
from app.core import prompts
from app.core.llm import complete
from app.graph.state import AgentState, empty_answer


def format_answer(state: AgentState) -> dict:
    # 1) 안전성 거절 (injection/위험 요청)
    safety = state.get("safety", {})
    if not safety.get("ok", True):
        return {"answer": empty_answer(
            summary=safety.get("reason") or "그 요청은 데이터를 변경할 수 있어 실행하지 않았어요. 저는 조회만 도와드려요.",
        )}

    # 2) 검증 소진 (재시도 후에도 실패)
    if not state.get("validation", {}).get("ok", True):
        return {"answer": empty_answer(
            summary="질문을 조금 다르게 표현해 주시겠어요? 안전한 SQL 을 만들지 못했어요.",
            sql=state.get("sql", ""),
        )}

    result = state.get("result", {})
    rows = result.get("rows", [])

    # 3) 결과 없음
    if not rows:
        return {"answer": empty_answer(
            summary="조건에 맞는 데이터가 없습니다. 기간을 넓혀볼까요?",
            sql=state.get("sql", ""),
        )}

    # 4) 정상 — 결과 기반 자연어 요약 (LLM)
    ctx = (
        f"질문: {state['question']}\n"
        f"결과 컬럼: {result.get('columns', [])}\n"
        f"결과 행(일부): {rows[:5]}"
    )
    res = complete(
        state.get("model", "solar-mini"),
        [
            {"role": "system", "content": prompts.SUMMARY},
            {"role": "user", "content": ctx},
        ],
        temperature=0.3,
    )
    return {"answer": empty_answer(
        summary=res.text.strip(),
        table={"columns": result.get("columns", []), "rows": rows},
        sql=state.get("sql", ""),
        disclaimer="이 결과는 조회 시점 기준입니다.",
    )}

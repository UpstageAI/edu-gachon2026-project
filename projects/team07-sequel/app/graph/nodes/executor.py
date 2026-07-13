"""executor 노드 — 검증된 SQL 을 읽기전용으로 실행하고 결과를 포맷한다.

SELECT 만, LIMIT·타임아웃 강제. 결과 형태(scalar/table)를 판별해 반환.
실행 런타임 오류(없는 컬럼·타입 오류 등)는 exec_error 로 캡처해 수리 루프
(builder: execute→generate 재시도)로 넘긴다 — MapleRepair 의 실행 피드백.
빈 결과는 오류가 아니다(정당한 답 — formatter 가 안내).

입력(state): sql
출력(state): result({"columns","rows","format","truncated"}), exec_error(str)
"""
from app.graph.state import AgentState
from app.tools.sql_executor import execute_sql


def execute(state: AgentState) -> dict:
    try:
        result = execute_sql(state.get("sql", ""))
        return {"result": result.model_dump(), "exec_error": ""}
    except Exception as e:  # noqa: BLE001 — 런타임 오류 → 수리 루프 신호
        return {"result": {"columns": [], "rows": [], "format": "table", "truncated": False},
                "exec_error": str(e)[:300]}

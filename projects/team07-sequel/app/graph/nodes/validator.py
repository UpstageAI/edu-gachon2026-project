"""validator 노드 — 실행 전 SQL 을 검증한다 (sqlglot).

문법 파싱, SELECT 만 허용, 금지 키워드/DDL·DML 차단, 화이트리스트 밖 테이블/컬럼,
위험 패턴을 점검한다. (도구: tools.sql_validator)

입력(state): sql, schema
출력(state): validation({"ok": bool, "errors": list[str]})
"""
from app.graph.state import AgentState
from app.tools.sql_validator import validate_sql


def validate(state: AgentState) -> dict:
    result = validate_sql(state.get("sql", ""), state.get("schema", ""), state.get("tables"))
    return {"validation": result.model_dump()}

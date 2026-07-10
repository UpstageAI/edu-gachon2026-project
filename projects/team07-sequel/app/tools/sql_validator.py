"""sql_validator 도구 — sqlglot 로 SQL 을 검증한다 (실행 전 안전 게이트).

입력: sql(str), schema(str) — schema 는 참고용, 화이트리스트는 카탈로그에서 직접 확인
출력: ValidationResult(ok, errors)
검사: 파싱 가능 · 단일 문장 · SELECT 만 · DML/DDL 금지 · 화이트리스트 밖 테이블 거부.
"""
from __future__ import annotations

import sqlglot
from sqlglot import exp

from app.repositories import schema_repository
from app.tools.schemas import ValidationResult

# 쓰기/DDL/명령 계열 — 하나라도 있으면 거부
_BANNED = (
    exp.Insert, exp.Update, exp.Delete, exp.Merge,
    exp.Drop, exp.Create, exp.Alter, exp.TruncateTable, exp.Command,
)


def validate_sql(sql: str, schema: str = "") -> ValidationResult:
    errors: list[str] = []
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except Exception as e:  # noqa: BLE001
        return ValidationResult(ok=False, errors=[f"SQL 파싱 실패: {e}"])

    if len(statements) != 1:
        errors.append("정확히 한 개의 SELECT 문만 허용됩니다.")

    allowed = {t.lower() for t in schema_repository.list_tables()}
    for st in statements:
        for banned in _BANNED:
            if st.find(banned) is not None:
                errors.append(f"금지된 구문: {banned.__name__}")
        if st.find(exp.Select) is None:
            errors.append("SELECT 문만 허용됩니다.")
        # WITH(CTE) 별칭은 테이블이 아니라 이 쿼리 안의 임시 이름 → 화이트리스트 예외
        # (없으면 최상 난이도의 CTE 분해 SQL 이 항상 오탈락됨)
        cte_names = {c.alias_or_name.lower() for c in st.find_all(exp.CTE)}
        for tbl in st.find_all(exp.Table):
            name = (tbl.name or "").lower()
            if name and name not in allowed and name not in cte_names:
                errors.append(f"허용되지 않은 테이블: {tbl.name}")

    return ValidationResult(ok=not errors, errors=sorted(set(errors)))

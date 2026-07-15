"""sql_validator 도구 — sqlglot 로 SQL 을 검증한다 (실행 전 안전 게이트).

입력: sql(str), schema(str, 참고용), tables(list[str]|None) — 링크된 테이블 허용목록
출력: ValidationResult(ok, errors)
검사: 파싱 가능 · 단일 문장 · SELECT 만 · DML/DDL 금지 · 허용목록 밖 테이블 거부.
허용목록은 링크된 tables 우선(생성기가 본 스키마와 일치 → 미링크 테이블 참조 차단),
없으면 카탈로그 전체로 폴백.
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


def validate_sql(sql: str, schema: str = "", tables: list[str] | None = None) -> ValidationResult:
    errors: list[str] = []
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except Exception as e:  # noqa: BLE001
        return ValidationResult(ok=False, errors=[f"SQL 파싱 실패: {e}"])

    if len(statements) != 1:
        errors.append("정확히 한 개의 SELECT 문만 허용됩니다.")

    # 링크된 테이블을 허용목록으로(생성기가 본 스키마와 동일). 비면 카탈로그로 폴백.
    allowed = {t.lower() for t in (tables or schema_repository.list_tables())}
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

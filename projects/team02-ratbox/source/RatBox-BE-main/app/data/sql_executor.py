"""LLM이 생성한 SQL을 실행 전에 검증하고, 읽기 전용 커넥션으로 실행하는 계층.

자유 SQL 문자열을 그대로 실행하되, sqlglot AST로 "단일 SELECT문 + 화이트리스트
테이블만"을 강제한 뒤에만 읽기 전용 role/커넥션으로 실행한다.
"""

import psycopg2
import psycopg2.extras
import sqlglot
from sqlglot import exp

from app.core.config import settings

ALLOWED_TABLES = {"recipes", "recipe_ingredients", "ingredients_master"}


def validate_select_only(sql: str) -> None:
    try:
        statements = [s for s in sqlglot.parse(sql) if s is not None]
    except sqlglot.errors.SqlglotError as error:
        raise ValueError(f"SQL을 파싱할 수 없습니다: {error}") from error

    if len(statements) != 1:
        raise ValueError("단일 SELECT 문만 허용됩니다.")

    statement = statements[0]
    if not isinstance(statement, exp.Select):
        raise ValueError("SELECT 문만 허용됩니다.")

    tables = {table.name for table in statement.find_all(exp.Table)}
    disallowed = tables - ALLOWED_TABLES
    if disallowed:
        raise ValueError(f"허용되지 않은 테이블 접근: {disallowed}")


def execute_readonly_sql(sql: str) -> list[dict]:
    validate_select_only(sql)

    conn = psycopg2.connect(
        settings.database_url_readonly,
        options=f"-c statement_timeout={settings.sql_statement_timeout_ms}",
    )
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(sql)
            return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()

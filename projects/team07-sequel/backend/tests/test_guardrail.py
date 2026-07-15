"""guardrail.validate_sql() 테스트.

guardrail은 AI agent가 생성한 SQL이 실행되기 전 마지막으로 걸러주는
안전장치라서, 여기서 검증하는 세 가지 규칙(SELECT 전용, 위험 키워드 차단,
LIMIT 강제)이 실제로 지켜지는지가 가장 중요하다.
"""

import pytest

from app.services.guardrail import GuardrailError, validate_sql


class TestSelectOnly:
    def test_select_query_passes(self):
        result = validate_sql("SELECT * FROM olist_orders")
        assert result.upper().startswith("SELECT")

    def test_lowercase_select_passes(self):
        # SQL 키워드는 대소문자를 가리지 않아야 한다.
        result = validate_sql("select * from olist_orders")
        assert result.startswith("select")

    def test_leading_whitespace_select_passes(self):
        # agent 응답에 개행/공백이 섞여 와도 정상 처리돼야 한다.
        result = validate_sql("   \n  SELECT 1")
        assert "SELECT" in result.upper()

    def test_with_cte_query_passes(self):
        # 2026-07-10 실사용 중 발견된 버그: "카테고리별 매출" 같은 집계 질문에
        # agent가 WITH(CTE)로 감싼 SQL을 만들면, 예전엔 "SELECT로 시작 안 함"으로
        # 오탐 차단됐었다. WITH도 읽기 전용 구문이라 허용해야 한다.
        sql = (
            "WITH category_revenue AS ("
            "SELECT p.product_category_name AS category, SUM(oi.price) AS revenue "
            "FROM olist_order_items oi JOIN olist_products p ON oi.product_id = p.product_id "
            "GROUP BY p.product_category_name"
            ") SELECT * FROM category_revenue ORDER BY revenue DESC"
        )
        result = validate_sql(sql)
        assert result.upper().startswith("WITH")
        assert "LIMIT 200" in result.upper()

    def test_with_clause_containing_write_keyword_is_still_rejected(self):
        # WITH를 허용하더라도, 그 안에 쓰기 키워드가 숨어있으면 여전히 차단돼야 한다
        # (_FORBIDDEN_KEYWORDS 검사가 별도로 잡아준다).
        sql = "WITH x AS (INSERT INTO olist_orders VALUES (1) RETURNING *) SELECT * FROM x"
        with pytest.raises(GuardrailError):
            validate_sql(sql)

    @pytest.mark.parametrize(
        "sql",
        [
            "INSERT INTO olist_orders VALUES (1)",
            "UPDATE olist_orders SET status='x'",
            "DELETE FROM olist_orders",
            "DROP TABLE olist_orders",
            "",
            "이것은 SQL이 아닙니다",
        ],
    )
    def test_non_select_query_rejected(self, sql):
        with pytest.raises(GuardrailError):
            validate_sql(sql)


class TestForbiddenKeywords:
    @pytest.mark.parametrize(
        "keyword",
        ["insert", "update", "delete", "drop", "alter", "truncate", "grant", "revoke", "create"],
    )
    def test_forbidden_keyword_in_subquery_rejected(self, keyword):
        # SELECT로 시작하더라도, 서브쿼리 등 어디에 위험 키워드가 섞여 있으면 차단돼야 한다.
        sql = f"SELECT * FROM olist_orders WHERE 1=1; {keyword} something"
        with pytest.raises(GuardrailError):
            validate_sql(sql)

    def test_keyword_as_substring_of_column_name_is_not_a_problem_case(self):
        # 주의: 지금 구현은 단어 경계(\\b)를 쓰므로 "created_at" 같은 컬럼명은
        # "create"와 겹치지 않는다 (create 다음에 바로 단어 경계가 와야 함).
        # 이 테스트는 향후 정규식을 손댈 때 이 동작이 회귀하지 않았는지 확인하는 안전망이다.
        result = validate_sql("SELECT created_at FROM olist_orders")
        assert "created_at" in result


class TestLimitEnforcement:
    def test_missing_limit_gets_default_limit_appended(self):
        result = validate_sql("SELECT * FROM olist_orders")
        assert "LIMIT 200" in result.upper()

    def test_existing_limit_is_preserved(self):
        result = validate_sql("SELECT * FROM olist_orders LIMIT 5")
        assert result.upper().count("LIMIT") == 1
        assert "LIMIT 5" in result.upper()

    def test_trailing_semicolon_handled_before_limit_append(self):
        result = validate_sql("SELECT * FROM olist_orders;")
        # 세미콜론 뒤에 LIMIT을 잘못 붙여서 문법 오류가 나면 안 된다.
        assert result.rstrip().endswith(";")
        assert "LIMIT 200" in result.upper()

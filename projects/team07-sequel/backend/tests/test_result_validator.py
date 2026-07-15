"""result_validator.validate_result() 테스트.

guardrail이 "SQL이 실행되기 전, 안전한가"를 봤다면, 여기는 "SQL이 실행된
후, 결과가 타당한가"를 본다. 행 수/스키마 일관성/타입 일관성 세 가지 검사가
의도대로 통과/차단되는지 확인한다.
"""

import pytest

from app.services.result_validator import ResultValidationError, validate_result


class TestNormalCases:
    def test_normal_rows_pass(self):
        rows = [{"category": "a", "count": 10}, {"category": "b", "count": 20}]
        validate_result(rows)  # 예외 없이 통과해야 한다.

    def test_none_values_are_allowed_and_ignored_in_type_check(self):
        # DB의 NULL은 정상적인 값이라, 타입 일관성 검사에서 무시돼야 한다.
        rows = [{"a": 1}, {"a": None}, {"a": 3}]
        validate_result(rows)

    def test_single_row_passes(self):
        validate_result([{"a": 1, "b": "x"}])


class TestSchemaConsistency:
    def test_mismatched_columns_across_rows_raises(self):
        rows = [{"a": 1, "b": 2}, {"a": 1, "c": 3}]
        with pytest.raises(ResultValidationError, match="컬럼 구성"):
            validate_result(rows)

    def test_missing_column_in_later_row_raises(self):
        rows = [{"a": 1, "b": 2}, {"a": 1}]
        with pytest.raises(ResultValidationError):
            validate_result(rows)


class TestTypeConsistency:
    def test_mixed_types_in_same_column_raises(self):
        rows = [{"count": 10}, {"count": "twenty"}]
        with pytest.raises(ResultValidationError, match="타입"):
            validate_result(rows)

    def test_int_and_float_are_considered_different_types(self):
        # type(10) is int, type(10.5) is float — 지금 구현은 엄격하게 다른 타입으로 본다.
        rows = [{"price": 10}, {"price": 10.5}]
        with pytest.raises(ResultValidationError):
            validate_result(rows)

    def test_same_type_across_many_rows_passes(self):
        rows = [{"count": i} for i in range(50)]
        validate_result(rows)


class TestRowCountLimit:
    def test_rows_within_limit_pass(self):
        rows = [{"x": i} for i in range(200)]
        validate_result(rows)

    def test_rows_exceeding_limit_raises(self):
        rows = [{"x": i} for i in range(201)]
        with pytest.raises(ResultValidationError, match="행 수"):
            validate_result(rows)

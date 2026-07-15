import pytest

from app.data.sql_executor import validate_select_only


def test_validate_select_only_accepts_simple_select():
    validate_select_only("SELECT id, name FROM recipes WHERE cooking_time <= 30")


def test_validate_select_only_rejects_non_select():
    with pytest.raises(ValueError):
        validate_select_only("DROP TABLE recipes")


def test_validate_select_only_rejects_ddl_dml():
    with pytest.raises(ValueError):
        validate_select_only("INSERT INTO recipes (name) VALUES ('x')")
    with pytest.raises(ValueError):
        validate_select_only("UPDATE recipes SET name = 'x'")


def test_validate_select_only_rejects_disallowed_table():
    with pytest.raises(ValueError):
        validate_select_only("SELECT * FROM user_allergens")


def test_validate_select_only_rejects_multiple_statements():
    with pytest.raises(ValueError):
        validate_select_only("SELECT * FROM recipes; DROP TABLE recipes;")


def test_validate_select_only_rejects_stacked_injection():
    with pytest.raises(ValueError):
        validate_select_only(
            "SELECT * FROM recipes WHERE id = '1'; DELETE FROM recipes WHERE '1'='1'"
        )


def test_validate_select_only_rejects_malformed_sql():
    with pytest.raises(ValueError):
        validate_select_only("SELECT * FROM recipes WHERE name = 'unterminated")

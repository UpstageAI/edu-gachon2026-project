"""도구(tool) 입출력 계약 — Pydantic 스키마.

각 도구의 반환 형태를 타입으로 못박는다. 노드는 이 모델을 받아 state 에
`.model_dump()` 로 저장한다.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SchemaRetrievalResult(BaseModel):
    """schema_retriever 결과 — 관련 테이블 + DDL + 조인 경로."""

    tables: list[str] = Field(default_factory=list)
    ddl: str = ""
    joins: list[str] = Field(default_factory=list)  # 예: "olist_orders.order_id = olist_order_items.order_id"


class ValueHint(BaseModel):
    """질의 키워드 ↔ 실제 DB 값 매칭 1건.

    how="ambiguous": 근접 후보가 둘 이상(마진 작음) → 버리지 않고 candidates 로 노출(되묻기).
    """

    keyword: str
    column: str = ""                 # "table.column"
    value: str = ""                  # DB 에 실제 존재하는 값 (또는 시간범위 문자열)
    how: Literal["exact", "synonym", "fuzzy", "embedding", "ambiguous", "time_range", "not_found"] = "not_found"
    score: Optional[float] = None
    candidates: list[str] = Field(default_factory=list)  # ambiguous 시 되묻기 후보(top-2)


class ValueRetrievalResult(BaseModel):
    """value_retriever 결과 — 해소된 값 힌트 + 미해소 키워드."""

    hints: list[ValueHint] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)


class ValidationResult(BaseModel):
    """sql_validator 결과."""

    ok: bool = False
    errors: list[str] = Field(default_factory=list)


class ExecutionResult(BaseModel):
    """sql_executor 결과 — 실행된 표."""

    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    format: Literal["scalar", "table", "chart", "text"] = "table"
    truncated: bool = False

"""DB 실행 결과 검증 (신뢰성 문제 대응을 위한 백엔드 측 2차 방어선, 결과 버전).

guardrail.py가 "실행 전 SQL이 안전한 형태인가"를 본다면, 이 파일은
"실행 후 결과가 타당한 형태인가"를 본다. AI agent가 만든 SQL이 문법적으로는
안전(guardrail 통과)해도, 의도치 않게 이상한 결과(컬럼이 행마다 다르거나,
한 컬럼 안에 타입이 뒤섞이는 등)를 낼 수 있어서 실행 결과 자체를 한 번 더
확인한다.

주의: 결과가 0건인 경우(NO_RESULT)는 이 파일이 아니라 query.py에서 별도로
처리한다. 여기는 "결과가 있긴 한데 형태가 이상한 경우"만 다룬다.
"""

_MAX_ROWS = 200  # guardrail이 붙이는 기본 LIMIT과 동일 — 이 이상이면 뭔가 어긋난 것


class ResultValidationError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_result(rows: list[dict]) -> None:
    """DB 실행 결과의 스키마/타입/행 수가 일관적인지 확인한다.

    검사 항목:
    1. 행 수 — guardrail의 기본 LIMIT(200)을 벗어나면 비정상으로 간주
    2. 스키마 일관성 — 모든 행이 동일한 컬럼 집합을 가져야 함
    3. 타입 일관성 — 같은 컬럼의 값들은 (None을 제외하면) 같은 타입이어야 함

    통과 시 아무것도 반환하지 않고, 실패 시 ResultValidationError를 던진다.
    """

    if len(rows) > _MAX_ROWS:
        raise ResultValidationError(
            f"결과 행 수가 예상 범위를 벗어났습니다 ({len(rows)}행)."
        )

    expected_columns = set(rows[0].keys())

    column_types: dict[str, type] = {}

    for row in rows:
        if set(row.keys()) != expected_columns:
            raise ResultValidationError("결과의 컬럼 구성이 행마다 일치하지 않습니다.")

        for column, value in row.items():
            if value is None:
                continue
            value_type = type(value)
            existing_type = column_types.get(column)
            if existing_type is None:
                column_types[column] = value_type
            elif existing_type is not value_type:
                raise ResultValidationError(
                    f"'{column}' 컬럼에 서로 다른 타입의 값이 섞여 있습니다."
                )

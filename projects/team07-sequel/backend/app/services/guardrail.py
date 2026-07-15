"""SQL 안전성 2차 검증 (신뢰성 문제 대응을 위한 백엔드 측 최후 방어선).

AI agent가 생성한 SQL을 곧이곧대로 실행하지 않고, 여기서 한 번 더 확인한다.
DB 연결 자체도 text2sql_reader(읽기 전용) 계정이라 쓰기 자체는 DB 레벨에서도
막히지만, 사용자에게 "왜 실패했는지" 명확한 이유를 보여주려면 앱 레벨에서
먼저 걸러주는 것이 좋다.
"""

import re

# SELECT뿐 아니라 WITH(CTE, Common Table Expression)로 시작하는 쿼리도 허용한다.
# "카테고리별 매출" 같은 집계 쿼리는 agent가 WITH 절로 감싸서 만드는 경우가
# 흔한데, WITH 자체는 읽기 전용 구문이고 그 안에 쓰기 키워드가 숨어있어도
# 아래 _FORBIDDEN_KEYWORDS 검사가 그건 별도로 잡아준다. 그래서 시작 키워드만
# SELECT로 제한하면 정상적인 CTE 쿼리까지 오탐으로 차단하게 된다 (2026-07-10 수정).
_SELECT_ONLY = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|grant|revoke|create)\b",
    re.IGNORECASE,
)
_HAS_LIMIT = re.compile(r"\blimit\s+\d+", re.IGNORECASE)
_DEFAULT_LIMIT = 200


class GuardrailError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def validate_sql(sql: str) -> str:
    """SELECT 전용 여부를 확인하고, LIMIT이 없으면 기본 LIMIT을 붙여서 돌려준다."""

    stripped = sql.strip()

    if not _SELECT_ONLY.match(stripped):
        raise GuardrailError("SELECT(또는 WITH로 시작하는 CTE) 조회 쿼리만 허용됩니다.")

    if _FORBIDDEN_KEYWORDS.search(stripped):
        raise GuardrailError("데이터를 변경하거나 스키마를 수정하는 쿼리는 허용되지 않습니다.")

    if not _HAS_LIMIT.search(stripped):
        stripped = stripped.rstrip(";").rstrip() + f" LIMIT {_DEFAULT_LIMIT};"

    return stripped

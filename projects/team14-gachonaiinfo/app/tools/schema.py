"""도구 스키마 — Router가 고를 수 있는 도구들의 단일 정의.

파라미터 이름은 ToolExecutor(app/tools/executor.py)가 실제로 소비하는 한국어 키와
정확히 일치해야 한다. 포맷은 Anthropic tool-use 표준(name/description/input_schema).
prompts.py의 산문 설명과 이 스키마가 어긋나지 않도록 함께 관리한다.
"""

from typing import Any

# 트랙 명칭은 recommend_courses가 받는 유일한 허용값 집합(교육과정 기준).
TRACKS = ["Intelligent SW", "AIoT", "Vision & Language", "AI부트캠프"]

# 세부 이수구분: calc_graduation_progress가 학번별 요건과 대조해 남은 학점을 계산.
_CREDIT_FIELDS = {
    "전공": "전공(필수+선택 통합) 이수 학점. 전 학번 공통 72 기준.",
    "전공필수": "전공필수 이수 학점.",
    "전공선택": "전공선택 이수 학점.",
    "공통필수": "공통필수(옛 융합교양) 이수 학점.",
    "공통선택": "공통선택(옛 기초교양) 이수 학점.",
}

TOOLS_SCHEMA: list[dict[str, Any]] = [
    {
        "name": "calc_graduation_progress",
        "description": (
            "사용자가 이수 학점을 말하며 졸업까지 남은 학점을 물을 때 사용한다. "
            "학번을 알면 함께 넘겨 해당 학번의 졸업요건 기준으로 계산한다 "
            "(전공필수/전공선택/공통 기준은 학번별로 다름)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "학번": {
                    "type": "integer",
                    "description": "입학년도 4자리(예: 2024). 세부 이수구분 계산 시 필요.",
                },
                **{
                    name: {"type": "integer", "minimum": 0, "description": desc}
                    for name, desc in _CREDIT_FIELDS.items()
                },
            },
            "additionalProperties": False,
            # 이수 학점이 최소 하나는 있어야 계산 가능(executor가 없으면 에러 반환).
            "anyOf": [{"required": [f]} for f in _CREDIT_FIELDS],
        },
    },
    {
        "name": "recommend_courses",
        "description": "특정 학년/학기에 어떤 과목을 들어야 하는지 물을 때 사용한다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "학년": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4,
                    "description": "학년(1~4).",
                },
                "학기": {
                    "type": "integer",
                    "enum": [1, 2],
                    "description": "학기(1 또는 2).",
                },
                "트랙": {
                    "type": "string",
                    "enum": TRACKS,
                    "description": "트랙(선택). 미지정 시 전체 트랙 대상.",
                },
            },
            "required": ["학년", "학기"],
            "additionalProperties": False,
        },
    },
    {
        "name": "send_reminder_email",
        "description": (
            "사용자가 이메일 주소를 직접 적으며 학사 일정을 이메일로 리마인드/발송해달라고 "
            "할 때 사용한다. 즉시 발송이 아니라 예약만 등록하며, 실제 발송은 스케줄러가 "
            "처리한다."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "이메일": {
                    "type": "string",
                    "format": "email",
                    "description": "리마인드를 받을 수신자 이메일 주소.",
                },
                "내용": {
                    "type": "string",
                    "description": "리마인드 본문/대상 일정. 미지정 시 '학사 일정 리마인드'.",
                },
                "발송예정시각": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "발송 예정 시각(ISO 8601). 멀티턴 확인 흐름에서 파싱한 값을 그대로 "
                        "넘긴다. 미지정 시 executor가 내용에서 재파싱한다."
                    ),
                },
            },
            "required": ["이메일"],
            "additionalProperties": False,
        },
    },
]

# 이름 → 스키마 빠른 조회용.
TOOLS_BY_NAME: dict[str, dict[str, Any]] = {t["name"]: t for t in TOOLS_SCHEMA}

# Router가 고를 수 있는 유효한 도구 이름 집합.
TOOL_NAMES: frozenset[str] = frozenset(TOOLS_BY_NAME)


def _as_int(value: Any) -> int | None:
    """executor가 int(...)로 관대하게 받는 것과 동일하게, int/숫자문자열만 정수로 환산.
    환산 불가면 None(→ 호출측에서 타입 오류로 처리)."""
    if isinstance(value, bool):  # bool은 int 서브클래스라 별도로 배제
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def validate_tool_args(tool_name: str, args: dict[str, Any] | None) -> str | None:
    """도구 인자를 TOOLS_SCHEMA 기준으로 검증. 통과하면 None, 실패하면 오류 메시지 반환.

    executor의 관대함을 존중한다: 숫자 필드는 int/숫자문자열을 모두 허용하고,
    date-time 필드는 문자열/ datetime 객체를 모두 허용한다(타입 강제 대신 값 검증).
    검증 범위: 미지 도구 · 필수 필드 · anyOf · enum · 알 수 없는 필드 · 숫자 범위.
    """
    schema = TOOLS_BY_NAME.get(tool_name)
    if schema is None:
        return f"알 수 없는 도구: {tool_name}"

    args = args or {}
    input_schema = schema["input_schema"]
    props: dict[str, Any] = input_schema.get("properties", {})

    # 알 수 없는 필드
    if input_schema.get("additionalProperties") is False:
        unknown = set(args) - set(props)
        if unknown:
            return f"알 수 없는 인자: {', '.join(sorted(unknown))}"

    # 필수 필드
    for field in input_schema.get("required", []):
        if args.get(field) is None:
            return f"필수 인자 누락: {field}"

    # anyOf(예: 이수 학점 중 최소 하나) — 각 절의 required가 하나라도 충족되면 통과
    any_of = input_schema.get("anyOf")
    if any_of and not any(
        all(args.get(f) is not None for f in clause.get("required", [])) for clause in any_of
    ):
        needed = sorted({f for clause in any_of for f in clause.get("required", [])})
        return f"다음 중 최소 하나가 필요합니다: {', '.join(needed)}"

    # 필드별 값 검증(값이 있는 것만)
    for name, value in args.items():
        if value is None:
            continue
        spec = props.get(name, {})
        typ = spec.get("type")

        if "enum" in spec:
            enum = spec["enum"]
            # enum이 전부 정수면 executor처럼 숫자문자열도 허용해 비교.
            candidate = _as_int(value) if all(isinstance(v, int) for v in enum) else value
            if candidate not in enum:
                allowed = ", ".join(str(v) for v in enum)
                return f"{name} 값이 올바르지 않습니다. 허용: {allowed}"

        if typ == "integer":
            n = _as_int(value)
            if n is None:
                return f"{name}은(는) 정수여야 합니다."
            if "minimum" in spec and n < spec["minimum"]:
                return f"{name}은(는) {spec['minimum']} 이상이어야 합니다."
            if "maximum" in spec and n > spec["maximum"]:
                return f"{name}은(는) {spec['maximum']} 이하여야 합니다."

    return None

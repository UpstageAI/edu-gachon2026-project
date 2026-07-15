from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_REDACTED = "[민감정보 삭제]"


@dataclass(frozen=True)
class SensitiveDataPattern:
    label: str
    pattern: re.Pattern[str]


SENSITIVE_DATA_PATTERNS = (
    SensitiveDataPattern(
        "주민등록번호·외국인등록번호 형태",
        re.compile(r"(?<!\d)\d{6}\s*-?\s*[1-8]\d{6}(?!\d)"),
    ),
    SensitiveDataPattern(
        "전화번호 형태",
        re.compile(r"(?<!\d)(?:\+82[ -]?)?0?1[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)"),
    ),
    SensitiveDataPattern(
        "이메일 주소",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?![\w.-])"),
    ),
    SensitiveDataPattern(
        "계좌번호 형태",
        re.compile(r"(?:계좌(?:번호)?|통장번호)\s*[:：]?\s*(?:\d[ -]?){8,20}"),
    ),
    SensitiveDataPattern(
        "카드·금융번호 형태",
        re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    ),
)


def detect_sensitive_data(text: str) -> list[str]:
    """Return stable, deduplicated labels for sensitive identifiers in text."""

    detected: list[str] = []
    remaining = text
    for item in SENSITIVE_DATA_PATTERNS:
        if item.pattern.search(remaining):
            detected.append(item.label)
            # 주민등록번호가 일반 금융번호로도 중복 분류되지 않도록 먼저
            # 감지한 범위를 제거한 뒤 다음 유형을 검사한다.
            remaining = item.pattern.sub(_REDACTED, remaining)
    return detected


def redact_sensitive_text(text: str) -> str:
    redacted = text
    for item in SENSITIVE_DATA_PATTERNS:
        redacted = item.pattern.sub(_REDACTED, redacted)
    return redacted


def redact_sensitive_structure(value: Any) -> Any:
    """Recursively redact strings before structured memory is stored or reused."""

    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive_structure(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_sensitive_structure(item) for item in value)
    return value


def privacy_guard_reply(detected_labels: list[str]) -> str:
    labels = "·".join(detected_labels) if detected_labels else "민감 개인정보"
    return (
        f"입력에서 민감 개인정보({labels})를 감지해 정책 검색을 중단했어요. "
        "이 정보는 답변 생성 모델이나 외부 정책 API에 전달하지 않고, 대화 기록에는 삭제 표식만 저장합니다. "
        "정책 추천에는 주민등록번호·연락처·계좌번호가 필요하지 않아요. "
        "만 나이, 거주 지역, 취업·재학 상태, 관심 분야처럼 필요한 조건만 알려주세요."
    )

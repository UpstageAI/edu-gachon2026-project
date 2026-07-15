"""외부 AI 서비스로 전송하기 전 문의의 개인정보를 마스킹한다."""

import logging
import re
from collections import Counter
from typing import TypedDict

logger = logging.getLogger(__name__)

MASKING_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "이메일",
        re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+(?![\w.-])"),
        "[이메일]",
    ),
    (
        "주민등록번호",
        re.compile(r"(?<!\d)\d{6}\s*-?\s*[1-4]\d{6}(?!\d)"),
        "[주민등록번호]",
    ),
    ("카드번호", re.compile(r"(?<!\d)(?:\d[ -]?){15}\d(?!\d)"), "[카드번호]"),
    (
        "전화번호",
        re.compile(r"(?<!\d)(?:\+82[- ]?1[016789]|01[016789])[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
        "[전화번호]",
    ),
    (
        "전화번호",
        re.compile(r"(?<!\d)(?:02|0[3-6][1-5])[- ]?\d{3,4}[- ]?\d{4}(?!\d)"),
        "[전화번호]",
    ),
    (
        "이름",
        re.compile(r"((?:이름|성명)\s*[:：]\s*)[가-힣]{2,5}"),
        r"\1[이름]",
    ),
    (
        "주소",
        re.compile(r"((?:주소|배송지)\s*[:：]\s*)[^\n,]+"),
        r"\1[주소]",
    ),
    (
        "계좌번호",
        re.compile(r"((?:계좌번호|계좌)\s*[:：]\s*)[\d -]{8,20}"),
        r"\1[계좌번호]",
    ),
    (
        "여권번호",
        re.compile(r"((?:여권번호|여권)\s*[:：]\s*)[A-Za-z0-9-]{6,12}"),
        r"\1[여권번호]",
    ),
)


class MaskingResult(TypedDict):
    masked_text: str
    counts: dict[str, int]


def mask_personal_info_with_details(text: str) -> MaskingResult:
    """마스킹 결과와 유형별 치환 건수를 반환한다."""
    masked = text
    counts: Counter[str] = Counter()
    for name, pattern, replacement in MASKING_RULES:
        masked, count = pattern.subn(replacement, masked)
        counts[name] += count

    filtered_counts = {name: count for name, count in counts.items() if count}
    summary = ", ".join(f"{name}={count}건" for name, count in filtered_counts.items())
    logger.info(
        "개인정보 마스킹 완료: 입력=%d자 출력=%d자 총=%d건 유형=%s",
        len(text),
        len(masked),
        sum(filtered_counts.values()),
        summary or "없음",
    )
    return {"masked_text": masked, "counts": filtered_counts}

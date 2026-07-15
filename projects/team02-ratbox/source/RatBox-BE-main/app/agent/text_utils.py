"""LLM이 생성한 텍스트에서 마크다운 서식 기호를 제거해 순수 텍스트로 만든다.

프론트는 마크다운을 렌더링하지 않고 텍스트 그대로 표시하므로, 프롬프트로
마크다운 금지를 지시해도 LLM이 가끔 **볼드**/`코드`/인용부호 등을 섞어 답할 때를
대비한 방어적 후처리다.
"""

import re


def strip_markdown(text: str) -> str:
    if not text:
        return text

    result = text
    result = re.sub(r"\*\*(.+?)\*\*", r"\1", result)  # **볼드**
    result = re.sub(r"__(.+?)__", r"\1", result)  # __볼드__
    result = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", r"\1", result)  # *이탤릭*
    result = re.sub(r"`([^`]+)`", r"\1", result)  # `코드`
    result = re.sub(r"^[ \t]*#{1,6}\s*", "", result, flags=re.MULTILINE)  # # 헤더
    result = re.sub(r"(^|\n|\.\s+)[ \t]*>\s*", r"\1", result)  # > 인용 (줄 시작/문장 뒤 모두)
    result = re.sub(r"(^|\n|\.\s+)[ \t]*[-*+]\s+", r"\1", result)  # - 불릿 (줄 시작/문장 뒤 모두)
    return result.strip()

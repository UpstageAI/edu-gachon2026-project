"""비밀정보 마스킹: diff나 로그를 모델에 보내기 전에 민감한 값을 가린다.

PR의 변경 내용(patch)이나 체크 로그에는 실수로 API 키, 토큰, 비밀번호,
개인 키가 들어 있을 수 있다. 그런 값을 그대로 외부 모델에 보내면 유출
위험이 있으므로, prompt_builder가 프롬프트를 만들기 전에 이 함수로 한 번
걸러 낸다. 핵심은 정규식(regex)으로 "비밀처럼 생긴" 문자열을 찾아 <masked>로
바꾸는 것이다.
"""

from __future__ import annotations

import re

# 비밀정보로 의심되는 문자열을 찾는 정규식(regex) 목록.
# 정규식은 "이런 모양의 글자"를 찾는 패턴 언어다. re.compile로 미리 만들어 두면
# 매번 다시 해석하지 않아 빠르다.
SECRET_PATTERNS = [
    # 1) "api_key: xxxx" "token=xxxx" 처럼 이름=값 형태. (?i)는 대소문자 무시.
    #    괄호 두 개로 이름과 값을 각각 그룹(group)으로 잡아 둔다.
    re.compile(r"(?i)(api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?([A-Za-z0-9_\-./+=]{8,})"),
    # 2) GitHub 토큰 형식(ghp_, gho_ 등으로 시작하는 긴 문자열).
    re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    # 3) PEM 개인 키 블록 전체. re.S는 줄바꿈까지 포함해 여러 줄을 한 덩어리로 매칭한다.
    re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----.*?-----END [A-Z ]+PRIVATE KEY-----", re.S),
]


def mask_secrets(text: str) -> str:
    """텍스트에서 비밀처럼 보이는 부분을 찾아 가려진 표시로 바꾼 새 문자열을 돌려준다."""
    masked = text
    for pattern in SECRET_PATTERNS:
        # pattern.groups = 그 정규식이 잡아 둔 그룹(괄호)의 개수.
        # 이름=값 패턴(그룹 2개 이상)이면 이름은 남기고 값만 가린다.
        if pattern.groups >= 2:
            # sub(...)는 매칭된 부분을 교체한다. lambda는 "이름=<masked>" 형태를 만든다.
            masked = pattern.sub(lambda match: f"{match.group(1)}=<masked>", masked)
        else:
            # 토큰/개인 키처럼 값 전체가 비밀이면 통째로 가린다.
            masked = pattern.sub("<masked-secret>", masked)
    return masked


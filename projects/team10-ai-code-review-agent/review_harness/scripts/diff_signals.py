"""diff 신호(signal) 추출기: PR의 변경 내용에서 "무엇에 주의해야 하는가"를 감지한다.

리뷰 하네스(policy_harness.py)가 어떤 skill/지식 카드를 고를지 판단할 재료를 만든다.
핵심은 analyze_diff(): 바뀐 파일의 경로와 patch 내용을 규칙(SIGNAL_RULES)과 대조해
security, api_contract, test_impact 같은 신호를 뽑아낸다. 각 신호에는 "어느 파일의
어떤 단어에서 걸렸는지" 근거(evidence)도 함께 담는다.

명령줄에서 python -m 으로 직접 실행하면(main) JSON 요청 파일을 받아 신호를 출력한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.app.core.schemas import ReviewRequest

# 신호 감지 규칙표. 각 신호마다 "경로에서 찾을 단어(paths)"와 "patch 내용에서 찾을
# 단어(patch)"를 정해 둔다. require_patch가 True면 patch 쪽이 맞아야만 신호로 인정한다.
SIGNAL_RULES = {
    "api_contract": {
        "paths": ("/api/", "main.py", "schema", "router", "endpoint", "controller"),
        "patch": ("status_code", "response", "request", "webhook", "http", "json"),
    },
    "security": {
        "paths": ("auth", "security", "permission", "oauth", "jwt", "secret", "token"),
        "patch": ("authorization", "credential", "password", "private_key", "secret", "token"),
    },
    "test_impact": {
        "paths": ("test", "spec", "fixture", "routing", "publisher", "prompt", "workflow"),
        "patch": ("pytest", "assert", "mock", "exception", "fallback", "return"),
    },
    "performance": {
        "paths": ("performance", "cache", "query", "database", "storage", "rag"),
        "patch": (
            "for ",
            "while ",
            "select ",
            "join ",
            "sort(",
            "sorted(",
            "list(",
            "cache",
            "batch",
            "executor",
        ),
    },
    "reliability": {
        "paths": ("workflow", "deploy", "docker", "compose", "observability", "events", "llm"),
        "patch": ("timeout", "retry", "health", "logging", "exception", "api", "database"),
    },
    "input_boundary": {
        "paths": (
            "/api/",
            "controller",
            "handler",
            "parser",
            "upload",
            "proxy",
            "subprocess",
            "query",
        ),
        "patch": (
            "request.",
            "payload",
            "execute(",
            "shell=true",
            "subprocess",
            "eval(",
            "redirect",
            "requests.get",
            "httpx",
        ),
        "require_patch": True,
    },
    "data_integrity": {
        "paths": (
            "migration",
            "schema",
            "model",
            "repository",
            "database",
            "storage",
            "sql",
        ),
        "patch": (
            "transaction",
            "commit",
            "rollback",
            "alter table",
            "foreign key",
            "unique",
            "for update",
            "insert ",
            "update ",
            "delete ",
        ),
    },
    "dependency_workflow": {
        "paths": (
            ".github/workflows/",
            "dockerfile",
            "pyproject.toml",
            "requirements",
            "package.json",
            "package-lock.json",
            "action.yml",
            "action.yaml",
        ),
        "patch": (
            "uses:",
            "permissions:",
            "from ",
            "dependencies",
            "pip install",
            "npm install",
            "image:",
        ),
    },
    "frontend": {
        "paths": (
            ".html",
            ".css",
            ".tsx",
            ".jsx",
            ".vue",
            ".svelte",
            "/components/",
            "/pages/",
            "templates/",
            "frontend/",
        ),
        "patch": (
            "onclick",
            "onkeydown",
            "aria-",
            "<button",
            "<input",
            "tabindex",
            "focus(",
        ),
    },
    "documentation_contract": {
        "paths": ("readme", "docs/", ".env.example", "openapi", "changelog", "config", "cli"),
        "patch": (
            "environment",
            "endpoint",
            "deploy",
            "rollback",
            "webhook",
            "default",
            "status_code",
            "argument",
            "command",
        ),
    },
}


def reviewable_patch_text(patch: str) -> str:
    """diff 형식의 patch에서 "실제로 검토할 내용"만 남긴 순수 텍스트를 만든다.

    diff에는 메타 줄(@@, +++, ---)과 삭제 줄(-)이 섞여 있다. 삭제된 코드와 메타 정보는
    빼고, 추가(+)/유지( ) 줄에서 맨 앞의 +/공백 기호만 떼어 실제 코드처럼 되돌린다.
    """
    lines: list[str] = []
    for raw_line in patch.splitlines():
        # startswith에 튜플을 주면 "이 중 하나로 시작하면"이라는 뜻이다.
        if raw_line.startswith(("@@", "+++", "---", "\\ No newline")):
            continue
        if raw_line.startswith("-"):  # 삭제된 줄은 현재 코드가 아니므로 제외.
            continue
        if raw_line.startswith(("+", " ")):
            raw_line = raw_line[1:]  # 맨 앞의 +/공백 기호 한 글자를 떼어낸다.
        lines.append(raw_line)
    return "\n".join(lines)


def analyze_diff(request: ReviewRequest) -> dict[str, list[str]]:
    """PR 요청에서 신호들을 뽑아 {신호이름: [근거들]} 형태의 사전으로 돌려준다."""
    signals: dict[str, list[str]] = {}
    # 실패한 체크가 있으면 ci_failure 신호를 먼저 추가한다.
    # {...}는 집합 컴프리헨션: 중복 없이 실패 체크 종류만 모은 뒤 정렬한다.
    failed_checks = sorted({check.kind for check in request.checks if check.is_failed})
    if failed_checks:
        # 근거는 최대 5개까지만 남긴다(f"..."는 값을 문자열에 끼워 넣는 f-string).
        signals["ci_failure"] = [f"failed_check:{kind}" for kind in failed_checks[:5]]

    for changed_file in request.changed_files:
        path = changed_file.path.lower()
        patch = reviewable_patch_text(changed_file.patch).lower()
        for signal, rules in SIGNAL_RULES.items():
            # next((...), None): 조건에 맞는 첫 마커를 찾고, 없으면 None. 어떤 단어에
            # 걸렸는지 근거로 남기기 위해 단순 in 검사 대신 "걸린 마커"를 받아 둔다.
            path_match = next((marker for marker in rules["paths"] if marker in path), None)
            patch_match = next((marker for marker in rules["patch"] if marker in patch), None)
            # require_patch 규칙은 patch 쪽 증거가 없으면 경로만 맞아도 무시한다.
            if rules.get("require_patch") and not patch_match:
                continue
            if not path_match and not patch_match:
                continue
            # setdefault: 키가 없으면 빈 리스트로 만들고, 그 리스트를 돌려준다.
            evidence = signals.setdefault(signal, [])
            marker = path_match or patch_match  # 경로 우선, 없으면 patch 마커.
            item = f"{changed_file.path}:{marker}"
            # 중복은 빼고, 신호당 근거는 최대 5개까지만 모은다.
            if item not in evidence and len(evidence) < 5:
                evidence.append(item)
    return signals


def main() -> int:
    """명령줄 실행용 진입점. JSON 요청 파일 경로를 인자로 받아 신호를 출력한다.

    반환값(0/2)은 프로세스 종료 코드다: 0=성공, 2=사용법 오류.
    """
    # sys.argv는 명령줄 인자 목록. [0]은 스크립트 이름, [1]이 파일 경로여야 한다.
    if len(sys.argv) != 2:
        print("usage: python -m review_harness.scripts.diff_signals <review-request.json>")
        return 2
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    # ensure_ascii=False: 한글이 \uXXXX로 깨지지 않고 그대로 보이게 한다.
    print(json.dumps(analyze_diff(ReviewRequest.from_dict(payload)), ensure_ascii=False, indent=2))
    return 0


# 이 파일을 직접 실행할 때만 main()을 돌리고, 종료 코드를 그대로 프로세스에 넘긴다.
if __name__ == "__main__":
    raise SystemExit(main())

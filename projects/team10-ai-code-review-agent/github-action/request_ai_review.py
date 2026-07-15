"""다른 저장소의 GitHub Actions에서 우리 AI 리뷰 API를 호출하는 독립 스크립트.

이 파일은 우리 백엔드가 아니라, AI 리뷰를 도입한 "고객 저장소"의 워크플로 안에서
돈다. 그래서 표준 라이브러리(urllib 등)만 쓰고 외부 패키지에 의존하지 않는다.

하는 일:
1) GitHub Actions가 넘겨준 이벤트(JSON)에서 PR 정보를 읽는다.
2) 바뀐 파일 목록을 GitHub API로 가져오고, lint/test 결과 파일을 읽어 체크로 만든다.
3) 이것들을 하나의 payload로 묶어 우리 리뷰 API(POST /v1/reviews)에 보낸다.

환경변수로 설정을 받는다: GITHUB_TOKEN, GITHUB_REPOSITORY, GITHUB_EVENT_PATH,
AI_REVIEWER_API_URL, AI_REVIEWER_TOKEN 등.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def _env(name: str, default: str = "") -> str:
    """환경변수를 읽는 짧은 도우미. 없으면 default(기본 빈 문자열)를 돌려준다."""
    return os.getenv(name, default)


def _read_json(path: Path) -> Any:
    """JSON 파일을 읽어 파싱한다. 파일이 없으면 None(예외 대신)."""
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _github_request(path: str) -> Any:
    """현재 저장소(GITHUB_REPOSITORY) 기준으로 GitHub API를 GET 호출하고 JSON을 돌려준다."""
    token = _env("GITHUB_TOKEN")
    repository = _env("GITHUB_REPOSITORY")
    if not token or not repository:
        raise RuntimeError("GITHUB_TOKEN and GITHUB_REPOSITORY are required")
    url = f"https://api.github.com/repos/{repository}{path}"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    # with ... as : 응답을 다 읽으면 연결을 자동으로 닫는다. urlopen이 실제 HTTP 호출.
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _pull_files(pr_number: int) -> list[dict[str, Any]]:
    """PR에서 바뀐 파일 목록을 모두 가져와, 우리 API가 원하는 필드만 남겨 돌려준다.

    GitHub은 한 번에 최대 100개만 주므로 page를 늘려가며 반복 호출한다(페이지네이션).
    """
    files: list[dict[str, Any]] = []
    page = 1
    while True:  # 더 받을 게 없을 때까지 반복.
        # urlencode: dict를 "per_page=100&page=1" 같은 URL 쿼리 문자열로 만든다.
        query = urllib.parse.urlencode({"per_page": 100, "page": page})
        payload = _github_request(f"/pulls/{pr_number}/files?{query}")
        if not payload:
            break  # 빈 페이지면 끝.
        files.extend(payload)
        if len(payload) < 100:
            break  # 100개 미만이면 마지막 페이지.
        page += 1
    # 원본 항목에서 필요한 필드만 골라 새 dict 리스트로 변환(리스트 컴프리헨션).
    return [
        {
            "path": item.get("filename", ""),
            "status": item.get("status", "modified"),
            "additions": item.get("additions", 0),
            "deletions": item.get("deletions", 0),
            "patch": item.get("patch", ""),
        }
        for item in files
    ]


def _lint_check() -> dict[str, str]:
    """워크플로가 남긴 lint-result.json을 읽어 하나의 "체크 결과" dict로 만든다.

    파일이 없으면 skipped(건너뜀). ruff는 지적 목록을 JSON 배열로 내보내므로,
    항목이 하나라도 있으면 실패(failure)로 본다.
    """
    payload = _read_json(Path("lint-result.json"))
    if payload is None:
        return {"kind": "lint", "status": "skipped", "conclusion": "skipped", "summary": ""}
    failed_count = len(payload) if isinstance(payload, list) else 0
    conclusion = "success" if failed_count == 0 else "failure"
    return {
        "kind": "lint",
        "status": "completed",
        "conclusion": conclusion,
        "summary": f"ruff findings: {failed_count}",
    }


def _test_check() -> dict[str, str]:
    """test-result.json(테스트 실행 결과)을 읽어 "체크 결과" dict로 만든다.

    파일이 없으면 skipped. 테스트 러너의 종료코드(exitcode)가 0이면 성공, 아니면 실패.
    """
    payload = _read_json(Path("test-result.json"))
    if payload is None:
        return {"kind": "test", "status": "skipped", "conclusion": "skipped", "summary": ""}
    exitcode = int(payload.get("exitcode", 1)) if isinstance(payload, dict) else 1
    summary = payload.get("summary", {}) if isinstance(payload, dict) else {}
    conclusion = "success" if exitcode == 0 else "failure"
    return {
        "kind": "test",
        "status": "completed",
        "conclusion": conclusion,
        "summary": json.dumps(summary, ensure_ascii=False),
    }


def _post_review_request(payload: dict[str, Any]) -> Any:
    """모아 둔 payload를 우리 리뷰 API로 POST 전송하고 응답 JSON을 돌려준다."""
    api_url = _env("AI_REVIEWER_API_URL").rstrip("/")  # 끝의 / 제거해 주소 이중 슬래시 방지.
    token = _env("AI_REVIEWER_TOKEN")
    if not api_url:
        raise RuntimeError("AI_REVIEWER_API_URL is required")
    # data를 주고 method="POST"로 하면 GET이 아닌 POST 요청이 된다. 본문은 바이트여야 한다.
    request = urllib.request.Request(
        f"{api_url}/v1/reviews",
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    """이벤트에서 PR 정보를 읽어 리뷰 요청 payload를 만들고 API에 보낸 뒤 응답을 출력한다."""
    # GitHub Actions는 이벤트 상세를 JSON 파일로 저장하고 그 경로를 이 환경변수로 알려준다.
    event_path = Path(_env("GITHUB_EVENT_PATH"))
    event = _read_json(event_path)
    if not event or "pull_request" not in event:
        raise RuntimeError("This script must run from a pull_request event")

    repository_name = event["repository"]["name"]
    owner = event["repository"]["owner"]["login"]
    pr = event["pull_request"]
    payload = {
        "repository": {
            "provider": "github",
            "owner": owner,
            "name": repository_name,
            "default_branch": event["repository"].get("default_branch", "main"),
        },
        "pull_request": {
            "number": pr["number"],
            "title": pr.get("title", ""),
            "author": pr.get("user", {}).get("login", ""),
            "base_sha": pr.get("base", {}).get("sha", ""),
            "head_sha": pr.get("head", {}).get("sha", ""),
            "base_branch": pr.get("base", {}).get("ref", ""),
            "head_branch": pr.get("head", {}).get("ref", ""),
        },
        # lint/test 체크와 바뀐 파일을 각각 위 도우미로 채운다.
        "checks": [_lint_check(), _test_check()],
        "changed_files": _pull_files(pr["number"]),
        "github": {
            "run_id": _env("GITHUB_RUN_ID"),
            "event_name": _env("GITHUB_EVENT_NAME", "pull_request"),
        },
    }
    result = _post_review_request(payload)
    print(json.dumps(result, indent=2, ensure_ascii=False))


# 직접 실행할 때만 돈다. 오류가 나면 이유를 stderr로 남기고 예외를 다시 던져
# (raise) 워크플로가 실패로 인식하게 한다.
if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"AI review request failed: {exc}", file=sys.stderr)
        raise


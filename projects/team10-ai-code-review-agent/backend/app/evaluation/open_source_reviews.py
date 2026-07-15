"""공개 GitHub 저장소의 PR 리뷰/코멘트를 "평가용 데이터"로 수집·정규화하는 모듈.

우리 AI 리뷰 결과가 얼마나 좋은지 비교하려면, 실제 사람(특히 maintainer)이
공개 저장소에서 남긴 리뷰가 필요하다. 이 파일은 GitHub REST API를 직접 호출해
그 리뷰/인라인 코멘트를 긁어오고, 각 항목을 우리가 쓰기 편한 형태로 다듬는다.

핵심 구성:
- GitHubPublicDataClient : GitHub API를 호출하는 도우미(재시도/페이지네이션 포함).
- normalize_review / normalize_review_comment : API 원본을 평가용 dict로 정규화.
- collect_repository_reviews : 한 저장소의 PR들을 훑어 레코드 목록으로 모은다.
- summarize_records / write_jsonl : 수집 결과를 요약하고 JSONL 파일로 저장한다.

이 파일은 표준 라이브러리(urllib 등)만 쓰며, CLI는 scripts/collect_open_source_reviews.py다.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

# GitHub은 코멘트 작성자와 저장소의 관계를 author_association으로 알려준다.
# 이 세 값 중 하나면 "관리자(maintainer)"로 본다(소유자/조직원/공동작업자).
MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


class GitHubPublicDataClient:
    """GitHub REST API를 호출하는 얇은 클라이언트. 인증 토큰과 타임아웃을 들고 다닌다."""

    def __init__(self, token: str | None = None, timeout: int = 30) -> None:
        # 토큰을 직접 주지 않으면 환경변수 GITHUB_TOKEN을 쓴다(요청 한도를 늘려 줌).
        self.token = token or os.getenv("GITHUB_TOKEN")
        self.timeout = timeout

    def get_json(self, path: str) -> Any:
        """API 경로(또는 전체 URL)를 GET 요청하고 JSON을 파싱해 돌려준다.

        일시적 오류(429/5xx)는 최대 3번까지 재시도한다.
        """
        # path가 이미 전체 주소면 그대로, 아니면 API 기본 주소를 앞에 붙인다.
        url = path if path.startswith("http") else f"https://api.github.com{path}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "ai-code-review-agent-evaluation",
        }
        if self.token:
            # 토큰이 있으면 인증 헤더를 붙인다(비인증은 시간당 요청 한도가 매우 낮다).
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(url, headers=headers)
        # range(3) → 0,1,2 세 번 시도. urlopen은 실제 HTTP 요청을 보낸다.
        for attempt in range(3):
            try:
                # with ... as : 응답을 다 읽으면 연결을 자동으로 닫아 준다.
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                # 일시적 오류(429=한도초과, 5xx=서버오류)가 아니거나 마지막 시도면 그대로 실패.
                if exc.code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                # 2**attempt = 1초, 2초로 점점 더 기다렸다 재시도(지수 백오프).
                time.sleep(2**attempt)
        raise RuntimeError("GitHub request retry loop ended unexpectedly")

    def paginate(self, path: str, *, max_items: int | None = None) -> list[dict[str, Any]]:
        """목록 API를 여러 페이지에 걸쳐 모두 읽어 하나의 리스트로 합친다.

        GitHub은 한 번에 최대 100개만 주므로, page 번호를 늘려가며 반복 호출한다
        (이런 방식을 페이지네이션이라 한다). * 뒤의 max_items는 키워드로만 넘길 수 있다.
        """
        items: list[dict[str, Any]] = []
        # path에 이미 ?쿼리가 있으면 &로, 없으면 ?로 페이지 파라미터를 이어 붙인다.
        separator = "&" if "?" in path else "?"
        for page in range(1, 101):  # 최대 100페이지(=1만 건)까지만 안전하게 순회.
            payload = self.get_json(f"{path}{separator}per_page=100&page={page}")
            # 리스트가 아니거나 빈 페이지면 더 볼 게 없으므로 중단.
            if not isinstance(payload, list) or not payload:
                break
            # dict인 항목만 추려서 모은다.
            items.extend(item for item in payload if isinstance(item, dict))
            if max_items is not None and len(items) >= max_items:
                return items[:max_items]  # 원하는 개수를 넘으면 잘라서 반환.
            # 100개 미만이면 마지막 페이지라는 뜻이라 중단.
            if len(payload) < 100:
                break
        return items


# 이름 앞의 밑줄(_)은 "이 파일 안에서만 쓰는 내부 함수"라는 관례적 표시다.
def _user(payload: dict[str, Any]) -> str:
    """리뷰/코멘트 payload에서 작성자 로그인 이름을 안전하게 꺼낸다(없으면 빈 문자열)."""
    user = payload.get("user")
    return str(user.get("login") or "") if isinstance(user, dict) else ""


def _is_bot(login: str) -> bool:
    """봇 계정인지 이름 규칙으로 판별한다(예: dependabot[bot], some-bot)."""
    return login.endswith("[bot]") or login.endswith("-bot")


def _is_maintainer(payload: dict[str, Any]) -> bool:
    """작성자가 저장소 관리자인지(author_association 기준) 판별한다.

    평가에서는 "관리자가 남긴 리뷰"만 신뢰할 정답으로 취급하므로 이 구분이 중요하다.
    """
    return str(payload.get("author_association") or "").upper() in MAINTAINER_ASSOCIATIONS


def normalize_review(payload: dict[str, Any]) -> dict[str, Any]:
    """GitHub 리뷰 1건(원본 dict)을 평가용으로 필요한 필드만 추린 dict로 정규화한다."""
    reviewer = _user(payload)
    return {
        "id": payload.get("id"),
        "state": str(payload.get("state") or "").upper(),
        "commit_id": str(payload.get("commit_id") or ""),
        "submitted_at": payload.get("submitted_at"),
        "reviewer": reviewer,
        "author_association": payload.get("author_association"),
        "is_bot": _is_bot(reviewer),
        "is_maintainer": _is_maintainer(payload),
        "body": str(payload.get("body") or ""),
        "html_url": payload.get("html_url"),
    }


def normalize_review_comment(payload: dict[str, Any]) -> dict[str, Any]:
    """인라인 코드 코멘트 1건을 평가용 dict로 정규화한다(어느 파일/줄에 달렸는지 포함)."""
    author = _user(payload)
    return {
        "id": payload.get("id"),
        "review_id": payload.get("pull_request_review_id"),
        # parent_id: 다른 코멘트에 대한 "답글"이면 원본 코멘트 id가 들어간다.
        "parent_id": payload.get("in_reply_to_id"),
        "author": author,
        "author_association": payload.get("author_association"),
        "is_bot": _is_bot(author),
        "is_maintainer": _is_maintainer(payload),
        "path": str(payload.get("path") or ""),
        "line": payload.get("line") or payload.get("original_line"),
        "side": payload.get("side"),
        "commit_id": str(payload.get("commit_id") or ""),
        "original_commit_id": str(payload.get("original_commit_id") or ""),
        "diff_hunk": str(payload.get("diff_hunk") or ""),
        "body": str(payload.get("body") or ""),
        "created_at": payload.get("created_at"),
        "html_url": payload.get("html_url"),
    }


def collect_repository_reviews(
    repository: str,
    *,
    max_prs: int = 25,
    state: str = "closed",
    client: GitHubPublicDataClient | None = None,
) -> list[dict[str, Any]]:
    """한 저장소의 PR들을 훑어, PR별 메타데이터 + 리뷰/코멘트를 담은 레코드 목록을 만든다.

    repository: "owner/name" 형식. max_prs: 최근 몇 개 PR까지 볼지. state: 열림/닫힘/전체.
    각 PR마다 상세 정보, 리뷰 목록, 인라인 코멘트를 각각 API로 받아 하나로 합친다.
    """
    # partition("/")은 "owner/name"을 (owner, "/", name) 세 조각으로 나눈다.
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name:
        raise ValueError("repository must use owner/name format")
    if state not in {"open", "closed", "all"}:
        raise ValueError("state must be open, closed, or all")
    github = client or GitHubPublicDataClient()
    # urllib.parse.quote: owner/name에 특수문자가 있어도 URL에 안전하게 넣는다.
    pulls = github.paginate(
        f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/pulls"
        f"?state={state}&sort=updated&direction=desc",
        max_items=max_prs,
    )
    records: list[dict[str, Any]] = []
    for pull_summary in pulls:
        number = int(pull_summary.get("number") or 0)
        if number <= 0:
            continue  # 번호가 이상하면 건너뛴다.
        # PR 한 건마다 상세/리뷰/코멘트를 각각 따로 받아 온다.
        detail = github.get_json(f"/repos/{owner}/{name}/pulls/{number}")
        reviews = github.paginate(f"/repos/{owner}/{name}/pulls/{number}/reviews")
        comments = github.paginate(f"/repos/{owner}/{name}/pulls/{number}/comments")
        # 리스트의 각 원소를 정규화 함수로 변환한 새 리스트(리스트 컴프리헨션).
        normalized_reviews = [normalize_review(review) for review in reviews]
        normalized_comments = [normalize_review_comment(comment) for comment in comments]
        records.append(
            {
                "schema_version": 1,
                "repository": repository,
                "pull_number": number,
                "title": str(detail.get("title") or ""),
                "state": str(detail.get("state") or ""),
                "merged": bool(detail.get("merged")),
                "draft": bool(detail.get("draft")),
                "created_at": detail.get("created_at"),
                "closed_at": detail.get("closed_at"),
                "merged_at": detail.get("merged_at"),
                # (detail.get("base") or {}) : base가 없어도 빈 dict로 만들어 .get 오류를 막는다.
                "base_sha": str((detail.get("base") or {}).get("sha") or ""),
                "head_sha": str((detail.get("head") or {}).get("sha") or ""),
                "additions": int(detail.get("additions") or 0),
                "deletions": int(detail.get("deletions") or 0),
                "changed_files": int(detail.get("changed_files") or 0),
                "reviews": normalized_reviews,
                "review_comments": normalized_comments,
                # 관리자가 실제로 리뷰한 커밋들의 집합. 우리 리뷰를 어느 커밋 기준으로
                # 비교할지 후보로 쓴다. { ... } 는 집합 컴프리헨션이라 중복이 자동 제거되고,
                # sorted(...)로 정렬해 항상 같은 순서를 보장한다.
                "candidate_review_commits": sorted(
                    {
                        review["commit_id"]
                        for review in normalized_reviews
                        if review["is_maintainer"]
                        and review["commit_id"]
                        and review["state"] in {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}
                    }
                ),
            }
        )
    return records


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    """수집한 레코드 전체를 한눈에 볼 수 있는 통계 dict로 요약한다(수집 결과 검증용)."""
    # for가 두 번 나오는 컴프리헨션 = 중첩 반복. 모든 레코드의 모든 리뷰를 하나로 편다(flatten).
    reviews = [review for record in records for review in record.get("reviews", [])]
    comments = [
        comment for record in records for comment in record.get("review_comments", [])
    ]
    # 관리자가 남긴 "최상위" 코멘트(답글이 아닌 것). 원 지적 코멘트만 세기 위함.
    maintainer_roots = [
        comment
        for comment in comments
        if comment.get("is_maintainer") and not comment.get("parent_id")
    ]
    return {
        "pull_requests": len(records),
        # sum(bool(...) for ...) : True는 1로 세어져 "조건에 맞는 개수"를 구한다.
        "merged_pull_requests": sum(bool(record.get("merged")) for record in records),
        "reviews": len(reviews),
        # Counter는 값별 등장 횟수를 세는 도구. 리뷰 상태(APPROVED 등) 분포를 dict로 만든다.
        "review_states": dict(Counter(str(review.get("state")) for review in reviews)),
        "inline_comments": len(comments),
        "maintainer_root_comments": len(maintainer_roots),
        "bot_comments": sum(bool(comment.get("is_bot")) for comment in comments),
        # 사람이 단 "답글" 수(parent_id가 있고 봇이 아닌 것).
        "human_replies": sum(
            bool(comment.get("parent_id")) and not bool(comment.get("is_bot"))
            for comment in comments
        ),
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """레코드들을 JSONL 파일로 저장한다(한 줄에 JSON 하나씩).

    JSONL은 큰 데이터를 한 줄씩 읽기 좋은 형식이다. ensure_ascii=False로 한글이
    \\uXXXX 이스케이프 없이 그대로 저장된다.
    """
    # parents=True : 중간 폴더가 없으면 함께 만든다. exist_ok=True : 이미 있어도 에러 없음.
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )

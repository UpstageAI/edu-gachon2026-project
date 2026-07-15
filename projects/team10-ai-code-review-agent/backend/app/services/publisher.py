"""리뷰 결과 "발행(publish)" 단계: 완성된 리뷰를 사람이 볼 곳에 붙이는 마지막 단계.

파이프라인이 만든 ReviewResult를 받아 두 가지 방식 중 하나로 내보낸다.
- LocalPublisher   : 로컬 폴더에 마크다운(.md) 파일로 저장(개발/테스트용).
- GitHubPublisher  : 실제 GitHub PR에 발행. inline comment(diff 해당 줄에 다는
  코멘트) + 요약 댓글(issue comment) + check run(체크 결과) 완료 처리를 한다.

핵심 아이디어:
- 마커(marker): 우리가 단 댓글에 눈에 안 보이는 HTML 주석 표식을 심어 둔다. 다음
  리뷰 때 그 표식으로 "이전에 우리가 단 댓글"을 찾아 갱신/삭제한다(중복 방지).
- 표준 리뷰(policy_context_review)에는 "심층 리뷰 실행" 버튼을 함께 붙여, 사용자가
  원할 때 더 깊은 리뷰를 요청할 수 있게 한다.

format_review_markdown()이 댓글 본문(마크다운)을 만들고, 각 Publisher가 그걸
목적지에 쓴다. create_publisher()가 설정(Settings)을 보고 알맞은 Publisher를 고른다.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from pathlib import Path
from typing import Protocol

from backend.app.core.config import Settings
from backend.app.core.schemas import (
    ReviewFinding,
    ReviewKnowledgeCard,
    ReviewRequest,
    ReviewResult,
)
from backend.app.services.github_app import DEEP_REVIEW_ACTION_IDENTIFIER, GitHubAppClient

logger = logging.getLogger(__name__)


# Protocol = "덕 타이핑" 인터페이스. 상속하지 않아도 publish() 메서드만 있으면
# ReviewPublisher로 취급된다("이 메서드만 있으면 OK"라는 약속).
class ReviewPublisher(Protocol):
    def publish(self, request: ReviewRequest, result: ReviewResult) -> dict[str, object]:
        ...


# 아래 세 dict는 코드 내부의 영어 식별자를 사용자에게 보여 줄 한국어 라벨로 바꾸는 표다.
# 라우팅 경로 이름(routing.py에서 정한 name) → 사람이 읽을 리뷰 유형 이름.
REVIEW_TYPE_LABELS = {
    "simple_failure_review": "실패 원인 빠른 리뷰",
    "policy_context_review": "정책 기반 표준 리뷰",
    "deep_quality_review": "심층 품질 리뷰",
}

# 지적 사항의 category(영어) → 한국어 분류명.
CATEGORY_LABELS = {
    "functional_correctness": "기능 정확성",
    "security": "보안",
    "data_integrity": "데이터 무결성",
    "reliability": "신뢰성",
    "performance": "성능",
    "test": "테스트",
    "api_contract": "API 계약",
    "architecture": "아키텍처",
    "time_complexity": "시간 복잡도",
    "space_complexity": "공간 복잡도",
    "simplification": "코드 간소화",
    "maintainability": "유지보수성",
    "failure": "실패 원인",
    "style": "코드 품질",
}

# 경로 선택 이유(routing.py가 영어로 남긴 reasons) → 한국어 설명.
ROUTE_REASON_LABELS = {
    "syntax, lint, or test failed": "문법, 린트 또는 테스트 실패가 감지됨",
    "manual deep review requested": "사용자가 심층 리뷰를 직접 요청함",
    "checks passed or no failing check detected": "실패한 체크가 없음",
    "repository policy is available": "저장소 정책 컨텍스트 사용 가능",
    "repository policy is unavailable; falling back to general review": (
        "저장소 정책이 없어 일반 리뷰로 진행"
    ),
    "high-risk signals detected; deep review can be requested": (
        "고위험 변경 신호 감지, 필요 시 심층 리뷰 선택 가능"
    ),
    "large diff detected; deep review can be requested": (
        "큰 변경 규모 감지, 필요 시 심층 리뷰 선택 가능"
    ),
    "many changed files detected; deep review can be requested": (
        "많은 파일 변경 감지, 필요 시 심층 리뷰 선택 가능"
    ),
}

# 마커: 우리가 단 댓글에 심는 눈에 안 보이는 HTML 주석 표식. {scope}에는 리뷰 종류
# (deep/automatic)가 들어가, 심층 리뷰 댓글과 자동 리뷰 댓글을 서로 구분해 갱신한다.
SUMMARY_COMMENT_MARKER = "<!-- ai-code-review-agent:summary:{scope} -->"
INLINE_COMMENT_MARKER = "<!-- ai-code-review-agent:inline:{scope} -->"


def _review_type_label(result: ReviewResult) -> str:
    # 경로 이름을 한국어 라벨로 바꾼다. 표에 없으면 "자동 코드 리뷰"로 기본 처리.
    return REVIEW_TYPE_LABELS.get(result.route.name, "자동 코드 리뷰")


def _review_context_label(result: ReviewResult) -> str:
    # 이번 리뷰가 무엇을 근거로 삼았는지 한 줄로 설명한다(RAG 사용 여부에 따라).
    if result.route.use_rag:
        return "저장소 정책/RAG 참조"
    return "체크 결과와 변경 diff 기반"


def _route_reason_summary(result: ReviewResult) -> str:
    # 경로 선택 이유들을 한국어로 바꿔 ", "로 이어 붙인다(체크 결과 요약에 표시).
    if not result.route.reasons:
        return "자동 라우팅 기준"
    return ", ".join(ROUTE_REASON_LABELS.get(reason, reason) for reason in result.route.reasons)


def _supports_manual_deep_review(result: ReviewResult) -> bool:
    # 표준 리뷰일 때만 "심층 리뷰 실행" 버튼을 제공한다(실패/심층 경로엔 안 붙임).
    return result.route.name == "policy_context_review"


def _review_scope(result: ReviewResult) -> str:
    # 마커의 {scope} 값. 심층 리뷰면 "deep", 그 외에는 "automatic".
    return "deep" if result.route.name == "deep_quality_review" else "automatic"


# 지식 카드 하나를 "제목 (출처: [문서명](URL), ...)" 형태의 사람이 읽을 문자열로 만든다.
# card.sources는 policy_harness.py가 sources.json에서 미리 찾아 채워 둔 참고 문헌이다.
def _card_reference_markdown(card: ReviewKnowledgeCard) -> str:
    if not card.sources:
        return card.title
    # 출처마다 URL이 있으면 마크다운 링크로, 없으면 제목만 나열한다.
    source_labels = ", ".join(
        f"[{source.title}]({source.url})" if source.url else source.title
        for source in card.sources
    )
    return f"{card.title} (출처: {source_labels})"


def _cards_by_id(result: ReviewResult) -> dict[str, ReviewKnowledgeCard]:
    """이번 리뷰에서 선택된 지식 카드를 card_id로 바로 찾을 수 있는 사전으로 바꾼다.

    ReviewFinding은 knowledge_card_id(문자열)만 들고 있어, 제목/출처를 보여 주려면
    review_harness.knowledge_cards에서 같은 id의 카드를 찾아야 한다.
    """
    if result.review_harness is None:
        return {}
    return {card.card_id: card for card in result.review_harness.knowledge_cards}


# 지적 사항 하나(ReviewFinding)를 마크다운 텍스트로 만든다.
# cards_by_id가 있으면 knowledge_card_id를 카드 제목·출처로 풀어서 보여 주고, 없으면
# (예: 오래된 저장 결과, 카드가 사라진 경우) id만 그대로 보여 준다.
# 인자의 * 뒤에 있는 include_location은 "키워드로만" 넘길 수 있는 옵션이다
# (예: _finding_markdown(f, cards, include_location=False)). inline 코멘트는 이미 해당
# 줄에 붙으므로 위치 표기를 뺀다.
def _finding_markdown(
    finding: ReviewFinding,
    cards_by_id: dict[str, ReviewKnowledgeCard] | None = None,
    *,
    include_location: bool = True,
) -> str:
    heading = f"**{CATEGORY_LABELS.get(finding.category, finding.category)}**"
    if include_location:
        location = finding.file_path
        if finding.line_start:
            location = f"{location}:{finding.line_start}"
        heading = f"{heading} - `{location}`"
    lines = [heading, "", finding.message, "", f"**개선 제안:** {finding.suggestion}"]
    # evidence(근거) dict에서 발생 조건/영향을 꺼낸다. .get(...)은 키가 없으면 None을
    # 주고, `or ""`로 None을 빈 문자열로 바꾼 뒤 앞뒤 공백을 정리한다.
    trigger = str(finding.evidence.get("trigger") or "").strip()
    consequence = str(finding.evidence.get("consequence") or "").strip()
    if trigger:
        lines.extend(["", f"**발생 조건:** {trigger}"])
    if consequence:
        lines.extend(["", f"**영향:** {consequence}"])
    if finding.policy_source:
        lines.extend(["", f"**참고 정책:** `{finding.policy_source}`"])
    if finding.knowledge_card_id:
        card = (cards_by_id or {}).get(finding.knowledge_card_id)
        if card:
            lines.extend(
                [
                    "",
                    f"**검토 기준:** {_card_reference_markdown(card)} "
                    f"(`{finding.knowledge_card_id}`)",
                ]
            )
        else:
            lines.extend(["", f"**검토 기준:** `{finding.knowledge_card_id}`"])
    return "\n".join(lines)


# 마크다운 표의 한 칸에 넣을 문자열을 안전하게 다듬는다. 줄바꿈은 공백으로 합치고,
# 표 구분자인 |는 \|로 이스케이프해 표가 깨지지 않게 한다.
def _table_cell(value: str) -> str:
    return " ".join(value.splitlines()).replace("|", "\\|").strip()


def _evidence_lines(result: ReviewResult) -> list[str]:
    """"이 리뷰가 무엇을 근거로 삼았는지" 한눈에 보여 주는 절을 만든다.

    개별 지적(finding)에도 근거가 표시되지만, 이 절은 리뷰 전체가 어떤 검토 절차·
    저장소 정책·외부 지식 카드를 훑어봤는지 한 곳에 모아 보여 준다. "왜 이런 리뷰가
    나왔는지" 설명할 때 그대로 근거로 제시할 수 있게 하기 위한 절이다. 아무것도
    선택된 게 없으면(예: 정책/신호가 전혀 없는 아주 단순한 변경) 절 자체를 생략한다.
    """
    harness = result.review_harness
    skills = harness.skills if harness else []
    knowledge_cards = harness.knowledge_cards if harness else []
    # dict를 "순서를 기억하는 집합"처럼 써서 (source_path, section_title) 중복을 없앤다.
    # 여러 배치가 같은 정책 조각을 다시 검색해 올 수 있어 중복 제거가 필요하다.
    seen_policies: dict[tuple[str, str], None] = {}
    for policy in result.retrieved_policies:
        seen_policies.setdefault((policy.source_path, policy.section_title), None)

    if not skills and not knowledge_cards and not seen_policies:
        return []

    lines = ["", "### 리뷰 근거", ""]
    if skills:
        skill_titles = ", ".join(skill.title for skill in skills)
        lines.append(f"- **적용된 검토 절차**: {skill_titles}")
    if seen_policies:
        policy_labels = ", ".join(
            f"`{source_path}#{section_title}`" if section_title else f"`{source_path}`"
            for source_path, section_title in seen_policies
        )
        lines.append(f"- **참조한 저장소 정책 문서**: {policy_labels}")
    if knowledge_cards:
        card_labels = ", ".join(_card_reference_markdown(card) for card in knowledge_cards)
        lines.append(f"- **참고한 외부 지식 카드**: {card_labels}")
    return lines


def format_review_markdown(
    result: ReviewResult,
    findings: list[ReviewFinding] | None = None,
    inline_findings_count: int = 0,
) -> str:
    """리뷰 결과 전체를 PR 댓글용 마크다운 문자열로 조립한다.

    변경 요약 → 파일별 요약 표 → 지적 사항 목록 순서로 쌓는다. findings를 따로 주면
    그걸 쓰고(예: inline으로 이미 단 것 제외), 안 주면 result.findings를 그대로 쓴다.
    inline_findings_count가 있으면 "그중 몇 건은 inline으로도 달았다"는 안내를 붙인다.
    """
    # findings 인자를 안 주면(None) 결과에 담긴 전체 지적을 그대로 렌더링한다.
    rendered_findings = result.findings if findings is None else findings
    lines = [
        "## AI Code Review",
        "",
        "### 변경 요약",
        "",
        result.summary.change_summary or result.summary.short_comment,
        "",
        "### 파일별 변경 요약",
        "",
        "| 파일 | 변경 내용 |",
        "| --- | --- |",
    ]
    if result.summary.file_summaries:
        # 파일별 요약을 표의 각 행으로 만든다(제너레이터 표현식을 extend에 바로 넘김).
        lines.extend(
            f"| `{_table_cell(item.file_path)}` | {_table_cell(item.change_summary)} |"
            for item in result.summary.file_summaries
        )
    else:
        lines.append("| - | 변경 파일 요약이 없습니다. |")
    # 리뷰가 무엇을 근거로 삼았는지(검토 절차/정책 문서/지식 카드) 먼저 보여 준다.
    lines.extend(_evidence_lines(result))
    lines.extend(["", "### 리뷰"])
    if rendered_findings:
        lines.extend(["", f"검증된 리뷰 {len(rendered_findings)}건입니다."])
    else:
        lines.extend(["", "추가로 지적할 문제가 없습니다."])
    cards_by_id = _cards_by_id(result)
    # enumerate(..., start=1): 지적 사항에 1부터 번호를 매겨 목록으로 나열한다.
    for index, finding in enumerate(rendered_findings, start=1):
        lines.extend(
            [
                "",
                f"{index}. {_finding_markdown(finding, cards_by_id)}",
            ]
        )
    if inline_findings_count:
        lines.extend(
            [
                "",
                f"> 이 중 {inline_findings_count}건은 diff의 해당 줄에도 inline comment로 표시했습니다.",
            ]
        )
    # 표준 리뷰일 때만 심층 리뷰를 추가로 요청하는 방법을 안내한다.
    if _supports_manual_deep_review(result):
        lines.extend(
            [
                "",
                "#### 추가 검토",
                "",
                "> 다른 시각의 심층 리뷰가 필요하면 GitHub Checks 화면의 "
                "`심층 리뷰 실행` 버튼으로 추가 실행할 수 있습니다.",
            ]
        )
    return "\n".join(lines).strip() + "\n"


class LocalPublisher:
    """GitHub에 붙이는 대신 로컬 폴더에 마크다운 파일로 저장하는 발행기(개발/테스트용)."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def publish(self, request: ReviewRequest, result: ReviewResult) -> dict[str, object]:
        # mkdir(parents=True, exist_ok=True): 상위 폴더까지 만들고, 이미 있어도 에러 안 냄.
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"{result.review_run_id}.md"
        path.write_text(format_review_markdown(result), encoding="utf-8")
        return {"mode": "local", "path": str(path)}


class GitHubPublisher:
    """실제 GitHub PR에 리뷰를 발행하는 발행기.

    인증 방법은 두 가지다.
    - token       : 개인 액세스 토큰 등 이미 발급된 토큰을 직접 쓴다.
    - app_client  : GitHub App으로 동작. PR마다 installation token을 새로 발급받는다.
    app_client가 있을 때만 이전 댓글 조회/갱신/삭제 같은 고급 동작을 할 수 있다.
    """

    def __init__(
        self,
        token: str | None = None,
        app_client: GitHubAppClient | None = None,
    ) -> None:
        self.token = token
        self.app_client = app_client

    def publish(self, request: ReviewRequest, result: ReviewResult) -> dict[str, object]:
        """리뷰를 PR에 발행하는 전체 흐름: inline 코멘트 → 요약 댓글 → check run 마무리."""
        token = self._token_for(request)
        # line_start가 있는(특정 줄을 가리키는) 지적만 inline 코멘트 대상으로 고른다.
        inline_findings = [finding for finding in result.findings if finding.line_start is not None]
        cards_by_id = _cards_by_id(result)
        scope = _review_scope(result)
        inline_marker = INLINE_COMMENT_MARKER.format(scope=scope)
        # 새로 달기 전에, 같은 마커가 붙은 지난번 inline 코멘트를 먼저 지운다(중복 방지).
        self._delete_previous_inline_comments(request, token, inline_marker)
        inline_review: dict[str, object] = {}
        if inline_findings:
            try:
                inline_review = self._post_pull_review(
                    request,
                    token,
                    inline_findings,
                    cards_by_id=cards_by_id,
                    marker=inline_marker,
                )
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
                # inline 발행이 실패하면(권한/네트워크 등) 요약 댓글만으로 진행한다.
                logger.exception(
                    "inline review publish failed; falling back to issue comment",
                    extra={
                        "repository": request.repository.full_name,
                        "pull_request_number": request.pull_request.number,
                    },
                )
                inline_findings = []
        summary_marker = SUMMARY_COMMENT_MARKER.format(scope=scope)
        markdown = format_review_markdown(
            result,
            findings=result.findings,
            inline_findings_count=len(inline_findings),
        )
        # 마커를 본문 끝에 붙여 저장한다. 다음 리뷰 때 이 마커로 댓글을 찾아 갱신한다.
        body = self._upsert_issue_comment(
            request,
            token,
            f"{markdown}\n{summary_marker}\n",
            summary_marker,
        )
        check_run = self._complete_check_run(request, result, token)
        # 반환용 mode 표기: 토큰 없이 App으로 동작하면 "github_app", 아니면 "github".
        mode = "github_app" if self.app_client and not self.token else "github"
        return {
            "mode": mode,
            "comment_id": body.get("id"),
            "html_url": body.get("html_url"),
            "pull_request_review_id": inline_review.get("id"),
            "inline_findings_count": len(inline_findings),
            "check_run_id": check_run.get("id") if check_run else None,
            "check_run_url": check_run.get("html_url") if check_run else None,
        }

    def _post_pull_review(
        self,
        request: ReviewRequest,
        token: str,
        findings: list[ReviewFinding],
        cards_by_id: dict[str, ReviewKnowledgeCard] | None = None,
        marker: str = "",
    ) -> dict[str, object]:
        """지적 사항들을 PR review로 묶어 diff의 해당 줄에 inline 코멘트로 단다."""
        url = (
            "https://api.github.com/repos/"
            f"{request.repository.owner}/{request.repository.name}/pulls/"
            f"{request.pull_request.number}/reviews"
        )
        # 각 finding을 GitHub review API가 요구하는 코멘트 형태로 변환한다.
        # side="RIGHT"는 diff의 "변경 후(오른쪽)" 줄에 달겠다는 뜻이다.
        comments = [
            {
                "path": finding.file_path,
                "line": finding.line_start,
                "side": "RIGHT",
                "body": "\n\n".join(
                    part
                    for part in (
                        _finding_markdown(finding, cards_by_id, include_location=False),
                        marker,
                    )
                    if part
                ),
            }
            for finding in findings
        ]
        # json.dumps로 파이썬 dict를 JSON 문자열로 바꾸고, .encode로 바이트로 만든다
        # (HTTP 요청 본문은 바이트여야 한다).
        payload = json.dumps(
            {
                "commit_id": request.pull_request.head_sha,
                "event": "COMMENT",
                "body": "AI Code Review의 검증된 inline finding입니다.",
                "comments": comments,
            }
        ).encode("utf-8")
        # 외부 라이브러리 없이 표준 라이브러리 urllib.request로 HTTP POST를 보낸다.
        http_request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        # with ... as: 응답을 다 읽으면 연결을 자동으로 닫아 주는 컨텍스트 매니저.
        with urllib.request.urlopen(http_request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
        return json.loads(response_body) if response_body else {}

    def _delete_previous_inline_comments(
        self,
        request: ReviewRequest,
        token: str,
        marker: str,
    ) -> None:
        """지난번에 우리가 단 inline 코멘트를 마커로 찾아 삭제한다(App 모드에서만)."""
        if not self.app_client:
            return
        path = (
            f"/repos/{request.repository.owner}/{request.repository.name}/pulls/"
            f"{request.pull_request.number}/comments"
        )
        try:
            comments = self.app_client.paginated_get(path, token=token)
            for comment in comments:
                # 우리 마커가 없는 댓글은 건너뛴다(남이 단 것/다른 종류).
                if marker not in str(comment.get("body") or ""):
                    continue
                # 우리 App이 단 것이 맞는지 한 번 더 확인한다(오삭제 방지).
                if not self._is_own_app_comment(comment):
                    continue
                comment_id = comment.get("id")
                if comment_id:
                    self.app_client.request_json(
                        "DELETE",
                        f"/repos/{request.repository.owner}/{request.repository.name}/pulls/comments/"
                        f"{comment_id}",
                        token=token,
                    )
        except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
            logger.exception(
                "previous inline review cleanup failed",
                extra={
                    "repository": request.repository.full_name,
                    "pull_request_number": request.pull_request.number,
                },
            )

    def _upsert_issue_comment(
        self,
        request: ReviewRequest,
        token: str,
        markdown: str,
        marker: str,
    ) -> dict[str, object]:
        """요약 댓글을 "갱신(upsert)"한다: 기존 댓글이 있으면 수정(PATCH), 없으면 새로 생성.

        upsert = update + insert. 마커로 우리가 단 이전 요약 댓글을 찾아 내용만 바꿔,
        PR에 같은 요약 댓글이 계속 쌓이지 않게 한다.
        """
        if self.app_client:
            path = (
                f"/repos/{request.repository.owner}/{request.repository.name}/issues/"
                f"{request.pull_request.number}/comments"
            )
            try:
                comments = self.app_client.paginated_get(path, token=token)
                # reversed: 최신 댓글부터 훑어 가장 최근의 우리 요약 댓글을 갱신한다.
                for comment in reversed(comments):
                    if marker not in str(comment.get("body") or ""):
                        continue
                    if not self._is_own_app_comment(comment):
                        continue
                    comment_id = comment.get("id")
                    if comment_id:
                        # PATCH: 기존 댓글 본문을 새 내용으로 교체한다.
                        return self.app_client.request_json(
                            "PATCH",
                            f"/repos/{request.repository.owner}/{request.repository.name}/issues/comments/"
                            f"{comment_id}",
                            token=token,
                            data={"body": markdown},
                        )
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError):
                logger.exception(
                    "review summary lookup failed; posting a new comment",
                    extra={
                        "repository": request.repository.full_name,
                        "pull_request_number": request.pull_request.number,
                    },
                )
        # App이 아니거나 기존 댓글을 못 찾았으면 새 댓글을 만든다.
        return self._post_issue_comment(request, token, markdown)

    def _is_own_app_comment(self, comment: dict[str, object]) -> bool:
        """이 댓글이 우리 GitHub App이 남긴 것인지 확인한다(다른 봇/사람의 댓글 보호)."""
        if not self.app_client:
            return False
        # getattr(obj, "이름", 기본값): 속성이 없어도 에러 대신 기본값을 준다.
        settings = getattr(self.app_client, "settings", None)
        configured_app_id = str(getattr(settings, "github_app_id", "") or "")
        performed_by = comment.get("performed_via_github_app")
        if not configured_app_id or not isinstance(performed_by, dict):
            return False
        # 댓글을 남긴 App의 id가 우리 App id와 같아야 "우리 것"으로 인정한다.
        return str(performed_by.get("id") or "") == configured_app_id

    def _post_issue_comment(
        self,
        request: ReviewRequest,
        token: str,
        markdown: str,
    ) -> dict[str, object]:
        """PR에 요약 댓글(issue comment)을 새로 하나 생성한다."""
        url = (
            "https://api.github.com/repos/"
            f"{request.repository.owner}/{request.repository.name}/issues/"
            f"{request.pull_request.number}/comments"
        )
        payload = json.dumps({"body": markdown}).encode("utf-8")
        http_request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(http_request, timeout=20) as response:
            response_body = response.read().decode("utf-8")
        return json.loads(response_body) if response_body else {}

    def _complete_check_run(
        self,
        request: ReviewRequest,
        result: ReviewResult,
        token: str,
    ) -> dict[str, object]:
        """GitHub Checks 화면의 체크 항목을 "완료(success)"로 갱신한다.

        check_run_id가 있어야(우리가 만든 체크가 있어야) 동작한다. 표준 리뷰일 때는
        "심층 리뷰 실행" 버튼(actions)을 함께 붙여 사용자가 눌러 재실행할 수 있게 한다.
        """
        if not self.app_client or not request.github.check_run_id:
            return {}
        summary = (
            f"{result.summary.short_comment}\n\n"
            f"- 리뷰 유형: {_review_type_label(result)}\n"
            f"- 선택 사유: {_route_reason_summary(result)}\n"
            f"- 리뷰 결과: {len(result.findings)}"
        )
        payload: dict[str, object] = {
            "status": "completed",
            "conclusion": "success",
            "completed_at": _utc_now_iso(),
            "output": {
                "title": "AI Code Review 완료",
                "summary": summary,
            },
        }
        # 버튼을 누르면 GitHub이 이 identifier로 webhook을 보내고, 그때 심층 리뷰가 돈다.
        if _supports_manual_deep_review(result):
            payload["actions"] = [
                {
                    "label": "심층 리뷰 실행",
                    "description": "다른 시각의 심층 리뷰를 실행합니다.",
                    "identifier": DEEP_REVIEW_ACTION_IDENTIFIER,
                }
            ]
        return self.app_client.update_check_run(
            request.repository.owner,
            request.repository.name,
            request.github.check_run_id,
            token,
            payload,
        )

    def _token_for(self, request: ReviewRequest) -> str:
        """이번 발행에 쓸 인증 토큰을 고른다: 직접 준 토큰 우선, 없으면 App으로 발급."""
        if self.token:
            return self.token
        if not self.app_client:
            raise RuntimeError("GitHub publisher requires GITHUB_TOKEN or GitHub App settings")
        if not request.github.installation_id:
            raise RuntimeError("GitHub App publish requires github.installation_id")
        return self.app_client.installation_token(request.github.installation_id)


def create_publisher(settings: Settings) -> ReviewPublisher:
    """설정(publish_mode)을 보고 알맞은 Publisher를 만들어 주는 팩토리 함수.

    github_app → App 방식, github(+토큰) → 토큰 방식, 그 외에는 로컬 파일 저장.
    """
    if settings.publish_mode == "github_app":
        return GitHubPublisher(app_client=GitHubAppClient(settings))
    if settings.publish_mode == "github" and settings.github_token:
        return GitHubPublisher(settings.github_token)
    return LocalPublisher(settings.comment_output_dir)


def _utc_now_iso() -> str:
    # GitHub이 요구하는 UTC 시각 문자열(ISO 8601, 끝을 Z로 표기)을 만든다.
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")

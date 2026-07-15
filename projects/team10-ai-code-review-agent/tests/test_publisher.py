import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core.schemas import (
    FileChangeSummary,
    GitHubPayload,
    ModelCallUsage,
    PolicyChunk,
    PullRequestFeatures,
    PullRequestPayload,
    RepositoryPayload,
    ReviewHarnessContext,
    ReviewKnowledgeCard,
    ReviewRequest,
    ReviewResult,
    ReviewRoute,
    ReviewSkill,
    ReviewSourceReference,
    ReviewSummary,
    ReviewFinding,
)
from backend.app.services.publisher import GitHubPublisher, format_review_markdown


class FakeGitHubAppClient:
    def __init__(self):
        self.settings = SimpleNamespace(github_app_id="4252630")
        self.payload = None
        self.comments = []
        self.requests = []

    def update_check_run(self, owner, repo, check_run_id, token, payload):
        self.payload = payload
        return {"id": check_run_id, "html_url": "https://github.com/team/repo/runs/1"}

    def paginated_get(self, path, token):
        self.requests.append(("GET", path, token, None))
        return self.comments

    def request_json(self, method, path, token, data=None):
        self.requests.append((method, path, token, data))
        return {"id": 88, "html_url": "https://github.com/team/repo/pull/7#comment-88"}


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return b'{"id": 77}'


def _review_result(route_name="policy_context_review"):
    route = ReviewRoute(
        name=route_name,
        model_tier="solar3-medium" if route_name == "policy_context_review" else "solar3-high",
        use_rag=True,
        focus=["repo_policy"],
        reasons=["checks passed or no failing check detected", "repository policy is available"],
        confidence=0.9,
    )
    return ReviewResult(
        review_run_id="run-1",
        status="completed",
        idempotency_key="key",
        summary=ReviewSummary(
            route_name=route.name,
            model_tier=route.model_tier,
            overall_risk="medium",
            short_comment="리뷰가 완료되었습니다.",
            change_summary="API 응답 계약과 검증 테스트를 변경했습니다.",
            file_summaries=[
                FileChangeSummary(
                    file_path="app/api.py",
                    change_summary="응답에 상태 필드를 추가했습니다.",
                )
            ],
        ),
        findings=[],
        route=route,
        features=PullRequestFeatures(
            syntax_status="unknown",
            lint_status="unknown",
            test_status="passed",
            changed_files_count=1,
            changed_lines=1,
            risk_files=[],
            policy_available=True,
            router_confidence=0.9,
        ),
        model_call=ModelCallUsage(
            provider="upstage",
            model="solar-pro3",
            reasoning_effort="medium",
        ),
    )


class PublisherTest(unittest.TestCase):
    def test_review_markdown_uses_change_summary_file_table_and_review_sections(self):
        markdown = format_review_markdown(_review_result())

        headings = ["### 변경 요약", "### 파일별 변경 요약", "### 리뷰"]
        self.assertEqual([heading for heading in headings if heading in markdown], headings)
        self.assertLess(markdown.index(headings[0]), markdown.index(headings[1]))
        self.assertLess(markdown.index(headings[1]), markdown.index(headings[2]))
        self.assertIn("| `app/api.py` | 응답에 상태 필드를 추가했습니다. |", markdown)
        self.assertIn("GitHub Checks 화면", markdown)
        self.assertNotIn("Review tier", markdown)
        self.assertNotIn("Reasoning effort", markdown)
        self.assertNotIn("solar3-medium", markdown)
        self.assertNotIn("위험도", markdown)
        self.assertNotIn("중요도", markdown)

    def test_standard_review_check_run_includes_deep_review_action(self):
        app_client = FakeGitHubAppClient()
        publisher = GitHubPublisher(app_client=app_client)
        request = ReviewRequest(
            repository=RepositoryPayload(provider="github", owner="team", name="repo"),
            pull_request=PullRequestPayload(
                number=7,
                title="Test",
                author="dev",
                base_sha="base",
                head_sha="head",
                base_branch="main",
                head_branch="feature",
            ),
            github=GitHubPayload(installation_id="123", check_run_id="456"),
        )

        publisher._complete_check_run(request, _review_result(), "token")

        self.assertEqual(app_client.payload["status"], "completed")
        self.assertEqual(app_client.payload["conclusion"], "success")
        self.assertEqual(app_client.payload["output"]["title"], "AI Code Review 완료")
        self.assertEqual(app_client.payload["actions"][0]["label"], "심층 리뷰 실행")
        self.assertEqual(app_client.payload["actions"][0]["identifier"], "run_deep_review")

    def test_summary_keeps_inline_findings_in_review_section(self):
        result = _review_result()
        inline_finding = ReviewFinding(
            severity="high",
            category="functional_correctness",
            file_path="app/service.py",
            line_start=10,
            line_end=10,
            message="빈 입력에서 예외가 발생합니다.",
            suggestion="인덱싱 전에 빈 결과를 반환합니다.",
        )
        result = ReviewResult(
            **{
                **result.__dict__,
                "findings": [inline_finding],
            }
        )

        markdown = format_review_markdown(result, findings=[inline_finding], inline_findings_count=1)

        self.assertIn("검증된 리뷰 1건", markdown)
        self.assertIn("빈 입력에서 예외가 발생", markdown)
        self.assertIn("1건은 diff의 해당 줄에도 inline comment", markdown)

    def test_review_heading_uses_category_without_abstract_severity(self):
        result = _review_result()
        finding = ReviewFinding(
            severity="high",
            category="functional_correctness",
            file_path="app/service.py",
            line_start=None,
            line_end=None,
            message="빈 입력에서 예외가 발생합니다.",
            suggestion="인덱싱 전에 빈 결과를 반환합니다.",
            knowledge_card_id="behavior-edge-and-failure-path",
        )
        result = ReviewResult(**{**result.__dict__, "findings": [finding]})

        markdown = format_review_markdown(result)

        self.assertIn("**기능 정확성** - `app/service.py`", markdown)
        self.assertIn("**검토 기준:** `behavior-edge-and-failure-path`", markdown)
        self.assertNotIn("high /", markdown)

    def test_evidence_section_lists_applied_skills_policies_and_knowledge_cards(self):
        card = ReviewKnowledgeCard(
            card_id="secret-and-sensitive-log-flow",
            title="Secret 로그 유출",
            skill_id="security-boundary",
            check="check",
            evidence_required="evidence",
            false_positive_guard="guard",
            severity_cap="medium",
            sources=[
                ReviewSourceReference(
                    source_id="owasp-logging",
                    title="Logging Cheat Sheet",
                    url="https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html",
                    authority="OWASP",
                )
            ],
        )
        skill = ReviewSkill(
            skill_id="security-boundary",
            title="보안 경계",
            instructions="instructions",
        )
        harness = ReviewHarnessContext(version="1.0", skills=[skill], knowledge_cards=[card])
        policy = PolicyChunk(
            source_path="policies/security-and-privacy.md",
            section_title="Secret 마스킹",
            content="content",
        )
        result = _review_result()
        result = ReviewResult(
            **{
                **result.__dict__,
                "review_harness": harness,
                "retrieved_policies": [policy],
            }
        )

        markdown = format_review_markdown(result)

        self.assertIn("### 리뷰 근거", markdown)
        self.assertIn("**적용된 검토 절차**: 보안 경계", markdown)
        self.assertIn("`policies/security-and-privacy.md#Secret 마스킹`", markdown)
        self.assertIn(
            "Secret 로그 유출 (출처: [Logging Cheat Sheet]"
            "(https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html))",
            markdown,
        )

    def test_finding_resolves_knowledge_card_title_and_source_link(self):
        card = ReviewKnowledgeCard(
            card_id="secret-and-sensitive-log-flow",
            title="Secret 로그 유출",
            skill_id="security-boundary",
            check="check",
            evidence_required="evidence",
            false_positive_guard="guard",
            severity_cap="medium",
            sources=[
                ReviewSourceReference(
                    source_id="owasp-logging",
                    title="Logging Cheat Sheet",
                    url="https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html",
                    authority="OWASP",
                )
            ],
        )
        harness = ReviewHarnessContext(version="1.0", knowledge_cards=[card])
        finding = ReviewFinding(
            severity="high",
            category="security",
            file_path="app/service.py",
            line_start=None,
            line_end=None,
            message="토큰이 그대로 로그에 남습니다.",
            suggestion="로그 남기기 전에 토큰을 마스킹합니다.",
            knowledge_card_id="secret-and-sensitive-log-flow",
        )
        result = _review_result()
        result = ReviewResult(
            **{**result.__dict__, "review_harness": harness, "findings": [finding]}
        )

        markdown = format_review_markdown(result, findings=[finding])

        self.assertIn(
            "**검토 기준:** Secret 로그 유출 (출처: [Logging Cheat Sheet]"
            "(https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)) "
            "(`secret-and-sensitive-log-flow`)",
            markdown,
        )

    def test_posts_validated_findings_as_pull_request_review_comments(self):
        publisher = GitHubPublisher(token="token")
        request = ReviewRequest(
            repository=RepositoryPayload(provider="github", owner="team", name="repo"),
            pull_request=PullRequestPayload(
                number=7,
                title="Test",
                author="dev",
                base_sha="base",
                head_sha="head",
                base_branch="main",
                head_branch="feature",
            ),
        )
        finding = ReviewFinding(
            severity="high",
            category="functional_correctness",
            file_path="app/service.py",
            line_start=10,
            line_end=10,
            message="Empty input raises an exception.",
            suggestion="Return an empty result before indexing.",
        )

        with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            response = publisher._post_pull_review(request, "token", [finding])

        http_request = urlopen.call_args.args[0]
        payload = json.loads(http_request.data)
        self.assertEqual(response["id"], 77)
        self.assertEqual(payload["commit_id"], "head")
        self.assertEqual(payload["comments"][0]["path"], "app/service.py")
        self.assertEqual(payload["comments"][0]["line"], 10)
        self.assertEqual(payload["comments"][0]["side"], "RIGHT")

    def test_updates_existing_summary_comment_for_same_review_scope(self):
        app_client = FakeGitHubAppClient()
        marker = "<!-- ai-code-review-agent:summary:automatic -->"
        app_client.comments = [
            {
                "id": 88,
                "body": f"old review\n{marker}",
                "performed_via_github_app": {"id": 4252630},
            }
        ]
        publisher = GitHubPublisher(app_client=app_client)
        request = ReviewRequest(
            repository=RepositoryPayload(provider="github", owner="team", name="repo"),
            pull_request=PullRequestPayload(
                number=7,
                title="Test",
                author="dev",
                base_sha="base",
                head_sha="head",
                base_branch="main",
                head_branch="feature",
            ),
        )

        response = publisher._upsert_issue_comment(
            request,
            "token",
            f"new review\n{marker}",
            marker,
        )

        self.assertEqual(response["id"], 88)
        self.assertIn(
            (
                "PATCH",
                "/repos/team/repo/issues/comments/88",
                "token",
                {"body": f"new review\n{marker}"},
            ),
            app_client.requests,
        )

    def test_removes_previous_inline_comments_for_same_review_scope(self):
        app_client = FakeGitHubAppClient()
        marker = "<!-- ai-code-review-agent:inline:automatic -->"
        app_client.comments = [
            {
                "id": 99,
                "body": f"old finding\n{marker}",
                "performed_via_github_app": {"id": 4252630},
            },
            {
                "id": 100,
                "body": "another app finding",
                "performed_via_github_app": {"id": 999},
            },
        ]
        publisher = GitHubPublisher(app_client=app_client)
        request = ReviewRequest(
            repository=RepositoryPayload(provider="github", owner="team", name="repo"),
            pull_request=PullRequestPayload(
                number=7,
                title="Test",
                author="dev",
                base_sha="base",
                head_sha="head",
                base_branch="main",
                head_branch="feature",
            ),
        )

        publisher._delete_previous_inline_comments(request, "token", marker)

        self.assertIn(
            (
                "DELETE",
                "/repos/team/repo/pulls/comments/99",
                "token",
                None,
            ),
            app_client.requests,
        )
        self.assertNotIn(
            (
                "DELETE",
                "/repos/team/repo/pulls/comments/100",
                "token",
                None,
            ),
            app_client.requests,
        )


if __name__ == "__main__":
    unittest.main()

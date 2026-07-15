import hashlib
import hmac
import unittest

from backend.app.core.config import Settings
from backend.app.services.github_app import (
    DEEP_REVIEW_ACTION_IDENTIFIER,
    GitHubWebhookError,
    GitHubWebhookProcessor,
    _complexity_source_priority,
    verify_github_signature,
)
from backend.app.services.rag import REPOSITORY_POLICY_PATH


class FakeGitHubClient:
    def installation_token(self, installation_id):
        self.installation_id = str(installation_id)
        return "installation-token"

    def get_pull_request(self, owner, repo, pull_number, token):
        return _pull_request_payload(number=pull_number)

    def list_pull_files(self, owner, repo, pull_number, token):
        return [
            {
                "filename": "app/api/items.py",
                "status": "modified",
                "additions": 12,
                "deletions": 2,
                "patch": "+return items",
            }
        ]

    def list_check_runs(self, owner, repo, ref, token):
        return [
            {
                "name": "test",
                "status": "completed",
                "conclusion": "success",
                "output": {"summary": "12 passed"},
                "html_url": "https://github.com/team/repo/actions/runs/1",
            }
        ]

    def get_file_content(self, owner, repo, path, ref, token):
        if path == REPOSITORY_POLICY_PATH:
            return "# Repository Policy\n\n## API Contract\n\nAPI 응답 계약을 유지한다.\n"
        if path == "app/api/items.py" and ref == "base-sha":
            return "def list_items():\n    return []\n"
        if path == "app/api/items.py" and ref == "head-sha":
            return "def list_items():\n    return [1]\n"
        return None


def _signature(payload_body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _repository_payload():
    return {
        "name": "repo",
        "full_name": "team/repo",
        "default_branch": "main",
        "owner": {"login": "team"},
    }


def _pull_request_payload(number=7):
    return {
        "number": number,
        "title": "Add API endpoint",
        "draft": False,
        "user": {"login": "dev"},
        "base": {"sha": "base-sha", "ref": "main"},
        "head": {"sha": "head-sha", "ref": "feature/items"},
    }


class GitHubWebhookTest(unittest.TestCase):
    def test_complexity_source_priority_prefers_branch_heavy_patch(self):
        large_linear_change = {
            "additions": 200,
            "deletions": 0,
            "patch": "+value = normalize(value)\n" * 20,
        }
        smaller_branch_change = {
            "additions": 20,
            "deletions": 0,
            "patch": "+if value:\n+    return value\n" * 4,
        }

        self.assertGreater(
            _complexity_source_priority(smaller_branch_change),
            _complexity_source_priority(large_linear_change),
        )

    def test_verify_github_signature_accepts_valid_hmac(self):
        body = b'{"zen":"Keep it logically awesome."}'
        verify_github_signature(body, "secret", _signature(body, "secret"))

    def test_verify_github_signature_rejects_invalid_hmac(self):
        with self.assertRaises(GitHubWebhookError):
            verify_github_signature(b"{}", "secret", "sha256=bad")

    def test_pull_request_waits_for_checks_in_after_checks_mode(self):
        settings = Settings(github_webhook_review_mode="after_checks")
        processor = GitHubWebhookProcessor(settings, client=FakeGitHubClient())

        plan = processor.review_plan(
            "pull_request",
            "delivery-1",
            {
                "action": "opened",
                "repository": _repository_payload(),
                "installation": {"id": 123},
                "pull_request": _pull_request_payload(),
            },
        )

        self.assertEqual(plan.status, "accepted")
        self.assertFalse(plan.requests)

    def test_check_suite_completed_builds_review_request(self):
        settings = Settings(github_webhook_review_mode="after_checks")
        processor = GitHubWebhookProcessor(settings, client=FakeGitHubClient())

        plan = processor.review_plan(
            "check_suite",
            "delivery-2",
            {
                "action": "completed",
                "repository": _repository_payload(),
                "installation": {"id": 123},
                "check_suite": {"pull_requests": [{"number": 7}]},
            },
        )

        self.assertEqual(plan.status, "ready")
        self.assertEqual(len(plan.requests), 1)
        request = plan.requests[0]
        self.assertEqual(request.repository.full_name, "team/repo")
        self.assertEqual(request.pull_request.number, 7)
        self.assertEqual(request.github.delivery_id, "delivery-2")
        self.assertEqual(request.github.installation_id, "123")
        self.assertEqual(request.checks[0].kind, "test")
        self.assertEqual(request.changed_files[0].path, "app/api/items.py")
        self.assertEqual(request.repository_policies[0].source_path, REPOSITORY_POLICY_PATH)
        self.assertEqual(request.repository_policies[0].section_title, "API Contract")

    def test_check_run_waits_for_check_suite_in_after_checks_mode(self):
        settings = Settings(github_webhook_review_mode="after_checks")
        processor = GitHubWebhookProcessor(settings, client=FakeGitHubClient())

        plan = processor.review_plan(
            "check_run",
            "delivery-3",
            {
                "action": "completed",
                "repository": _repository_payload(),
                "installation": {"id": 123},
                "check_run": {
                    "name": "test",
                    "pull_requests": [{"number": 7}],
                    "app": {"id": 999},
                },
            },
        )

        self.assertEqual(plan.status, "accepted")
        self.assertFalse(plan.requests)

    def test_check_run_requested_action_builds_manual_deep_review(self):
        settings = Settings(
            github_webhook_review_mode="after_checks",
            github_check_run_name="AI Code Review",
        )
        processor = GitHubWebhookProcessor(settings, client=FakeGitHubClient())

        plan = processor.review_plan(
            "check_run",
            "delivery-4",
            {
                "action": "requested_action",
                "requested_action": {"identifier": DEEP_REVIEW_ACTION_IDENTIFIER},
                "repository": _repository_payload(),
                "installation": {"id": 123},
                "check_run": {
                    "id": 456,
                    "name": "AI Code Review",
                    "pull_requests": [{"number": 7}],
                    "app": {"id": 999},
                },
            },
        )

        self.assertEqual(plan.status, "ready")
        self.assertEqual(plan.reason, "manual deep review requested")
        self.assertEqual(len(plan.requests), 1)
        request = plan.requests[0]
        self.assertEqual(request.review_mode, "deep_quality_review")
        self.assertEqual(request.github.event_name, "check_run.requested_action")
        self.assertEqual(request.github.check_run_id, "456")
        self.assertTrue(request.idempotency_key().endswith(":deep_quality_review"))
        self.assertIn("return []", request.changed_files[0].base_content)
        self.assertIn("return [1]", request.changed_files[0].head_content)


if __name__ == "__main__":
    unittest.main()

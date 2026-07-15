import unittest

from backend.app.core.routing import extract_features, select_route
from backend.app.core.schemas import ReviewRequest


def _request(checks, changed_files=None):
    return ReviewRequest.from_dict(
        {
            "repository": {"owner": "team", "name": "repo"},
            "pull_request": {
                "number": 1,
                "title": "Test PR",
                "author": "dev",
                "base_sha": "a",
                "head_sha": "b",
                "base_branch": "main",
                "head_branch": "feature",
            },
            "checks": checks,
            "changed_files": changed_files
            or [{"path": "app/api/users.py", "additions": 10, "deletions": 2, "patch": ""}],
        }
    )


class RoutingTest(unittest.TestCase):
    def test_failed_test_routes_to_low_tier(self):
        request = _request(
            [{"kind": "test", "status": "completed", "conclusion": "failure", "summary": "failed"}]
        )
        route = select_route(extract_features(request, policy_available=True))

        self.assertEqual(route.name, "simple_failure_review")
        self.assertEqual(route.model_tier, "solar3-low")
        self.assertFalse(route.use_rag)

    def test_policy_context_routes_to_medium_tier(self):
        request = _request(
            [
                {"kind": "lint", "status": "completed", "conclusion": "success", "summary": ""},
                {"kind": "test", "status": "completed", "conclusion": "success", "summary": ""},
            ]
        )
        route = select_route(extract_features(request, policy_available=True))

        self.assertEqual(route.name, "policy_context_review")
        self.assertEqual(route.model_tier, "solar3-medium")
        self.assertTrue(route.use_rag)

    def test_high_risk_path_stays_medium_by_default(self):
        request = _request(
            [{"kind": "test", "status": "completed", "conclusion": "success", "summary": ""}],
            changed_files=[
                {
                    "path": "app/auth/token_service.py",
                    "additions": 10,
                    "deletions": 1,
                    "patch": "+token = issue_token(user)",
                }
            ],
        )
        route = select_route(extract_features(request, policy_available=True))

        self.assertEqual(route.name, "policy_context_review")
        self.assertEqual(route.model_tier, "solar3-medium")
        self.assertIn("deep review can be requested", route.reasons[-1])

    def test_manual_deep_review_routes_to_high_tier(self):
        request = _request(
            [{"kind": "test", "status": "completed", "conclusion": "success", "summary": ""}]
        )
        route = select_route(
            extract_features(request, policy_available=True),
            review_mode="deep_quality_review",
        )

        self.assertEqual(route.name, "deep_quality_review")
        self.assertEqual(route.model_tier, "solar3-high")
        self.assertEqual(route.reasons, ["manual deep review requested"])


if __name__ == "__main__":
    unittest.main()

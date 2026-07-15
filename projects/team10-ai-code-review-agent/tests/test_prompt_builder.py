import json
import unittest

from backend.app.core.schemas import PolicyChunk, ReviewRequest, ReviewRoute
from backend.app.services.prompt_builder import build_review_messages, build_review_prompt_batches


def _request(changed_files=None):
    return ReviewRequest.from_dict(
        {
            "repository": {"owner": "team", "name": "repo"},
            "pull_request": {
                "number": 7,
                "title": "Optimize policy lookup",
                "author": "dev",
                "base_sha": "a",
                "head_sha": "b",
            },
            "changed_files": changed_files
            or [
                {
                    "path": "backend/policy.py",
                    "additions": 20,
                    "deletions": 4,
                    "patch": "+for policy in policies:\n+    find_match(policy)",
                }
            ],
        }
    )


class PromptBuilderTest(unittest.TestCase):
    def _policy_route(self):
        return ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["repository policy is available"],
            confidence=0.9,
        )

    def test_deep_review_requests_complexity_and_simplification(self):
        route = ReviewRoute(
            name="deep_quality_review",
            model_tier="solar3-high",
            use_rag=False,
            focus=["time_complexity", "space_complexity", "simplification"],
            reasons=["manual deep review requested"],
            confidence=0.9,
        )

        messages = build_review_messages(_request(), route, [])
        user_payload = json.loads(messages[1]["content"])
        instructions = " ".join(user_payload["review_instructions"])

        self.assertIn("time complexity", instructions)
        self.assertIn("space complexity", instructions)
        self.assertIn("simplification", instructions)
        self.assertEqual(user_payload["max_findings"], 8)

    def test_policy_context_includes_canonical_policy_source(self):
        route = self._policy_route()
        policy = PolicyChunk(
            source_path="policies/api-contract.md",
            section_title="Error response",
            content="Errors include code and message.",
            policy_type="api",
            score=0.75,
        )

        messages = build_review_messages(_request(), route, [policy])
        user_payload = json.loads(messages[1]["content"])
        prompt_policy = user_payload["review_payload"]["policies"][0]

        self.assertEqual(
            prompt_policy["policy_source"],
            "policies/api-contract.md#Error response",
        )
        self.assertEqual(prompt_policy["retrieval_score"], 0.75)

    def test_prompt_budget_limits_large_diff(self):
        route = ReviewRoute(
            name="simple_failure_review",
            model_tier="solar3-low",
            use_rag=False,
            focus=["failure_summary"],
            reasons=["syntax, lint, or test failed"],
            confidence=0.95,
        )
        files = [
            {
                "path": f"src/file_{index}.py",
                "additions": 100,
                "deletions": 0,
                "patch": "+" + ("x" * 5000),
            }
            for index in range(12)
        ]

        messages = build_review_messages(_request(files), route, [])
        user_payload = json.loads(messages[1]["content"])
        review_payload = user_payload["review_payload"]

        self.assertLessEqual(len(review_payload["changed_files"]), 8)
        self.assertTrue(review_payload["prompt_scope"]["files_truncated"])
        self.assertLessEqual(
            sum(len(item["patch"]) for item in review_payload["changed_files"]),
            12_000,
        )

    def test_prompt_scope_prioritizes_small_high_risk_file(self):
        route = ReviewRoute(
            name="simple_failure_review",
            model_tier="solar3-low",
            use_rag=False,
            focus=["failure_summary"],
            reasons=["syntax, lint, or test failed"],
            confidence=0.95,
        )
        files = [
            {
                "path": f"src/generated_{index}.py",
                "additions": 1000 - index,
                "deletions": 0,
                "patch": "+generated = True",
            }
            for index in range(8)
        ]
        files.append(
            {
                "path": "src/auth/token_store.py",
                "additions": 1,
                "deletions": 0,
                "patch": "+save_token(token)",
            }
        )

        messages = build_review_messages(_request(files), route, [])
        user_payload = json.loads(messages[1]["content"])
        included_paths = {
            item["path"] for item in user_payload["review_payload"]["changed_files"]
        }

        self.assertIn("src/auth/token_store.py", included_paths)

    def test_small_review_uses_single_prompt_batch(self):
        batches = build_review_prompt_batches(_request(), self._policy_route(), [])

        self.assertEqual(len(batches), 1)
        self.assertEqual(batches[0].index, 1)
        self.assertEqual(batches[0].count, 1)

    def test_large_review_is_split_by_file_and_patch_budget(self):
        files = [
            {
                "path": f"src/file_{index}.py",
                "additions": 100,
                "deletions": 0,
                "patch": "+" + ("x" * 2499),
            }
            for index in range(12)
        ]

        batches = build_review_prompt_batches(_request(files), self._policy_route(), [])

        self.assertGreater(len(batches), 1)
        self.assertTrue(all(len(batch.request.changed_files) <= 4 for batch in batches))
        self.assertTrue(all(batch.patch_chars <= 6_000 for batch in batches))
        self.assertTrue(all(batch.count == len(batches) for batch in batches))
        prompt_scope = json.loads(batches[0].messages[1]["content"])["review_payload"][
            "prompt_scope"
        ]
        self.assertEqual(prompt_scope["original_total_files"], 12)
        self.assertEqual(prompt_scope["batch_count"], len(batches))
        finding_limits = [
            json.loads(batch.messages[1]["content"])["max_findings"]
            for batch in batches
        ]
        self.assertTrue(all(limit == 1 for limit in finding_limits))

    def test_single_batch_keeps_route_finding_limit_and_counterevidence_rule(self):
        batches = build_review_prompt_batches(_request(), self._policy_route(), [])

        prompt = json.loads(batches[0].messages[1]["content"])

        self.assertEqual(prompt["max_findings"], 6)
        instructions = " ".join(prompt["review_harness_instructions"])
        self.assertIn("주장을 반증하는 코드", instructions)
        self.assertIn("빈 findings", instructions)


if __name__ == "__main__":
    unittest.main()

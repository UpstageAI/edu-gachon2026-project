import json
import unittest
from pathlib import Path

from backend.app.core.schemas import ReviewRequest, ReviewRoute
from backend.app.services.policy_harness import PolicyHarness
from backend.app.services.prompt_builder import build_review_prompt_batches
from backend.app.services.rag import LocalPolicyIndex
from review_harness.scripts.evaluate_harness import evaluate_harness


class PolicyHarnessTest(unittest.TestCase):
    def setUp(self):
        self.harness = PolicyHarness(Path("review_harness"))

    def test_selects_only_relevant_skills(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "backend/auth/token.py",
                        "patch": "+verify_token(authorization)",
                    }
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )

        context = self.harness.select(request, route)
        skill_ids = {skill.skill_id for skill in context.skills}

        self.assertIn("change-correctness", skill_ids)
        self.assertIn("security-boundary", skill_ids)
        self.assertNotIn("performance-simplification", skill_ids)
        self.assertIn("security", context.policy_types)
        self.assertNotIn(
            "secret-and-sensitive-log-flow",
            {card.card_id for card in context.knowledge_cards},
        )
        security_skill = next(
            skill for skill in context.skills if skill.skill_id == "security-boundary"
        )
        self.assertIn("owasp-secure-code-review", security_skill.source_ids)
        self.assertNotIn("instructions", context.to_dict(include_instructions=False)["skills"][0])
        persisted_card = context.to_dict(include_instructions=False)["knowledge_cards"][0]
        self.assertNotIn("check", persisted_card)
        self.assertNotIn("false_positive_guard", persisted_card)

    def test_prompt_harness_fixture_baseline(self):
        result = evaluate_harness()

        self.assertEqual(result["fixture_count"], 12)
        self.assertEqual(result["skill_recall"], 1.0, json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["skill_precision"], 1.0)
        self.assertEqual(
            result["knowledge_card_recall"],
            1.0,
            json.dumps(result, ensure_ascii=False),
        )
        self.assertEqual(result["knowledge_card_precision"], 1.0)
        self.assertEqual(result["source_backed_card_rate"], 1.0)
        self.assertEqual(result["source_utilization_rate"], 1.0)
        self.assertGreaterEqual(result["source_count"], 20)
        self.assertGreaterEqual(result["knowledge_card_count"], 20)
        self.assertEqual(
            result["policy_type_recall"],
            1.0,
            json.dumps(result, ensure_ascii=False),
        )
        self.assertGreaterEqual(result["policy_type_precision"], 0.9)
        self.assertGreater(
            result["policy_type_precision"],
            result["legacy_top3_policy_type_precision"],
        )
        self.assertGreater(result["vs_legacy_context_reduction"], 0.2)
        self.assertGreater(result["policy_context_reduction"], 0.5)
        test_card = next(
            card
            for card in self.harness.knowledge_cards
            if card["id"] == "test-distinguishes-regression"
        )
        self.assertIn("assertion의 회귀 검출력", test_card["false_positive_guard"])
        self.assertIn("네트워크", test_card["forbidden_claim_markers"])

    def test_deployment_smoke_does_not_select_unit_test_cards(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 12, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "scripts/local-deploy-test.sh",
                        "patch": (
                            "+client = GitHubAppClient(Settings.from_env())\n"
                            "+client.request_json('GET', '/app', token=client.create_jwt())"
                        ),
                    }
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )

        context = self.harness.select(request, route)
        selected_card_ids = {card.card_id for card in context.knowledge_cards}

        self.assertNotIn("test-distinguishes-regression", selected_card_ids)
        self.assertNotIn("test-brittle-implementation-detail", selected_card_ids)
        self.assertNotIn("secret-and-sensitive-log-flow", selected_card_ids)

    def test_path_and_patch_card_markers_must_match_the_same_file(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 13, "head_sha": "head"},
                "changed_files": [
                    {"path": "docs/logging.md", "patch": "+GitHub App setup guide"},
                    {"path": "scripts/deploy.sh", "patch": "+token = client.create_jwt()"},
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )

        context = self.harness.select(request, route)

        self.assertNotIn(
            "secret-and-sensitive-log-flow",
            {card.card_id for card in context.knowledge_cards},
        )

    def test_prompt_includes_selected_skills_and_at_most_two_policies(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 2, "title": "Secure API token", "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "backend/auth/logging.py",
                        "patch": "+logger.info('Authorization=%s', token)",
                    }
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )
        candidates = LocalPolicyIndex(Path("policies")).search(request, top_k=8)

        batches = build_review_prompt_batches(
            request,
            route,
            candidates,
            policy_harness=self.harness,
        )
        prompt = json.loads(batches[0].messages[1]["content"])
        security_skill = next(
            skill
            for skill in prompt["review_harness"]["skills"]
            if skill["skill_id"] == "security-boundary"
        )
        expected_instructions = Path(
            "review_harness/skills/security-boundary/SKILL.md"
        ).read_text(encoding="utf-8").strip()
        security_card = next(
            card
            for card in prompt["review_harness"]["knowledge_cards"]
            if card["card_id"] == "secret-and-sensitive-log-flow"
        )

        self.assertLessEqual(len(batches[0].policies), 2)
        self.assertIn("review_harness", prompt)
        self.assertIn("repository 정책이 아니다", prompt["review_harness_instructions"][0])
        self.assertTrue(prompt["review_harness"]["skills"])
        self.assertEqual(security_skill["instructions"], expected_instructions)
        self.assertIn("민감값의 source", security_card["evidence_required"])
        self.assertIn("유출로 판단하지 않는다", security_card["false_positive_guard"])
        self.assertEqual(prompt["language_contract"]["locale"], "ko-KR")
        self.assertIn("change_summary", prompt["output_schema"]["summary"])
        self.assertIn("file_summaries", prompt["output_schema"]["summary"])
        self.assertIn("knowledge_card_id", prompt["output_schema"]["findings"][0])
        self.assertEqual(
            set(prompt["finding_contract"]["allowed_knowledge_card_ids"]),
            {
                card["card_id"]
                for card in prompt["review_harness"]["knowledge_cards"]
            },
        )
        self.assertIn("security", prompt["review_harness"]["signals"])
        self.assertTrue(prompt["review_payload"]["policies"])
        selected_policy_types = {
            policy["policy_type"] for policy in prompt["review_payload"]["policies"]
        }
        self.assertIn("security", selected_policy_types)
        self.assertTrue(
            selected_policy_types.issubset(set(prompt["review_harness"]["policy_types"]))
        )

    def test_removed_unsafe_code_does_not_select_input_boundary_skill(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 3, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "backend/runner.py",
                        "patch": (
                            "@@ -10,1 +10,1 @@\n"
                            "-subprocess.run(command, shell=True)\n"
                            "+safe_run(command)"
                        ),
                    }
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )

        context = self.harness.select(request, route)

        self.assertNotIn(
            "input-boundary-safety",
            {skill.skill_id for skill in context.skills},
        )
        self.assertNotIn("input_boundary", context.signals)

    def test_additive_api_endpoint_does_not_select_sink_or_breaking_cards(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 4, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "app/api/profile.py",
                        "patch": (
                            "+def get_profile(user_id: str):\n"
                            "+    profile = service.load_profile(user_id)\n"
                            "+    return {\"data\": profile}"
                        ),
                    }
                ],
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["checks passed"],
            confidence=0.9,
        )

        context = self.harness.select(request, route)
        skill_ids = {skill.skill_id for skill in context.skills}
        card_ids = {card.card_id for card in context.knowledge_cards}

        self.assertNotIn("input-boundary-safety", skill_ids)
        self.assertNotIn("behavior-edge-and-failure-path", card_ids)
        self.assertNotIn("untrusted-input-before-sink", card_ids)
        self.assertNotIn("api-breaking-shape-change", card_ids)


if __name__ == "__main__":
    unittest.main()

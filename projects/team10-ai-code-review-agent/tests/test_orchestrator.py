import tempfile
import unittest
from pathlib import Path

from backend.app.core.config import Settings
from backend.app.core.schemas import ReviewRequest
from backend.app.services.orchestrator import create_orchestrator
from backend.app.services.rag import REPOSITORY_POLICY_PATH, split_policy_markdown


class OrchestratorTest(unittest.TestCase):
    def test_repository_policy_is_selected_and_used_by_review_workflow(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            policy_root = tmp_path / "policies"
            data_dir = tmp_path / "data"
            policy_root.mkdir()
            settings = Settings(
                policy_root=policy_root,
                review_harness_root=Path("review_harness"),
                local_data_dir=data_dir,
                review_store_path=data_dir / "reviews.json",
                comment_output_dir=data_dir / "comments",
                llm_mode="mock",
                publish_mode="local",
            )
            repository_policies = split_policy_markdown(
                REPOSITORY_POLICY_PATH,
                """# Team Policy

## API Response Contract

Profile API responses must include code and message fields.

## Security Logging

Authentication tokens must never be logged.
""",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 11,
                        "title": "Change profile API response",
                        "head_sha": "policy-head",
                    },
                    "checks": [
                        {"kind": "test", "status": "completed", "conclusion": "success"}
                    ],
                    "changed_files": [
                        {
                            "path": "app/api/profile.py",
                            "additions": 1,
                            "patch": (
                                "@@ -10,1 +10,1 @@\n"
                                "+return {'code': 'ok', 'message': 'done'}"
                            ),
                        }
                    ],
                    "repository_policies": [
                        policy.to_dict() for policy in repository_policies
                    ],
                }
            )
            events = []

            result = create_orchestrator(settings).run_review(
                request,
                event_publisher=lambda event_type, payload: events.append((event_type, payload)),
            )

            sources = [
                source
                for event, payload in events
                if event == "llm_batch_started"
                for source in payload["policy_sources"]
            ]
            self.assertTrue(result.features.policy_available)
            self.assertEqual(result.retrieved_policies[0].section_title, "API Response Contract")
            self.assertIn(
                f"{REPOSITORY_POLICY_PATH}#API Response Contract",
                sources,
            )
            self.assertNotIn(
                f"{REPOSITORY_POLICY_PATH}#Security Logging",
                sources,
            )

    def test_deep_review_measures_complexity_before_harness_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            policy_root = tmp_path / "policies"
            data_dir = tmp_path / "data"
            policy_root.mkdir()
            settings = Settings(
                policy_root=policy_root,
                review_harness_root=Path("review_harness"),
                local_data_dir=data_dir,
                review_store_path=data_dir / "reviews.json",
                comment_output_dir=data_dir / "comments",
                llm_mode="mock",
                publish_mode="local",
            )
            branches = "\n".join(
                f"    if value > {index}: result += 1" for index in range(15)
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {"number": 12, "head_sha": "complexity-head"},
                    "review_mode": "deep_quality_review",
                    "checks": [
                        {"kind": "test", "status": "completed", "conclusion": "success"}
                    ],
                    "changed_files": [
                        {
                            "path": "app/decision.py",
                            "additions": 15,
                            "patch": "@@ -1,1 +1,18 @@\n+def decide(value):\n+    result = 0",
                            "base_content": "def decide(value):\n    return 0\n",
                            "head_content": (
                                "def decide(value):\n    result = 0\n"
                                f"{branches}\n    return result\n"
                            ),
                        }
                    ],
                }
            )
            events = []

            result = create_orchestrator(settings).run_review(
                request,
                event_publisher=lambda event_type, payload: events.append((event_type, payload)),
            )

            complexity_event = next(
                payload for event, payload in events if event == "complexity_analyzed"
            )
            selected_cards = {
                card.card_id for card in result.review_harness.knowledge_cards
            }
            self.assertEqual(result.route.name, "deep_quality_review")
            self.assertEqual(result.complexity_metrics[0].after, 16)
            self.assertEqual(complexity_event["threshold_exceeded_count"], 1)
            self.assertIn("python-cyclomatic-complexity-threshold", selected_cards)

    def test_orchestrator_runs_local_review(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            policy_root = tmp_path / "policies"
            data_dir = tmp_path / "data"
            policy_root.mkdir()
            (policy_root / "review.md").write_text(
                "# Test Policy\n\nAPI changes should include tests.\n",
                encoding="utf-8",
            )
            settings = Settings(
                policy_root=policy_root,
                local_data_dir=data_dir,
                review_store_path=data_dir / "reviews.json",
                comment_output_dir=data_dir / "comments",
                llm_mode="mock",
                publish_mode="local",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 7,
                        "title": "Add API endpoint",
                        "author": "dev",
                        "base_sha": "a",
                        "head_sha": "b",
                        "base_branch": "main",
                        "head_branch": "feature",
                    },
                    "checks": [
                        {
                            "kind": "test",
                            "status": "completed",
                            "conclusion": "success",
                            "summary": "",
                        }
                    ],
                    "changed_files": [
                        {"path": "app/api/items.py", "additions": 12, "deletions": 0, "patch": ""}
                    ],
                }
            )

            events = []
            result = create_orchestrator(settings).run_review(
                request,
                event_publisher=lambda event_type, payload: events.append((event_type, payload)),
            )

            self.assertEqual(result.status, "completed")
            self.assertEqual(result.route.name, "policy_context_review")
            self.assertEqual(result.model_call.model, "solar-pro3")
            self.assertEqual(result.model_call.reasoning_effort, "medium")
            event_names = [event_name for event_name, _ in events]
            self.assertIn("route_selected", event_names)
            self.assertIn("llm_call_completed", event_names)
            self.assertIn("findings_validated", event_names)
            self.assertEqual(event_names[-1], "review_completed")
            completed_payload = events[-1][1]
            self.assertIn(completed_payload["workflow_engine"], {"langgraph", "local_fallback"})
            self.assertEqual(result.finding_validation["received"], 0)
            self.assertEqual(result.finding_validation["accepted"], 0)
            self.assertEqual(result.findings, [])
            self.assertTrue(settings.review_store_path.exists())
            self.assertTrue(list(settings.comment_output_dir.glob("*.md")))

    def test_orchestrator_aggregates_large_review_batches(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            policy_root = tmp_path / "policies"
            data_dir = tmp_path / "data"
            policy_root.mkdir()
            (policy_root / "review.md").write_text(
                "# Test Policy\n\nAPI changes should include tests.\n",
                encoding="utf-8",
            )
            settings = Settings(
                policy_root=policy_root,
                local_data_dir=data_dir,
                review_store_path=data_dir / "reviews.json",
                comment_output_dir=data_dir / "comments",
                llm_mode="mock",
                publish_mode="local",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 8,
                        "title": "Large API change",
                        "head_sha": "large-head",
                    },
                    "checks": [{"kind": "test", "status": "completed", "conclusion": "success"}],
                    "changed_files": [
                        {
                            "path": f"app/api/file_{index}.py",
                            "additions": 50,
                            "patch": "+" + ("x" * 1999),
                        }
                        for index in range(8)
                    ],
                }
            )
            events = []

            result = create_orchestrator(settings).run_review(
                request,
                event_publisher=lambda event_type, payload: events.append((event_type, payload)),
            )

            self.assertGreater(result.model_call.batch_count, 1)
            self.assertEqual(len(result.summary.file_summaries), 8)
            self.assertEqual(
                len([event for event, _ in events if event == "llm_batch_started"]),
                result.model_call.batch_count,
            )
            completed = [payload for event, payload in events if event == "llm_call_completed"]
            self.assertEqual(completed[0]["batch_count"], result.model_call.batch_count)

    def test_harness_signal_skill_policy_prompt_and_result_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            policy_root = tmp_path / "policies"
            data_dir = tmp_path / "data"
            policy_root.mkdir()
            (policy_root / "security-policy.md").write_text(
                "# Security Policy\n\n"
                "## SEC-LOG\n\n"
                "authorization token과 secret은 application log에 기록하지 않는다.\n",
                encoding="utf-8",
            )
            settings = Settings(
                policy_root=policy_root,
                review_harness_root=Path("review_harness"),
                local_data_dir=data_dir,
                review_store_path=data_dir / "reviews.json",
                comment_output_dir=data_dir / "comments",
                llm_mode="mock",
                publish_mode="local",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 9,
                        "title": "Prevent authorization token logging",
                        "head_sha": "security-head",
                    },
                    "checks": [
                        {"kind": "test", "status": "completed", "conclusion": "success"}
                    ],
                    "changed_files": [
                        {
                            "path": "backend/auth/logging.py",
                            "status": "modified",
                            "additions": 1,
                            "deletions": 1,
                            "patch": (
                                "@@ -10,1 +10,1 @@\n"
                                "-logger.info(authorization)\n"
                                "+logger.info('token validation completed')"
                            ),
                        }
                    ],
                }
            )
            events = []

            result = create_orchestrator(settings).run_review(
                request,
                event_publisher=lambda event_type, payload: events.append((event_type, payload)),
            )

            harness_event = next(
                payload for event, payload in events if event == "review_harness_selected"
            )
            batch_event = next(
                payload for event, payload in events if event == "llm_batch_started"
            )
            skill_ids = {skill.skill_id for skill in result.review_harness.skills}

            self.assertIn("security", harness_event["signals"])
            self.assertIn("security-boundary", harness_event["skills"])
            self.assertIn("secret-and-sensitive-log-flow", harness_event["knowledge_cards"])
            self.assertIn("security-boundary", batch_event["skills"])
            self.assertIn("secret-and-sensitive-log-flow", batch_event["knowledge_cards"])
            self.assertTrue(
                any("security-policy.md#SEC-LOG" == source for source in batch_event["policy_sources"])
            )
            self.assertIn("security-boundary", skill_ids)
            self.assertEqual(result.retrieved_policies[0].policy_type, "security")
            self.assertEqual(result.findings[0].policy_source, "security-policy.md#SEC-LOG")
            published = next(settings.comment_output_dir.glob("*.md")).read_text(encoding="utf-8")
            self.assertIn("### 변경 요약", published)
            self.assertIn("### 파일별 변경 요약", published)
            self.assertIn("### 리뷰", published)


if __name__ == "__main__":
    unittest.main()

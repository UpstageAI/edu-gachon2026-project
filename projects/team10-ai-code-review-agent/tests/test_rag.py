import tempfile
import unittest
from pathlib import Path

from backend.app.core.schemas import ReviewRequest
from backend.app.services.rag import (
    REPOSITORY_POLICY_PATH,
    LocalPolicyIndex,
    rank_policy_chunks,
    split_policy_markdown,
)


class LocalPolicyIndexTest(unittest.TestCase):
    def test_repository_policy_selects_diff_relevant_section(self):
        chunks = split_policy_markdown(
            REPOSITORY_POLICY_PATH,
            """# Team Review Policy

## API Contract

Profile API response must include code and message fields.

## Security Token

Authentication token must never be logged.
""",
        )
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 10, "title": "Change profile API response"},
                "changed_files": [
                    {
                        "path": "app/api/profile.py",
                        "patch": "+return {'code': 'ok', 'message': 'done'}",
                    }
                ],
            }
        )

        results = rank_policy_chunks(chunks, request, top_k=1, policy_types={"api"})

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_path, REPOSITORY_POLICY_PATH)
        self.assertEqual(results[0].section_title, "API Contract")
        self.assertEqual(results[0].policy_type, "api")

    def test_local_policy_index_retrieves_relevant_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "api-policy.md").write_text(
                "# API Contract\n\nProfile API responses should include code and message fields.\n",
                encoding="utf-8",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 1,
                        "title": "Add profile API response",
                        "author": "dev",
                        "base_sha": "a",
                        "head_sha": "b",
                        "base_branch": "main",
                        "head_branch": "feature",
                    },
                    "changed_files": [
                        {
                            "path": "app/api/profile.py",
                            "additions": 5,
                            "deletions": 1,
                            "patch": "+return {'data': profile}",
                        }
                    ],
                }
            )

            index = LocalPolicyIndex(tmp_path)
            results = index.search(request)

            self.assertTrue(index.has_policy())
            self.assertTrue(results)
            self.assertEqual(results[0].source_path, "api-policy.md")
            self.assertGreater(results[0].score, 0)

    def test_local_policy_index_does_not_fallback_to_unrelated_policy(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "security-policy.md").write_text(
                "# Secret Logging\n\nAuthentication tokens must never be logged.\n",
                encoding="utf-8",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {
                        "number": 2,
                        "title": "Adjust calendar color",
                        "author": "dev",
                        "base_sha": "a",
                        "head_sha": "b",
                    },
                    "changed_files": [
                        {
                            "path": "frontend/calendar.css",
                            "additions": 1,
                            "deletions": 1,
                            "patch": "+color: blue;",
                        }
                    ],
                }
            )

            self.assertEqual(LocalPolicyIndex(tmp_path).search(request), [])

    def test_local_policy_index_tokenizes_file_path_segments(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "webhook-policy.md").write_text(
                "# Webhook Signature\n\nWebhook handlers must verify the signature before parsing.",
                encoding="utf-8",
            )
            request = ReviewRequest.from_dict(
                {
                    "repository": {"owner": "team", "name": "repo"},
                    "pull_request": {"number": 3, "title": "Refactor handler"},
                    "changed_files": [
                        {
                            "path": "backend/app/services/github_webhook.py",
                            "additions": 5,
                            "deletions": 2,
                            "patch": "+def verify_signature(payload): ...",
                        }
                    ],
                }
            )

            results = LocalPolicyIndex(tmp_path).search(request)

            self.assertTrue(results)
            self.assertEqual(results[0].source_path, "webhook-policy.md")

    def test_markdown_headings_are_metadata_not_standalone_chunks(self):
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            (tmp_path / "observability-policy.md").write_text(
                "# Observability Policy\n\n## Trace Context\n\nAPI calls include a review run id.\n",
                encoding="utf-8",
            )

            chunks = LocalPolicyIndex(tmp_path).load_chunks()

            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].section_title, "Trace Context")
            self.assertEqual(chunks[0].policy_type, "observability")
            self.assertNotIn("#", chunks[0].content)

    def test_project_policy_retrieval_returns_normative_api_rule(self):
        policy_root = Path(__file__).resolve().parents[1] / "policies"
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 4, "title": "Change profile API response field"},
                "checks": [
                    {
                        "kind": "test",
                        "status": "completed",
                        "conclusion": "success",
                        "summary": "API tests passed",
                    }
                ],
                "changed_files": [
                    {
                        "path": "backend/app/api/profile.py",
                        "additions": 4,
                        "deletions": 2,
                        "patch": "+return {'profile': profile}",
                    }
                ],
            }
        )

        results = LocalPolicyIndex(policy_root).search(request, top_k=3)

        self.assertTrue(results)
        self.assertEqual(results[0].source_path, "api-contract.md")
        self.assertEqual(results[0].section_title, "API-001 안정적인 응답 계약")
        self.assertNotIn("적용 범위", [result.section_title for result in results])


if __name__ == "__main__":
    unittest.main()

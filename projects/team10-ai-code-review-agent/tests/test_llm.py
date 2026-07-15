import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from backend.app.core.config import Settings
from backend.app.core.schemas import ReviewRequest, ReviewRoute
from backend.app.services.llm import LiteLLMClient, _parse_json


class LLMResponseParsingTest(unittest.TestCase):
    def test_parses_json_object(self):
        self.assertEqual(_parse_json('{"summary": {}, "findings": []}')["findings"], [])

    def test_extracts_json_object_from_markdown_fence(self):
        parsed = _parse_json('```json\n{"summary": {}, "findings": []}\n```')

        self.assertEqual(parsed["summary"], {})

    def test_rejects_empty_content(self):
        with self.assertRaisesRegex(RuntimeError, "did not contain JSON content"):
            _parse_json("")

    def test_rejects_non_object_json(self):
        with self.assertRaisesRegex(RuntimeError, "must be an object"):
            _parse_json("[]")

    def test_solar_call_uses_route_specific_max_tokens(self):
        client = LiteLLMClient(
            Settings(
                llm_mode="litellm",
                upstage_api_key="test-key",
                upstage_api_base_url="https://api.upstage.ai/v1",
            )
        )
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=False,
            focus=["general"],
            reasons=["checks passed"],
            confidence=0.9,
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content='{"summary":{"overall_risk":"low","short_comment":"ok",'
                        '"change_summary":"API 응답을 변경했습니다.",'
                        '"file_summaries":[]},'
                        '"findings":[]}'
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

        with patch("litellm.completion", return_value=response) as completion:
            client.generate_review(request, route, [], [{"role": "user", "content": "review"}])

        kwargs = completion.call_args.kwargs
        self.assertEqual(kwargs["max_tokens"], 8192)
        self.assertEqual(kwargs["num_retries"], 1)
        self.assertEqual(kwargs["metadata"]["max_tokens"], 8192)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})

    def test_retries_once_when_model_returns_truncated_json(self):
        client = LiteLLMClient(
            Settings(
                llm_mode="litellm",
                upstage_api_key="test-key",
                upstage_api_base_url="https://api.upstage.ai/v1",
            )
        )
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
            }
        )
        route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=False,
            focus=["general"],
            reasons=["checks passed"],
            confidence=0.9,
        )
        truncated = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"summary":{"short_comment":"끊긴 응답'),
                    finish_reason="length",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )
        recovered = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=(
                            '{"summary":{"overall_risk":"low",'
                            '"change_summary":"응답을 복구했습니다.",'
                            '"file_summaries":[]},"findings":[]}'
                        )
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

        with patch(
            "litellm.completion",
            side_effect=[truncated, recovered],
        ) as completion:
            summary, findings, _ = client.generate_review(
                request,
                route,
                [],
                [{"role": "user", "content": "review"}],
            )

        self.assertEqual(completion.call_count, 2)
        self.assertEqual(completion.call_args_list[0].kwargs["metadata"]["response_attempt"], 1)
        self.assertEqual(completion.call_args_list[1].kwargs["metadata"]["response_attempt"], 2)
        self.assertEqual(summary.change_summary, "응답을 복구했습니다.")
        self.assertEqual(findings, [])

    def test_file_summaries_reject_unknown_paths_and_fill_missing_files(self):
        client = LiteLLMClient(
            Settings(
                llm_mode="litellm",
                upstage_api_key="test-key",
                upstage_api_base_url="https://api.upstage.ai/v1",
            )
        )
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "app/api.py",
                        "status": "modified",
                        "additions": 3,
                        "deletions": 1,
                    },
                    {
                        "path": "tests/test_api.py",
                        "status": "added",
                        "additions": 8,
                    },
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
        content = json.dumps(
            {
                "summary": {
                    "overall_risk": "low",
                    "short_comment": "API 변경",
                    "change_summary": "API 응답과 테스트를 변경했습니다.",
                    "file_summaries": [
                        {"file_path": "app/api.py", "change_summary": "응답 필드를 추가했습니다."},
                        {"file_path": "not/in/diff.py", "change_summary": "허위 경로"},
                    ],
                },
                "findings": [],
            },
            ensure_ascii=False,
        )
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

        with patch("litellm.completion", return_value=response):
            summary, _, _ = client.generate_review(
                request,
                route,
                [],
                [{"role": "user", "content": "review"}],
            )

        self.assertEqual(
            [item.file_path for item in summary.file_summaries],
            ["app/api.py", "tests/test_api.py"],
        )
        self.assertEqual(summary.file_summaries[0].change_summary, "응답 필드를 추가했습니다.")
        self.assertIn("새 파일 추가", summary.file_summaries[1].change_summary)

    def test_english_summaries_fall_back_to_korean_change_statistics(self):
        client = LiteLLMClient(
            Settings(
                llm_mode="litellm",
                upstage_api_key="test-key",
                upstage_api_base_url="https://api.upstage.ai/v1",
            )
        )
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
                "changed_files": [
                    {"path": "app/api.py", "additions": 3, "deletions": 1}
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
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {
                                "summary": {
                                    "overall_risk": "low",
                                    "short_comment": "Changed the API response.",
                                    "change_summary": "Added a response field.",
                                    "file_summaries": [
                                        {
                                            "file_path": "app/api.py",
                                            "change_summary": "Added a response field.",
                                        }
                                    ],
                                },
                                "findings": [],
                            }
                        )
                    ),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        )

        with patch("litellm.completion", return_value=response):
            summary, _, _ = client.generate_review(
                request,
                route,
                [],
                [{"role": "user", "content": "review"}],
            )

        self.assertEqual(summary.change_summary, "변경 파일 1개에서 3줄을 추가하고 1줄을 삭제했습니다.")
        self.assertEqual(summary.short_comment, summary.change_summary)
        self.assertEqual(
            summary.file_summaries[0].change_summary,
            "파일 수정: 3줄 추가, 1줄 삭제",
        )


if __name__ == "__main__":
    unittest.main()

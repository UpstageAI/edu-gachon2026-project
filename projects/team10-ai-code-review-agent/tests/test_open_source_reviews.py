import unittest

from backend.app.evaluation.open_source_reviews import (
    collect_repository_reviews,
    normalize_review,
    normalize_review_comment,
    summarize_records,
)


class FakeGitHubClient:
    def paginate(self, path, max_items=None):
        if path.endswith("/reviews"):
            return [
                {
                    "id": 1,
                    "state": "APPROVED",
                    "commit_id": "reviewed",
                    "user": {"login": "maintainer"},
                    "author_association": "MEMBER",
                }
            ]
        if path.endswith("/comments"):
            return [
                {
                    "id": 2,
                    "pull_request_review_id": 1,
                    "path": "src/main.py",
                    "line": 12,
                    "side": "RIGHT",
                    "body": "Handle the empty input before indexing.",
                    "user": {"login": "maintainer"},
                    "author_association": "MEMBER",
                }
            ]
        return [{"number": 7}][:max_items]

    def get_json(self, path):
        return {
            "number": 7,
            "title": "Handle empty input",
            "state": "closed",
            "merged": True,
            "base": {"sha": "base"},
            "head": {"sha": "head"},
            "additions": 3,
            "deletions": 1,
            "changed_files": 1,
        }


class OpenSourceReviewDatasetTest(unittest.TestCase):
    def test_normalizes_maintainer_and_bot_metadata(self):
        review = normalize_review(
            {
                "state": "commented",
                "user": {"login": "review-bot[bot]"},
                "author_association": "NONE",
            }
        )
        comment = normalize_review_comment(
            {
                "user": {"login": "owner"},
                "author_association": "OWNER",
                "path": "src/main.py",
                "original_line": 9,
            }
        )

        self.assertTrue(review["is_bot"])
        self.assertTrue(comment["is_maintainer"])
        self.assertEqual(comment["line"], 9)

    def test_collects_review_commit_candidates_and_summary(self):
        records = collect_repository_reviews(
            "team/repo",
            max_prs=1,
            client=FakeGitHubClient(),
        )
        summary = summarize_records(records)

        self.assertEqual(records[0]["candidate_review_commits"], ["reviewed"])
        self.assertEqual(summary["pull_requests"], 1)
        self.assertEqual(summary["merged_pull_requests"], 1)
        self.assertEqual(summary["maintainer_root_comments"], 1)


if __name__ == "__main__":
    unittest.main()

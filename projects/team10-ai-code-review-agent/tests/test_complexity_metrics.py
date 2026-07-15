import unittest
from pathlib import Path

from backend.app.core.schemas import ChangedFilePayload, ReviewRequest
from review_harness.scripts.complexity_metrics import (
    analyze_complexity,
    analyze_python_file,
)


COMPLEX_FUNCTION = (
    Path(__file__).parent / "fixtures" / "complexity_regression.py"
).read_text(encoding="utf-8")


class ComplexityMetricsTest(unittest.TestCase):
    def test_radon_reports_before_after_and_threshold_for_changed_function(self):
        changed_file = ChangedFilePayload(
            path="app/decision.py",
            base_content="def classify_review(value):\n    return int(value > 0)\n",
            head_content=COMPLEX_FUNCTION,
        )

        metrics = analyze_python_file(changed_file)

        self.assertEqual(len(metrics), 1)
        metric = metrics[0]
        self.assertEqual(metric.tool, "radon")
        self.assertEqual(metric.symbol, "classify_review")
        self.assertEqual(metric.before, 1)
        self.assertEqual(metric.after, 16)
        self.assertEqual(metric.delta, 15)
        self.assertEqual(metric.threshold, 15)
        self.assertTrue(metric.exceeded_threshold)
        self.assertEqual(metric.rank_before, "A")
        self.assertEqual(metric.rank_after, "C")

    def test_analysis_runs_only_for_manual_deep_review(self):
        request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1},
                "changed_files": [
                    {
                        "path": "app/decision.py",
                        "base_content": "def decide(value):\n    return 0\n",
                        "head_content": COMPLEX_FUNCTION,
                    }
                ],
            }
        )

        self.assertEqual(analyze_complexity(request), [])

    def test_invalid_python_source_does_not_fail_review(self):
        changed_file = ChangedFilePayload(
            path="app/broken.py",
            base_content="def okay():\n    return 1\n",
            head_content="def broken(:\n",
        )

        self.assertEqual(analyze_python_file(changed_file), [])


if __name__ == "__main__":
    unittest.main()

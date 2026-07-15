import unittest
from dataclasses import replace

from backend.app.core.schemas import (
    ComplexityMetric,
    PolicyChunk,
    ReviewFinding,
    ReviewKnowledgeCard,
    ReviewRequest,
    ReviewRoute,
)
from backend.app.services.review_quality import validate_and_rank_findings


class ReviewQualityTest(unittest.TestCase):
    def setUp(self):
        self.request = ReviewRequest.from_dict(
            {
                "repository": {"owner": "team", "name": "repo"},
                "pull_request": {"number": 1, "head_sha": "head"},
                "changed_files": [
                    {
                        "path": "app/service.py",
                        "additions": 3,
                        "deletions": 1,
                        "patch": "@@ -9,2 +9,4 @@\n old\n-removed\n+added\n+more\n tail",
                    }
                ],
            }
        )
        self.route = ReviewRoute(
            name="policy_context_review",
            model_tier="solar3-medium",
            use_rag=True,
            focus=["repo_policy"],
            reasons=["repository policy is available"],
            confidence=0.9,
        )
        self.policies = [
            PolicyChunk(
                source_path="security.md",
                section_title="Secret logging",
                content="Do not log tokens.",
                policy_type="security",
            )
        ]
        self.cards = [
            ReviewKnowledgeCard(
                card_id="secret-log-flow",
                title="Secret log flow",
                skill_id="security-boundary",
                check="Check token logging.",
                evidence_required="A token and logging sink.",
                false_positive_guard="Ignore redacted values.",
                severity_cap="medium",
            )
        ]

    def _finding(self, **overrides):
        payload = {
            "severity": "P1",
            "category": "security",
            "file_path": "app/service.py",
            "line_start": 10,
            "line_end": 10,
            "message": "토큰이 로그에 기록됩니다.",
            "suggestion": "로그 호출에서 토큰을 제거하세요.",
            "policy_source": "security.md",
            "confidence": 1.2,
        }
        payload.update(overrides)
        return ReviewFinding(**payload)

    def test_validates_line_policy_severity_and_confidence(self):
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [self._finding()],
        )

        self.assertEqual(report["accepted"], 1)
        self.assertEqual(findings[0].severity, "high")
        self.assertEqual(findings[0].line_start, 10)
        self.assertEqual(findings[0].policy_source, "security.md#Secret logging")
        self.assertEqual(findings[0].confidence, 1.0)

    def test_drops_unknown_files_and_deduplicates(self):
        finding = self._finding()
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [finding, finding, self._finding(file_path="missing.py")],
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(report["duplicate_dropped"], 1)
        self.assertEqual(report["unknown_file_dropped"], 1)

    def test_keeps_finding_but_removes_unverifiable_line_and_policy(self):
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [self._finding(line_start=999, line_end=999, policy_source="invented.md")],
        )

        self.assertEqual(len(findings), 1)
        self.assertIsNone(findings[0].line_start)
        self.assertIsNone(findings[0].policy_source)
        self.assertEqual(report["invalid_line_removed"], 1)
        self.assertEqual(report["invalid_policy_source_removed"], 1)

    def test_validates_card_id_and_enforces_card_severity_cap(self):
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [
                self._finding(knowledge_card_id="secret-log-flow"),
                self._finding(
                    message="두 번째 문제입니다.",
                    knowledge_card_id="invented-card",
                ),
            ],
            knowledge_cards=self.cards,
        )

        findings_by_message = {finding.message: finding for finding in findings}
        capped = findings_by_message["토큰이 로그에 기록됩니다."]
        self.assertEqual(capped.severity, "medium")
        self.assertEqual(capped.knowledge_card_id, "secret-log-flow")
        self.assertNotIn("두 번째 문제입니다.", findings_by_message)
        self.assertEqual(report["severity_capped_by_card"], 1)
        self.assertEqual(report["invalid_knowledge_card_dropped"], 1)
        self.assertEqual(report["invalid_knowledge_card_ids"], ["invented-card"])

    def test_drops_finding_without_card_when_harness_cards_are_selected(self):
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [self._finding(knowledge_card_id=None)],
            knowledge_cards=self.cards,
        )

        self.assertEqual(findings, [])
        self.assertEqual(report["missing_knowledge_card_dropped"], 1)

    def test_drops_claim_forbidden_by_selected_card(self):
        card = ReviewKnowledgeCard(
            card_id="test-regression",
            title="Regression assertion",
            skill_id="change-correctness",
            check="Check behavior assertions.",
            evidence_required="An assertion tied to changed behavior.",
            false_positive_guard="Do not infer network behavior.",
            severity_cap="medium",
            forbidden_claim_markers=["네트워크", "mock"],
        )
        finding = self._finding(
            knowledge_card_id="test-regression",
            message="테스트가 실제 네트워크를 호출합니다.",
            suggestion="mock으로 외부 호출을 대체하세요.",
        )

        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [finding],
            knowledge_cards=[card],
        )

        self.assertEqual(findings, [])
        self.assertEqual(report["knowledge_card_guard_dropped"], 1)

    def test_drops_english_finding_before_publishing(self):
        findings, report = validate_and_rank_findings(
            self.request,
            self.route,
            self.policies,
            [
                self._finding(
                    message="Token is logged.",
                    suggestion="Remove the token from the log call.",
                )
            ],
        )

        self.assertEqual(findings, [])
        self.assertEqual(report["non_korean_finding_dropped"], 1)

    def test_complexity_finding_requires_matching_measured_metric(self):
        metric = ComplexityMetric(
            metric_id="python:cyclomatic_complexity:app/service.py:handle",
            tool="radon",
            metric="cyclomatic_complexity",
            file_path="app/service.py",
            symbol="handle",
            line_start=10,
            before=8,
            after=18,
            delta=10,
            threshold=15,
            exceeded_threshold=True,
            rank_before="B",
            rank_after="C",
        )
        request = replace(self.request, complexity_metrics=[metric])
        card = ReviewKnowledgeCard(
            card_id="python-cyclomatic-complexity-threshold",
            title="Python complexity",
            skill_id="performance-simplification",
            check="Check measured complexity.",
            evidence_required="A metric id.",
            false_positive_guard="Ignore unmeasured claims.",
            severity_cap="medium",
        )
        valid = self._finding(
            category="maintainability",
            message="함수 분기가 임계값을 초과했습니다.",
            suggestion="조건 분기를 작은 함수로 분리하세요.",
            knowledge_card_id=card.card_id,
            evidence={"metric_id": metric.metric_id},
        )
        invented = self._finding(
            category="maintainability",
            message="측정되지 않은 함수가 복잡합니다.",
            suggestion="측정되지 않은 함수를 분리하세요.",
            knowledge_card_id=card.card_id,
            evidence={"metric_id": "invented"},
        )

        findings, report = validate_and_rank_findings(
            request,
            self.route,
            [],
            [valid, invented],
            knowledge_cards=[card],
        )

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].evidence["before"], 8)
        self.assertEqual(findings[0].evidence["after"], 18)
        self.assertIn("8에서 18로", findings[0].evidence["trigger"])
        self.assertEqual(report["invalid_complexity_evidence_dropped"], 1)


if __name__ == "__main__":
    unittest.main()

from datetime import date

from app.core import langfuse_scores
from app.core.config import Settings
from app.core.schemas import EvaluationResult


def _eval_result() -> EvaluationResult:
    return EvaluationResult(
        eval_name="safety.forbidden_terms",
        score=1.0,
        passed=True,
        result={"secret_token": "must-not-leak", "violations": []},
        run_id="run_score",
        run_date=date(2026, 7, 14),
        trace_id="trace_score",
    )


def test_score_eval_result_is_noop_when_langfuse_disabled():
    ok = langfuse_scores.score_eval_result(
        _eval_result(),
        settings=Settings(langfuse_enabled=False),
    )

    assert ok is False


def test_score_eval_result_redacts_metadata_and_uses_trace_id(monkeypatch):
    calls = []

    class FakeClient:
        def score(self, **payload):
            calls.append(payload)

    monkeypatch.setattr(
        langfuse_scores.observability,
        "configure_langfuse_environment",
        lambda settings=None: True,
    )
    monkeypatch.setattr(langfuse_scores, "_get_langfuse_client", lambda: FakeClient())

    ok = langfuse_scores.score_eval_result(
        _eval_result(),
        settings=Settings(
            langfuse_enabled=True,
            langfuse_public_key="pk-test",
            langfuse_secret_key="sk-test",
        ),
    )

    assert ok is True
    assert calls == [
        {
            "trace_id": "trace_score",
            "name": "safety.forbidden_terms",
            "value": 1.0,
            "comment": "passed",
            "metadata": {
                "run_id": "run_score",
                "run_date": "2026-07-14",
                "topic_id": None,
                "passed": True,
                "result": {"secret_token": "[redacted]", "violations": []},
            },
        }
    ]

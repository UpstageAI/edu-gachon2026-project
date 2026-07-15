import pytest


def test_mask_sensitive_text_redacts_common_secrets():
    from app.core.llm_guardrails import mask_sensitive_text

    text = (
        "contact me at analyst@example.com and use "
        "https://discord.com/api/webhooks/123456789/token-value"
    )

    masked = mask_sensitive_text(text)

    assert "analyst@example.com" not in masked
    assert "discord.com/api/webhooks" not in masked
    assert "[EMAIL_REDACTED]" in masked
    assert "[WEBHOOK_REDACTED]" in masked


def test_validate_card_json_rejects_forbidden_financial_advice():
    from app.core.llm_guardrails import GuardrailViolation, validate_json_payload
    from app.core.config import Settings

    payload = {
        "headline": "지금 매수 기회",
        "lead": "단기 반등 가능성",
        "body": "목표가를 제시하며 반드시 수익이 난다고 단정합니다.",
        "source": "예시통신",
    }

    with pytest.raises(GuardrailViolation) as exc_info:
        validate_json_payload(payload, profile="card", settings=Settings())

    assert exc_info.value.reason == "forbidden_terms"
    # 조언 구(phrase) 기반: "지금 매수"(headline) + "반드시 수익"(body) 차단.
    # 사실 보도에 흔한 "목표가"(증권사 목표가 상향 등)는 오탐이라 금지어에서 제외됨.
    terms = exc_info.value.details["terms"]
    assert "지금 매수" in terms and "반드시 수익" in terms


def test_validate_card_json_allows_market_descriptive_trading_terms():
    from app.core.llm_guardrails import validate_json_payload
    from app.core.config import Settings

    payload = {
        "headline": "매수세 유입",
        "lead": "위험자산 선호가 회복됐습니다.",
        "body": "기관 매도 압력은 남아 있지만 장기 보유 심리가 일부 개선됐다는 보도입니다.",
        "source": "예시통신",
    }

    result = validate_json_payload(payload, profile="card", settings=Settings())

    assert result["headline"] == "매수세 유입"


def test_validate_card_json_requires_card_keys():
    from app.core.llm_guardrails import GuardrailViolation, validate_json_payload
    from app.core.config import Settings

    with pytest.raises(GuardrailViolation) as exc_info:
        validate_json_payload({"headline": "나스닥 상승"}, profile="card", settings=Settings())

    assert exc_info.value.reason == "schema_error"
    assert "body" in exc_info.value.details["missing_keys"]


def test_validate_generic_payload_masks_pii_without_card_schema():
    from app.core.llm_guardrails import validate_json_payload
    from app.core.config import Settings

    payload = {"intent": "add_topic", "topic": "달러", "note": "user@example.com"}

    result = validate_json_payload(payload, profile="intent", settings=Settings())

    assert result["note"] == "[EMAIL_REDACTED]"

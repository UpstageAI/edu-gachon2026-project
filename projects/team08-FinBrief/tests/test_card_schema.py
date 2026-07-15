import pytest
from pydantic import ValidationError
from app.agents.card_schema import CardContent


def test_headline_overflow_rejected():
    with pytest.raises(ValidationError):
        CardContent(category="MARKET", subtitle="s", headline="x" * 25, lead="l", body="b", source="src")


def test_valid_card():
    c = CardContent(category="MARKET", subtitle="나스닥", headline="나스닥 상승", lead="l", body="b", source="src")
    assert c.category == "MARKET" and c.disclaimer

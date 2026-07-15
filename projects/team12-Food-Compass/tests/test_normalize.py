from app.tools.item_alias import resolve_processed_alias
from app.tools.normalize import rice_price_per_bowl


class TestRicePricePerBowl:
    def test_20kg_bag(self):
        # 쌀 20kg 60,800원 -> 100g당 304원 -> 밥 1공기(마른 쌀 90g) 273.6원
        assert rice_price_per_bowl(60_800, "20kg") == 273.6

    def test_4kg_bag(self):
        # 쌀 4kg 15,000원 -> 100g당 375원 -> 밥 1공기 337.5원
        assert rice_price_per_bowl(15_000, "4kg") == 337.5

    def test_unrecognized_unit_returns_none(self):
        # "묶음"은 무게/개수 단위 어느 쪽으로도 인식되지 않는 형식 — 임의 추정 없이 None
        assert rice_price_per_bowl(60_800, "1묶음") is None

    def test_missing_unit_returns_none(self):
        assert rice_price_per_bowl(60_800, None) is None


class TestResolveProcessedAlias:
    def test_known_alias(self):
        assert resolve_processed_alias("즉석밥") == "햇반(210g)"
        assert resolve_processed_alias("햇반") == "햇반(210g)"

    def test_unknown_alias_returns_none(self):
        assert resolve_processed_alias("두부") is None

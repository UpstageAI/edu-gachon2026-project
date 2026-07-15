"""
tests/test_retriever.py
retriever 테스트. 외부(Supabase/Upstage) 의존 없이 돈다.
  - CSV 경로: foods를 명시 주입하면 Supabase를 타지 않는다.
  - Supabase 경로: RPC/embedding을 mock해서 파라미터·변환만 검증.
"""

from app.schemas import FoodItem, UserConditions, UserProfile
from app.services import food_retriever
from app.services.food_retriever import (
    build_search_query,
    contains_excluded,
    load_foods,
    retrieve_foods,
)


def _mk(name, ingredients=""):
    return FoodItem(
        food_id=abs(hash(name)) % 100000,
        food_name=name,
        meal_role="반찬",
        kcal=100,
        carbohydrate=10,
        protein=5,
        fat=3,
        sodium=100,
        ingredients=ingredients,
    )


def test_contains_excluded_checks_name_and_ingredients():
    """알레르겐이 이름에 있든(계란찜) 재료에만 있든(양배추감자전) 둘 다 잡는다."""
    assert contains_excluded(_mk("계란찜"), ["계란"]) is True
    assert contains_excluded(_mk("양배추감자전", "감자, 양배추, 계란 1개"), ["계란"]) is True
    assert contains_excluded(_mk("시금치나물", "시금치, 참기름"), ["계란"]) is False


def test_ingredient_allergen_filtered_from_csv_candidates():
    """재료에 알레르겐이 든 음식은 CSV 검색 후보에서 제외된다(이름엔 안 드러나도)."""
    prof = UserProfile(allergies=["계란", "달걀"])
    result = retrieve_foods(UserConditions(), prof, foods=load_foods())
    candidates = [f for role in result.values() for f in role]
    leaked = [f.food_name for f in candidates if contains_excluded(f, ["계란", "달걀"])]
    assert not leaked, f"재료에 계란 든 음식이 후보에 샘: {leaked}"


def test_load_foods():
    """CSV 로딩되고 음식이 있는지"""
    foods = load_foods()
    assert len(foods) > 0


def test_retrieve_returns_candidates_csv():
    """CSV 주입 시 후보가 역할별로 나오는지 (외부 의존 없음)"""
    cond = UserConditions(target_kcal=400, kcal_mode="upper", preferences=["야채 많은"])
    result = retrieve_foods(cond, UserProfile(), foods=load_foods())
    total = sum(len(v) for v in result.values())
    assert total > 0
    assert set(result.keys()) == {"밥", "국물", "반찬", "한그릇"}


def test_allergy_excluded_csv():
    """알레르기 음식이 후보에서 빠지는지 (CSV 경로)"""
    cond = UserConditions(target_kcal=400, kcal_mode="upper")
    prof = UserProfile(allergies=["계란"])
    result = retrieve_foods(cond, prof, foods=load_foods())
    for foods in result.values():
        for f in foods:
            assert "계란" not in f.food_name


def test_kcal_ceiling_csv():
    """target_kcal 상한이 CSV 경로에서 적용되는지"""
    cond = UserConditions(target_kcal=300, kcal_mode="upper")
    result = retrieve_foods(cond, UserProfile(), foods=load_foods())
    for foods in result.values():
        for f in foods:
            assert f.kcal <= 300


def test_low_sodium_filters_high_sodium_candidates_csv():
    """'저염' nutrition_goal이 있으면 고나트륨 후보가 사실 축에서 배제되는지 (CSV 경로)"""
    from app.services.food_retriever import LOW_SODIUM_MAX

    cond = UserConditions(nutrition_goals=["저염"])
    result = retrieve_foods(cond, UserProfile(), foods=load_foods())
    total = 0
    for foods in result.values():
        for f in foods:
            assert f.sodium <= LOW_SODIUM_MAX  # 상한 초과 후보는 없어야 함
            total += 1
    assert total > 0  # 저염이어도 후보 자체는 남아야 함


def test_no_sodium_filter_when_not_low_sodium_csv():
    """저염 요청이 아니면 나트륨 필터가 걸리지 않아 고나트륨 음식도 후보에 남는지"""
    from app.services.food_retriever import LOW_SODIUM_MAX

    cond = UserConditions()  # nutrition_goals 없음
    result = retrieve_foods(cond, UserProfile(), foods=load_foods())
    has_high = any(f.sodium > LOW_SODIUM_MAX for foods in result.values() for f in foods)
    assert has_high  # 제한이 없으므로 고나트륨 음식이 존재해야 정상


def test_low_sodium_relax_disables_filter_csv():
    """relax(재검색) 시에는 저염 필터를 완화해 후보 폭을 넓히는지"""
    from app.services.food_retriever import LOW_SODIUM_MAX

    cond = UserConditions(nutrition_goals=["저염"])
    result = retrieve_foods(cond, UserProfile(), foods=load_foods(), relax=True)
    has_high = any(f.sodium > LOW_SODIUM_MAX for foods in result.values() for f in foods)
    assert has_high  # relax면 상한 초과도 다시 허용


def test_build_search_query_semantic_only():
    """검색문에 의미 조건만 담기고 숫자/제외는 안 담기는지"""
    cond = UserConditions(
        target_kcal=400,
        preferences=["얼큰한"],
        nutrition_goals=["저염"],
        exclude_foods=["계란"],
        meal_style="한그릇",
    )
    q = build_search_query(cond)
    assert "얼큰한" in q and "저염" in q and "한그릇" in q
    assert "400" not in q and "계란" not in q  # 사실 축은 검색문에 안 들어감


def test_build_search_query_default():
    """의미 조건이 하나도 없으면 기본 검색문"""
    q = build_search_query(UserConditions())
    assert q  # 빈 문자열이 아니어야 함


def test_supabase_path_mocked(monkeypatch):
    """Supabase 경로: embedding/RPC를 mock해 역할별 dict 변환·파라미터를 검증."""
    captured = {}

    def fake_embed_query(text):
        captured.setdefault("query_texts", []).append(text)
        return [0.0] * 4096

    fake_row = {
        "food_id": 1,
        "food_name": "김치찌개",
        "meal_role": "국물",
        "serving_size": 300.0,
        "kcal": 250.0,
        "carbohydrate": 10.0,
        "protein": 12.0,
        "fat": 8.0,
        "sugar": 2.0,
        "sodium": 700.0,
    }

    class FakeRPC:
        def __init__(self, params):
            captured.setdefault("calls", []).append(params)

        def execute(self):
            role = captured["calls"][-1]["role_filter"][0]
            # 국물 역할일 때만 결과 반환
            return type("R", (), {"data": [dict(fake_row)] if role == "국물" else []})()

    class FakeClient:
        def rpc(self, name, params):
            assert name == "match_foods"
            return FakeRPC(params)

    monkeypatch.setattr("app.services.embedding_service.embed_query", fake_embed_query)
    monkeypatch.setattr("app.services.supabase_client.get_client", lambda: FakeClient())

    cond = UserConditions(preferences=["얼큰한"], exclude_foods=["계란"])
    result = food_retriever.retrieve_foods(cond, UserProfile(allergies=["우유"]))

    # 역할별로 RPC 호출됨 (4개 역할)
    assert len(captured["calls"]) == 4
    # 맛 조건이 검색문에 반영됨 (임베딩된 텍스트 중 하나에 "얼큰한" 포함)
    assert any("얼큰한" in t for t in captured["query_texts"])
    # 밥은 맛 노이즈 제거를 위해 중립 쿼리로 검색됨 (별도 임베딩 존재)
    assert "밥" in captured["query_texts"]
    # 제외어(알레르기+exclude)가 RPC 파라미터에 합쳐져 전달
    assert set(captured["calls"][0]["excluded_terms"]) == {"우유", "계란"}
    # 결과가 FoodItem으로 변환되어 역할별 dict에 담김
    assert result["국물"][0].food_name == "김치찌개"

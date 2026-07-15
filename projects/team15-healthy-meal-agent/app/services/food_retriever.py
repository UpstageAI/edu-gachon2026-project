"""
app/services/food_retriever.py
음식 후보 검색.

검색은 두 축으로 나뉜다(docs/08):
  - 의미 축: 사용자 표현("얼큰한", "담백한")을 임베딩 유사도로 검색 (Supabase pgvector).
  - 사실 축: kcal 상한·나트륨·알레르기/제외어는 SQL 필터(RPC 파라미터)로 처리.

기존의 PREFERENCE_KEYWORDS 하드코딩 매핑은 제거했다.
Supabase가 없거나 실패하면 CSV 전량을 fallback 후보로 반환한다(테스트/오프라인).

retrieve_foods의 시그니처·반환형(역할별 dict)은 유지 → LangGraph retrieve 노드 무변경.
"""

from pathlib import Path

import pandas as pd

from app.schemas import FoodItem

CSV_PATH = Path(__file__).resolve().parent.parent / "data" / "foods_samsam.csv"

# 한 끼 구성에 쓰는 역할만 검색 (간식·기타는 후보에서 제외)
ROLES = ["밥", "국물", "반찬", "한그릇"]
PER_ROLE = 20  # 역할별로 가져올 후보 수

# 맛 키워드("칼칼한")를 의미검색에 쓰지 않는 역할.
# 밥은 맛이 아니라 '탄수화물 담당'이라 맛 벡터를 적용하면 노이즈만 된다(유사도 0.25 수준).
# → 밥은 중립 쿼리로 검색해 어울리는 기본 밥류를 뽑는다.
_FLAVOR_NEUTRAL_ROLES = {"밥"}
_NEUTRAL_QUERY = "밥"

# 저염("저염" nutrition_goal) 요청 시 개별 음식에 적용할 나트륨 상한(mg).
# 한 끼 총합 KDRI 기준은 767mg/끼(validator와 동일). 한 끼가 밥+국+반찬으로 나뉘므로
# 개별 음식엔 보수적 상한을 둬 젓갈·장아찌 등 고나트륨 음식을 사실 축에서 배제한다.
LOW_SODIUM_MAX = 400.0

# 디저트·빵·후식류: 한 끼 메인/반찬으로는 부적절하므로 추천 후보에서 제외한다.
# ('간식/기타' 역할은 애초에 ROLES에 없어 빠지지만, 한그릇·반찬에 섞인 것도 걸러낸다.)
_DESSERT_KEYWORDS = (
    "빵",
    "케익",
    "케이크",
    "파르페",
    "샌드위치",
    "쿠키",
    "머핀",
    "타르트",
    "파이",
    "스콘",
    "와플",
    "도넛",
    "화채",
    "무스",
    "마카롱",
    "카스텔라",
    "스무디",
    "파운드",
    "찰빵",
    "공갈빵",
    "식빵",
    "펀치",
)


def is_dessert(food_name: str) -> bool:
    """이름에 디저트/빵 키워드가 있으면 True (한 끼 후보에서 제외 대상)."""
    return any(k in food_name for k in _DESSERT_KEYWORDS)


def contains_excluded(food: FoodItem, excluded: list[str]) -> bool:
    """알레르기·제외 재료/음식이 후보에 들어있는지 — 이름뿐 아니라 '재료'까지 검사한다.

    제외어가 이름/재료에 들어있으면 제외한다. 이름만 보면 '양배추감자전'(반죽에 계란)처럼
    안 드러난 알레르겐을 놓쳐, ingredients 원문도 함께 본다.

    설계 원칙("판단은 LLM, 실행은 코드"): '무엇을 뺄지'는 extractor(LLM)가 판단한다.
    "부대된장찌개 말고 다른 된장찌개" 같은 요청은 LLM이 exclude=["부대"], wanted=["된장찌개"]로
    뽑아주므로, 코드는 그 결과를 단순 부분일치로 실행만 한다("부대"가 "맑은부대찌개"에 포함 → 제외).
    """
    haystack = f"{food.food_name} {food.ingredients or ''}"
    return any(x and x in haystack for x in excluded)


# '밥' 역할로 분류돼 있지만 실제로는 그 자체로 완성된 한 그릇인 것들.
# (볶음밥·덮밥·죽·김밥·초밥·주먹밥·리조또·카레·쌈밥·버거 등)
# 백반의 '밥' 자리에 들어가면 국·반찬이 덧붙어 과해지므로 '한그릇' 역할로 재분류한다.
_COMPLETE_RICE_KEYWORDS = (
    "볶음밥",
    "덮밥",
    "비빔밥",
    "리조또",
    "리소토",
    "롤",
    "볼 밥",
    "볼밥",
    "주먹밥",
    "쌈밥",
    "컵밥",
    "카레",
    "필라프",
    "파에야",
    "죽",
    "김밥",
    "초밥",
    "스시",
    "핫도그",
    "약식",
    "유부",
    "오므라이스",
    "크로켓",
    "버거",
    "밥스틱",
    "그라탕",
    "미음",
    "무른밥",
    "튀밥",
    "범벅",
    "강정",
)


def effective_role(food_name: str, raw_role: str) -> str:
    """데이터의 원래 역할을 실제 식사 구성에 맞게 보정한다.

    핵심: '밥' 역할이지만 볶음밥·덮밥처럼 완성된 한 그릇이면 '한그릇'으로 바꾼다.
    (원본 데이터의 역할 분류가 부정확한 것을 런타임에서 교정 — 파일은 안 건드림)
    """
    if raw_role == "밥" and any(k in food_name for k in _COMPLETE_RICE_KEYWORDS):
        return "한그릇"
    return raw_role


# 구체적 음식명이 아니라 '분류어'라서 wanted_foods로 강제 포함하면 안 되는 말들.
# (LLM이 "국이랑 밥 있는 한식"에서 "국","밥"을 음식명으로 오인하는 것 방어)
_GENERIC_FOOD_WORDS = {
    "국",
    "밥",
    "반찬",
    "찌개",
    "면",
    "국물",
    "한식",
    "한상",
    "한정식",
    "죽",
    "탕",
}


def match_wanted_foods(
    wanted: list[str], foods: list["FoodItem"], excluded: list[str] | None = None
) -> tuple[dict, list[str]]:
    """
    사용자가 원한 음식명(여러 개 가능)을 DB 음식과 부분일치로 매칭한다.
    반환: ({원문: 매칭된 FoodItem}, [DB에 없는 원문들])

    예) "김치찌개" → "닭고기김치찌개" 매칭. "존재안함" → 미매칭 목록에 담김.
    한 원문에 여러 후보가 걸리면 이름이 가장 짧은(=가장 대표적인) 것을 고른다.
    '국/밥' 같은 분류어는 특정 음식이 아니므로 매칭/미매칭 어디에도 넣지 않고 무시한다.

    excluded: 제외 음식/재료. "된장찌개 원하지만 부대된장찌개는 말고"처럼, 원한 음식 계열
    안에서도 제외 대상은 강제 포함 후보에서 뺀다(멀티턴 '다른 걸로'에 필수).
    """
    excluded = [x for x in (excluded or []) if x]
    matched: dict[str, FoodItem] = {}
    missing: list[str] = []
    for term in wanted:
        key = term.replace(" ", "")
        if key in _GENERIC_FOOD_WORDS:  # 분류어는 무시(강제 포함도, '없다' 안내도 안 함)
            continue
        hits = [f for f in foods if key in f.food_name.replace(" ", "")]
        # 디저트는 한 끼 요청 매칭 대상에서 제외
        hits = [f for f in hits if not is_dessert(f.food_name)]
        # 제외 대상은 강제 포함 후보에서 뺀다("부대된장찌개 말고 다른 된장찌개")
        if excluded:
            hits = [f for f in hits if not contains_excluded(f, excluded)]
        if hits:
            matched[term] = min(hits, key=lambda f: len(f.food_name))
        else:
            missing.append(term)
    return matched, missing


def _wants_low_sodium(conditions) -> bool:
    """LLM/폴백이 정규화한 nutrition_goals에 '저염' 태그가 있는지."""
    return "저염" in (conditions.nutrition_goals or [])


def _search_max_kcal(conditions, relax: bool):
    """1차 검색의 kcal 상한. target('정도') 모드면 여유(+tolerance)를 둬 밥류가
    초과로 원천 필터링되는 것을 막는다. upper('이하')는 여유 없이 그대로(안전축).
    relax(재검색) 시에는 상한 없음.
    """
    from app.services.validator import TARGET_KCAL_TOLERANCE

    if not conditions.target_kcal or relax:
        return None
    if conditions.kcal_mode == "target":
        return conditions.target_kcal * (1 + TARGET_KCAL_TOLERANCE)
    return conditions.target_kcal  # upper 또는 mode 미상은 그대로


_FOODS_CACHE: list[FoodItem] | None = None


def _opt_float(value) -> float | None:
    """빈값·NaN·결측 → None, 그 외 → float. serving_size/sugar 결측 방어."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "" or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_json_list(value) -> list[str]:
    """recipe_steps/images → list[str].

    두 경로를 모두 받는다:
      - Supabase jsonb 컬럼 → supabase-py가 이미 list로 역직렬화해서 줌.
      - CSV 문자열 → JSON 배열 문자열.
    실패 시 빈 리스트.
    """
    import json

    if value is None:
        return []
    # jsonb 컬럼은 이미 파이썬 list로 온다
    if isinstance(value, list):
        return [str(x) for x in value]
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return []
    try:
        parsed = json.loads(s)
        return [str(x) for x in parsed] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def _str_or_empty(value) -> str:
    s = str(value).strip() if value is not None else ""
    return "" if s.lower() == "nan" else s


def load_foods() -> list[FoodItem]:
    """CSV(foods_samsam) → FoodItem 리스트 (한 번 읽고 캐시). Supabase fallback·테스트용."""
    global _FOODS_CACHE
    if _FOODS_CACHE is not None:
        return _FOODS_CACHE

    df = pd.read_csv(CSV_PATH)
    if "food_id" not in df.columns:
        df["food_id"] = df.index + 1
    # 삼삼한밥상 전용 컬럼이 없는 CSV(구 데이터)도 로드되도록 기본값 보강
    for col in ("recipe_steps", "recipe_images", "ingredients", "na_tip"):
        if col not in df.columns:
            df[col] = ""

    foods = [
        FoodItem(
            food_id=int(row["food_id"]),
            food_name=str(row["food_name"]),
            meal_role=effective_role(str(row["food_name"]), str(row["meal_role"])),
            serving_size=_opt_float(row["serving_size"]),
            kcal=float(row["kcal"]),
            carbohydrate=float(row["carbohydrate"]),
            protein=float(row["protein"]),
            fat=float(row["fat"]),
            sugar=_opt_float(row["sugar"]),
            sodium=float(row["sodium"]),
            recipe_steps=_parse_json_list(row["recipe_steps"]),
            recipe_images=_parse_json_list(row["recipe_images"]),
            ingredients=_str_or_empty(row["ingredients"]),
            na_tip=_str_or_empty(row["na_tip"]),
        )
        for _, row in df.iterrows()
    ]
    _FOODS_CACHE = foods
    return foods


def build_search_query(conditions) -> str:
    """조건에서 '의미 축' 검색문을 만든다. 숫자/제외는 넣지 않는다(사실 축은 SQL)."""
    parts: list[str] = []
    parts.extend(conditions.preferences or [])
    parts.extend(conditions.nutrition_goals or [])
    parts.extend(conditions.wanted_foods or [])
    if conditions.meal_style:
        parts.append(conditions.meal_style)
    query = " ".join(p for p in parts if p).strip()
    # 아무 의미 조건도 없으면 일반적인 검색문으로 (전 음식과 고루 가까움)
    return query or "건강한 한 끼 식사"


def _row_to_food(r: dict) -> FoodItem:
    return FoodItem(
        food_id=int(r["food_id"]),
        food_name=str(r["food_name"]),
        meal_role=effective_role(str(r["food_name"]), str(r["meal_role"])),
        serving_size=_opt_float(r.get("serving_size")),
        kcal=float(r["kcal"]),
        carbohydrate=float(r["carbohydrate"]),
        protein=float(r["protein"]),
        fat=float(r["fat"]),
        sugar=_opt_float(r.get("sugar")),
        sodium=float(r["sodium"]),
        recipe_steps=_parse_json_list(r.get("recipe_steps")),
        recipe_images=_parse_json_list(r.get("recipe_images")),
        ingredients=_str_or_empty(r.get("ingredients")),
        na_tip=_str_or_empty(r.get("na_tip")),
    )


def _retrieve_supabase(conditions, profile, relax: bool) -> dict:
    """Supabase pgvector 의미검색. 역할별로 match_foods RPC를 호출해 dict 구성."""
    from app.services.embedding_service import embed_query
    from app.services.supabase_client import get_client

    client = get_client()
    query_vec = embed_query(build_search_query(conditions))
    # 밥처럼 맛과 무관한 역할은 중립 쿼리 벡터로 검색(맛 노이즈 제거). 필요할 때만 임베딩.
    neutral_vec = embed_query(_NEUTRAL_QUERY) if _FLAVOR_NEUTRAL_ROLES else query_vec

    excluded = [x for x in (list(profile.allergies) + list(conditions.exclude_foods)) if x]
    max_kcal = _search_max_kcal(conditions, relax)
    # 저염 요청이면 나트륨 상한을 사실 축(DB 필터)으로 전달. relax(재검색) 시에는 완화.
    max_sodium = LOW_SODIUM_MAX if (_wants_low_sodium(conditions) and not relax) else None

    result: dict[str, list[FoodItem]] = {role: [] for role in ROLES}
    for role in ROLES:
        role_vec = neutral_vec if role in _FLAVOR_NEUTRAL_ROLES else query_vec
        params = {
            "query_embedding": role_vec,
            "match_count": PER_ROLE,
            "role_filter": [role],
            "excluded_terms": excluded,
        }
        if max_kcal is not None:
            params["max_kcal"] = max_kcal
        if max_sodium is not None:
            params["max_sodium"] = max_sodium
        rows = client.rpc("match_foods", params).execute().data or []
        for r in rows:
            name = str(r["food_name"])
            if is_dessert(name):  # 디저트/빵류 제외
                continue
            food = _row_to_food(r)
            # 알레르기·제외 재료를 '재료'까지 검사해 한 번 더 거른다(SQL은 이름만 봄).
            # 이름에 안 드러난 알레르겐('양배추감자전' 반죽의 계란 등)을 확실히 차단.
            if contains_excluded(food, excluded):
                continue
            # 완성밥요리는 '밥'으로 검색됐어도 실제 역할(한그릇) 버킷에 담는다
            if food.meal_role in result:
                result[food.meal_role].append(food)
    return result


def _retrieve_csv(conditions, profile, foods, relax: bool) -> dict:
    """Supabase 불가 시 fallback: CSV 전량에서 사실 축 필터만 적용(의미검색 없음)."""
    if foods is None:
        foods = load_foods()
    excluded = [x for x in (list(profile.allergies) + list(conditions.exclude_foods)) if x]
    max_kcal = _search_max_kcal(conditions, relax)
    max_sodium = LOW_SODIUM_MAX if (_wants_low_sodium(conditions) and not relax) else None

    result: dict[str, list[FoodItem]] = {role: [] for role in ROLES}
    for food in foods:
        if food.meal_role not in ROLES:  # 기타 제외
            continue
        if is_dessert(food.food_name):  # 디저트/빵류 제외
            continue
        if contains_excluded(food, excluded):  # 알레르기·제외 재료(이름+재료) 제외
            continue
        if max_kcal and food.kcal > max_kcal:
            continue
        if max_sodium is not None and food.sodium > max_sodium:
            continue
        result[food.meal_role].append(food)
    return result


def retrieve_foods(conditions, profile, foods=None, relax=False) -> dict:
    """역할별 후보 반환: {"밥":[], "국물":[], "반찬":[], "한그릇":[]}.

    기본은 Supabase 의미검색. foods를 명시하거나 Supabase 실패 시 CSV fallback.
    """
    if foods is not None:  # 테스트에서 후보를 직접 주입한 경우
        return _retrieve_csv(conditions, profile, foods, relax)
    try:
        return _retrieve_supabase(conditions, profile, relax)
    except Exception as e:
        print(f"[retrieve Supabase 실패 → CSV fallback] {str(e)[:80]}")
        return _retrieve_csv(conditions, profile, None, relax)

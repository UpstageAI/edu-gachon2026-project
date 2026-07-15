"""
app/services/nutrition_lookup.py
영양 조회(nutrition_query) 처리. "김치찌개 나트륨 얼마야?" 같은 요청에 답한다.

"판단은 LLM, 사실은 코드":
  - 어떤 음식을 묻는지 이름 추출은 단순 매칭(필요 시 LLM 확장 가능).
  - 실제 영양 수치는 반드시 DB(CSV)의 값을 그대로 쓴다. LLM이 숫자를 지어내지 않는다.
"""

from app.schemas import FoodItem
from app.services.food_retriever import load_foods

MIN_CANDIDATE_LEN = 2  # 이보다 짧은 조각은 너무 흔해서(예: 한 글자) 후보로 안 쓴다.
MAX_CANDIDATES = 5

# 음식명이 아닌 질문 표현. 문장 전체를 후보 탐색에 쓰면 이 단어들의 조각이
# 무관한 음식명과 우연히 겹칠 수 있다(예: "칼로리얼마야"의 "리얼"이 "씨리얼"과 매칭).
# 길이 내림차순으로 제거해야 "얼마나"를 통째로 지우고 "나"만 남기는 식으로 처리된다.
QUERY_STOPWORDS = sorted(
    [
        "칼로리",
        "나트륨",
        "단백질",
        "탄수화물",
        "당류",
        "지방",
        "얼마나요",
        "얼마나",
        "얼마예요",
        "얼마인가요",
        "얼마야",
        "얼마",
        "몇인가요",
        "몇이야",
        "몇칼로리",
        "몇",
        "알려줘",
        "알려주세요",
        "궁금해요",
        "궁금해",
        "궁금합니다",
        "뭐예요",
        "뭔가요",
        "뭐야",
    ],
    key=len,
    reverse=True,
)


def _find_food(user_message: str, foods: list[FoodItem]) -> FoodItem | None:
    """문장에 음식명이 포함돼 있으면 가장 길게(구체적으로) 매칭되는 음식을 찾는다."""
    text = user_message.replace(" ", "")
    matches = [f for f in foods if f.food_name.replace(" ", "") in text]
    if not matches:
        return None
    # 이름이 가장 긴 것 = 가장 구체적인 매칭 (예: "된장찌개"가 "된장"보다 우선)
    return max(matches, key=lambda f: len(f.food_name))


def _strip_query_words(text: str) -> str:
    """영양 속성명·질문 표현을 지워 음식명으로 보이는 부분만 남긴다."""
    for word in QUERY_STOPWORDS:
        text = text.replace(word, "")
    return text.strip("?!., ")


def _find_candidates(user_message: str, foods: list[FoodItem]) -> list[FoodItem]:
    """정확히 일치하는 음식이 없을 때, 반대 방향(사용자가 말한 부분 문자열이
    DB 음식명 안에 포함되는지)으로 후보를 찾는다.
    예: "김치찌개"만 물었는데 DB엔 "닭고기김치찌개" 등 변형만 있는 경우 —
    가장 긴(구체적인) 부분 문자열에서 매칭이 나오는 즉시 그 결과를 쓴다.
    질문 표현을 먼저 지워서, 남은 음식명 부분만 탐색 대상이 되게 한다
    (그래야 "밥 칼로리 얼마야?"처럼 음식명 자체가 짧아도 정상 탐색된다).
    """
    text = _strip_query_words(user_message.replace(" ", ""))
    if not text:
        return []
    lower_bound = min(MIN_CANDIDATE_LEN, len(text))
    for length in range(len(text), lower_bound - 1, -1):
        found: list[FoodItem] = []
        seen_names: set[str] = set()
        for start in range(len(text) - length + 1):
            token = text[start : start + length]
            for f in foods:
                name = f.food_name.replace(" ", "")
                if token in name and name not in seen_names:
                    seen_names.add(name)
                    found.append(f)
        if found:
            return found[:MAX_CANDIDATES]
    return []


def answer_nutrition_query(user_message: str, foods: list[FoodItem] | None = None) -> str:
    """영양 조회 응답 문자열을 만든다. 수치는 전부 DB 실제값."""
    if foods is None:
        foods = load_foods()

    food = _find_food(user_message, foods)
    if food is None:
        candidates = _find_candidates(user_message, foods)
        if candidates:
            options = "\n".join(f"  · {c.food_name}" for c in candidates)
            return (
                "정확히 일치하는 음식을 찾지 못했어요. 혹시 이 중 하나인가요?\n"
                f"{options}\n"
                "정확한 이름으로 다시 물어봐 주세요."
            )
        return (
            "어떤 음식의 영양 정보를 알려드릴까요? "
            "저희 DB에 있는 음식명을 정확히 말씀해 주시면 실제 성분값으로 답해드려요."
        )

    # serving_size·sugar는 삼삼한밥상에서 결측일 수 있어 None 가드
    serving = f"1인분({food.serving_size:.0f}g)" if food.serving_size is not None else "1인분"
    macro = f"  · 탄수화물 {food.carbohydrate:.0f}g / 단백질 {food.protein:.0f}g / 지방 {food.fat:.0f}g\n"
    sugar_part = f"당류 {food.sugar:.0f}g / " if food.sugar is not None else ""
    return (
        f"[{food.food_name}] {serving} 기준\n"
        f"  · 칼로리 {food.kcal:.0f}kcal\n"
        f"{macro}"
        f"  · {sugar_part}나트륨 {food.sodium:.0f}mg\n"
        f"(식약처 통합식품영양성분 DB 기준)"
    )

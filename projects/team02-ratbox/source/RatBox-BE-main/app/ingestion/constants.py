import uuid

import pandas as pd

INGREDIENT_SYNONYMS = {
    "계란": ["달걀", "왕란", "계란(달걀)"],
    "밥": ["쌀밥", "흰쌀밥"],
    "돼지고기": ["삼겹살", "돈육", "돼지肉"],
    "소금": ["천일염", "소금(천일염)"],
    "참기름": ["깨기름"],
    "고추": ["건고추", "고추(말린)"],
    "파": ["대파", "쪽파"],
    "마늘": ["다진마늘"],
    "양파": ["양파(다진)", "다진양파"],
}

SYNONYM_TO_STANDARD = {}
for _standard, _synonyms in INGREDIENT_SYNONYMS.items():
    SYNONYM_TO_STANDARD[_standard] = _standard
    for _syn in _synonyms:
        SYNONYM_TO_STANDARD[_syn] = _standard

INGREDIENT_CATEGORIES = {
    "육류": ["계란", "돼지고기", "소고기", "닭고기", "생선"],
    "채소": ["대파", "양파", "마늘", "고추", "당근", "브로콜리"],
    "양념": ["소금", "설탕", "간장", "참기름", "고추장"],
    "곡류": ["밥", "밀가루", "쌀"],
    "유제품": ["우유", "치즈", "버터"],
}

INGREDIENT_CATEGORY_NAMES = [*INGREDIENT_CATEGORIES.keys(), "기타"]

# 브랜드명/복합재료 표기 등 표준 재료명으로 부적절하다고 판단해 제외하기로 한 항목.
EXCLUDED_INGREDIENT_NAMES = {
    "S&B테이스티 하야시라이스큐브",
    "오돌뼈볶음 & 주먹밥 밀키트",
    "양파 채수 큐브+물",
    "닭고기 육수 큐브+ 물",
    "소고기 육수 큐브+물",
    "소고기 육수 큐브+ 물",
    "닭고기 육수 큐브+물",
    "소고기 육수+물",
    "무염버터:",
    "설탕:",
    "달걀:",
    "우유:",
    "돼지고기 목살+삼겹살",
    "蔥燒福利麵館牛肉湯麵",
    "美味堂麻辣鴨血",
    "적赤용과",
    "소금+설탕",
}


def get_ingredient_category(ingredient_name: str) -> str:
    for category, items in INGREDIENT_CATEGORIES.items():
        if ingredient_name in items:
            return category
    return "기타"


def build_ingredient_category_master() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "id": [str(uuid.uuid4()) for _ in INGREDIENT_CATEGORY_NAMES],
            "name": INGREDIENT_CATEGORY_NAMES,
        }
    )

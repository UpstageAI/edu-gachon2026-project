DB_SCHEMA_CONTEXT = """다음 4개 테이블만 조회할 수 있다:

- recipes(id uuid, name text, cooking_time integer, difficulty text, servings integer,
  category text, cooking_method text)
- recipe_ingredients(recipe_id uuid, ingredient_id uuid, amount numeric, unit text,
  is_required boolean)
- ingredients_master(id uuid, name text, category_id uuid, allergen_id uuid)
- ingredients_category(id uuid, name text)

규칙:
- SELECT 문만 작성한다. INSERT/UPDATE/DELETE/DDL은 절대 쓰지 않는다.
- 위 4개 테이블 외에는 참조하지 않는다.
- 재료명은 항상 ingredients_master.name과 정확히 일치하는 문자열로 매칭한다.
- 문자열 리터럴은 안전하게 작성하고, 세미콜론으로 여러 문장을 이어 쓰지 않는다.
- 후보를 넉넉히(최대 20개) 가져와야 이후 단계에서 부족 재료 개수로 다시 정렬할 수 있으니
  LIMIT 20을 반드시 붙인다."""

EXACT_STRATEGY_INSTRUCTION = """아래 보유 재료와 하나라도 겹치는 레시피를 찾는 단일 SELECT문을
작성하라.
- 보유 재료: {ingredients}

예시 (보유 재료 ["계란", "밥"]):
SELECT DISTINCT r.id, r.name, r.cooking_time
FROM recipes r
JOIN recipe_ingredients ri ON ri.recipe_id = r.id
JOIN ingredients_master im ON im.id = ri.ingredient_id
WHERE im.name IN ('계란', '밥')
LIMIT 20;"""

RELAXED_STRATEGY_INSTRUCTION = """이전에 아래 보유 재료로 정확 매칭 검색을 했는데 0건이 나왔다.
이번엔 조건을 완화해서 다시 찾아야 한다.
- 보유 재료: {ingredients}

완화 방법(둘 중 상황에 맞는 쪽을 골라 적용하라):
- 보유 재료명이 ingredients_master.name과 정확히 일치하지 않을 수 있으니, ingredients_master를
  ingredients_category와 조인해 보유 재료와 같은 카테고리인 재료(예: "대파" 대신 "쪽파"도
  category_id가 '파류' 카테고리)도 포함해 넓게 매칭한다.
- 그래도 너무 좁으면 recipe_ingredients.is_required = false인 재료는 매칭 조건에서 아예 제외하고,
  나머지 필수 재료만으로 다시 매칭한다.

예시 (보유 재료 ["양파"], ingredients_master에 같은 카테고리('뿌리채소')인 재료가
여러 개일 때):
SELECT DISTINCT r.id, r.name, r.cooking_time
FROM recipes r
JOIN recipe_ingredients ri ON ri.recipe_id = r.id
JOIN ingredients_master im ON im.id = ri.ingredient_id
WHERE im.category_id = (
    SELECT category_id FROM ingredients_master WHERE name = '양파'
)
LIMIT 20;"""

STRATEGY_INSTRUCTIONS = {
    "exact": EXACT_STRATEGY_INSTRUCTION,
    "relaxed": RELAXED_STRATEGY_INSTRUCTION,
}


def build_generate_sql_prompt(ingredients: list[str], strategy: str) -> str:
    instruction = STRATEGY_INSTRUCTIONS[strategy].format(ingredients=ingredients)
    return f"{DB_SCHEMA_CONTEXT}\n\n{instruction}\n\nSQL 문 하나만 출력하라."

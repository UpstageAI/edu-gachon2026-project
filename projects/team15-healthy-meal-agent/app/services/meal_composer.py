"""
app/services/meal_composer.py
후보 안에서만 식단 조합. 규칙 기반(LLM 아님).

생성-검증 루프(2026-07-14 개선):
  이전에는 밥+국+반찬2를 무작정 담아 합계 칼로리를 안 봐서 "400 이하 요청에 740kcal 백반"
  같은 초과 조합이 나왔다. 이제는 여러 조합 후보를 생성한 뒤, 우리가 정의한 건강 기준
  (칼로리·나트륨·탄단지, docs/건강식_기준_재정의_v4)으로 채점해 가장 좋은 조합을 고른다.
  즉 검증 기준을 "채점"만이 아니라 "생성 기준"으로 끌어올렸다.

조합 형태:
  - 한그릇: 한그릇 1개 (+ 목표 미달 시 반찬 곁들임)
  - 백반: 밥1 + (국0~1) + (반찬0~2)  → 밥+α 조합을 여러 개 만들어 최적 선택
재시도(seed)마다 동점 조합 중 다른 것을 고른다.
"""

import random

from app.schemas import FoodItem, MealPlan, NutritionTotal, UserConditions
from app.services.validator import TARGET_KCAL_TOLERANCE, macro_deviation

MAIN_MIN_RATIO = 0.75  # 목표 칼로리의 이 비율 미만이면 한그릇/조합이 부실 (validator 하한과 동일)
SODIUM_SOFT_MAX = 1500  # 이 값 초과 조합은 validator에서 FAIL → 후보 채점에서 강한 감점
_CANDIDATE_POOL = 6  # 각 역할에서 조합 생성에 쓸 상위 후보 수(너무 많으면 조합 폭발)
HIGH_PROTEIN_TARGET = 20  # 고단백 목표 시 지향하는 단백질 에너지비율(%). 이 미만이면 벌점
JUDGE_TOP_N = 4  # LLM Judge에 넘길 규칙 상위 후보 수(자연스러움으로 재랭킹)

# 양념 다양성: 같은 양념이 여러 음식에 겹치면 단조로운 한 끼(예: 된장찌개+된장무침+된장소스).
# 음식명에서 대표 양념을 감지해, 2개 이상 겹칠 때마다 벌점을 준다.
# 단, 사용자가 콕 집어 요청한 음식(된장찌개 등)은 존중하되 '반복'만 억제한다.
_SEASONING_KEYWORDS = ("된장", "고추장", "간장", "카레", "마라", "김치", "청국장", "굴소스")
_SEASONING_DUP_PENALTY = 60  # 같은 양념이 겹칠 때마다 더하는 벌점(중간 강도)


def compose_meal(
    candidates: dict,
    conditions: UserConditions,
    meal_type: str = None,
    seed: int = None,
    must_include: list[FoodItem] = None,
) -> MealPlan:
    """
    candidates: retrieve_foods 결과 (역할별 dict)
    meal_type: "한그릇" or "백반" (None이면 자동 결정)
    seed: 재시도 시 다른 조합을 뽑기 위한 시드
    must_include: 사용자가 콕 집은 음식(wanted_foods 매칭). 모든 조합에 반드시 포함한다.

    여러 조합 후보를 생성→건강 기준으로 채점→최적 조합을 MealPlan으로 반환.
    통과 조합이 하나도 없으면 그중 '가장 덜 나쁜' 조합을 반환한다(최종 판정은 validator가 함).
    """
    rng = random.Random(seed)
    forced = list(must_include or [])

    # 형태 결정: 사용자가 명시하면 그것만, 아니면 한그릇·백반 둘 다 만들어 제일 건강한 걸 고른다.
    if meal_type in ("백반", "한그릇"):
        types = [meal_type]
    elif conditions.meal_style in ("백반", "한그릇"):
        types = [conditions.meal_style]
    else:
        types = ["한그릇", "백반"]

    # (형태, 조합) 후보를 모아 전체에서 최적 선택 — 생성-검증 루프가 형태까지 아우름
    scored: list[tuple[float, str, list[FoodItem]]] = []
    for t in types:
        for items in _generate_combos(candidates, conditions, t, rng):
            combo = _with_forced(items, forced)
            scored.append((_score(combo, conditions), t, combo))

    if not scored:
        # 후보 조합이 없어도 요청 음식은 최소한 보여준다
        fallback_type = types[0]
        return MealPlan(
            meal_type=fallback_type, items=forced, reason=_reason(fallback_type, conditions)
        )

    # 규칙 점수 상위 후보들을 뽑아, LLM Judge로 '한 끼 자연스러움'까지 반영해 최종 선택.
    # Judge가 상위 후보 전부를 '한 끼로 부적절'하다고 하면, 그 다음 순위 묶음으로 한 번 더 시도.
    top = _top_distinct(scored, JUDGE_TOP_N)
    best_type, best_items, judged_ok = _select_best(top, conditions)
    if not judged_ok:
        # 상위 묶음이 전부 어색 → 그 다음 상위 후보들로 재시도(같은 후보 제외)
        used = {tuple(sorted(f.food_id for f in items)) for _, items in top}
        remaining = [s for s in scored if tuple(sorted(f.food_id for f in s[2])) not in used]
        if remaining:
            top2 = _top_distinct(remaining, JUDGE_TOP_N)
            best_type, best_items, _ = _select_best(top2, conditions)
    return MealPlan(meal_type=best_type, items=best_items, reason=_reason(best_type, conditions))


def _top_distinct(
    scored: list[tuple[float, str, list[FoodItem]]], n: int
) -> list[tuple[str, list[FoodItem]]]:
    """규칙 점수 낮은 순으로, 음식 구성이 서로 다른 상위 n개 조합을 뽑는다."""
    out: list[tuple[str, list[FoodItem]]] = []
    seen: set[tuple[int, ...]] = set()
    for _, t, items in sorted(scored, key=lambda x: x[0]):
        key = tuple(sorted(f.food_id for f in items))
        if key in seen:
            continue
        seen.add(key)
        out.append((t, items))
        if len(out) >= n:
            break
    return out


def _select_best(
    top: list[tuple[str, list[FoodItem]]], conditions: UserConditions
) -> tuple[str, list[FoodItem], bool]:
    """상위 후보 중 최종 1개 선택.

    반환: (형태, 음식들, judged_ok).
    judged_ok=False면 LLM이 '이 후보들은 한 끼로 다 어색하다'고 판정한 것 →
    호출부가 다음 순위 후보로 재시도한다.
    LLM Judge 실패 시 규칙 1등 + judged_ok=True(무중단).
    """
    if len(top) <= 1:
        return top[0][0], top[0][1], True
    try:
        from app.services.meal_judge import judge_coherence

        result = judge_coherence([items for _, items in top], conditions)
        t, items = top[result.choice]
        if not result.acceptable:
            print(f"[조합 Judge 거부] {' + '.join(f.food_name for f in items)} — {result.reason}")
        return t, items, result.acceptable
    except Exception as e:
        print(f"[조합 Judge 실패 → 규칙 1등 사용] {str(e)[:80]}")
        return top[0][0], top[0][1], True


def _with_forced(items: list[FoodItem], forced: list[FoodItem]) -> list[FoodItem]:
    """강제 포함 음식을 조합 맨 앞에 넣되, 중복·역할 겹침을 막는다.

    - food_id 중복 제거.
    - forced에 '메인'(한그릇/밥)이 있으면, 조합의 다른 메인은 뺀다.
      (예: '비빔밥'을 강제 포함했는데 함박볼밥까지 붙어 밥요리 2개가 되는 것 방지)
    """
    if not forced:
        return items
    seen = {f.food_id for f in forced}
    forced_has_main = any(f.meal_role in ("한그릇", "밥") for f in forced)
    out = list(forced)
    for x in items:
        if x.food_id in seen:
            continue
        if forced_has_main and x.meal_role in ("한그릇", "밥"):
            continue  # 메인 중복 방지 (곁들임 반찬·국만 추가)
        out.append(x)
    return out


def _generate_combos(
    candidates: dict, conditions: UserConditions, meal_type: str, rng: random.Random
) -> list[list[FoodItem]]:
    """식사 형태에 맞는 여러 조합 후보(밥+α 등)를 생성한다."""
    combos: list[list[FoodItem]] = []

    if meal_type == "한그릇":
        pool = candidates.get("한그릇", [])[:_CANDIDATE_POOL]
        sides = candidates.get("반찬", [])[:_CANDIDATE_POOL]
        for main in pool:
            combos.append([main])  # 단독
            for side in sides:  # 곁들임 1개
                combos.append([main, side])
    else:  # 백반: 밥 + 국(0~1) + 반찬(0~2)
        # 밥은 맛 검색을 안 해(중립 벡터) 항상 같은 순서로 온다. 그대로 상위 6개만 쓰면
        # 저칼로리 밥(무현미밥 등)이 매번 뽑혀 단조롭다 → 후보를 셔플해 다양한 밥이 조합에 들어가게 한다.
        rices_all = candidates.get("밥", [])
        rices = list(rices_all)
        rng.shuffle(rices)
        rices = rices[:_CANDIDATE_POOL]
        soups = candidates.get("국물", [])[:_CANDIDATE_POOL]
        sides = candidates.get("반찬", [])[:_CANDIDATE_POOL]
        # 국물은 밥과 함께여야 자연스럽다(한식 상식). 밥 후보가 없으면 국물은 아예 안 붙인다.
        # → "국물 단독" / "국물+반찬만" 같은 어색한 조합이 생성 단계에서 안 나오게 막는다.
        rice_opts = rices or [None]
        for rice in rice_opts:
            base = [rice] if rice else []
            # 밥이 있을 때만 국물을 곁들임 후보로 둔다(밥 없으면 국물 제외).
            soup_opts = ([None] + soups) if rice else [None]
            for soup in soup_opts:
                cur = base + ([soup] if soup else [])
                # 반찬 0/1/2개
                combos.append(list(cur))
                for s1 in sides:
                    combos.append(cur + [s1])
                    for s2 in sides:
                        if s2 is not s1:
                            combos.append(cur + [s1, s2])

    # 빈 조합 제거 + 재시도 다양성을 위해 셔플(동점일 때 seed로 다른 선택)
    combos = [c for c in combos if c]
    rng.shuffle(combos)
    return combos


def _nutrition_of(items: list[FoodItem]) -> NutritionTotal:
    """조합의 영양 합산(경량). validator/calculator와 동일 로직."""
    t = NutritionTotal()
    for f in items:
        t.total_kcal += _safe(f.kcal)
        t.total_carbohydrate += _safe(f.carbohydrate)
        t.total_protein += _safe(f.protein)
        t.total_fat += _safe(f.fat)
        t.total_sodium += _safe(f.sodium)
    return t


def _score(items: list[FoodItem], conditions: UserConditions) -> float:
    """조합의 '나쁜 정도' 점수. 낮을수록 좋음.

    우선순위(가중치): 칼로리 위반 ≫ 나트륨 FAIL ≫ 탄단지 이탈.
    - 칼로리: upper 초과/부실, target ±10% 이탈을 강하게 벌점(FAIL 축).
    - 나트륨: 1500 초과(FAIL)는 강한 벌점, 그 아래는 약한 벌점.
    - 탄단지: 적정범위 이탈량(%p)을 약한 벌점(경고 축).
    """
    nut = _nutrition_of(items)
    penalty = 0.0
    target = conditions.target_kcal

    # 1) 칼로리 (안전축, 최우선)
    if target:
        kcal = nut.total_kcal
        # kcal_mode가 없어도(LLM이 안 밝힘) 숫자를 준 이상 칼로리 채점은 반드시 한다.
        # None이면 target(정도)로 간주해 상·하한 모두 벌점 → 260kcal이 600 요청에 통과하는 구멍 방지.
        mode = conditions.kcal_mode or "target"
        if mode == "upper":
            if kcal > target:
                penalty += (kcal - target) * 100  # 초과는 절대 안 됨 → 매우 강한 벌점
            elif kcal < target * MAIN_MIN_RATIO:
                penalty += (target * MAIN_MIN_RATIO - kcal) * 20  # 부실도 벌점(덜 강함)
        else:  # target(정도) 또는 mode 미상 — validator와 동일한 허용 오차 사용
            lo = target * (1 - TARGET_KCAL_TOLERANCE)
            hi = target * (1 + TARGET_KCAL_TOLERANCE)
            if kcal < lo:
                penalty += (lo - kcal) * 50
            elif kcal > hi:
                penalty += (kcal - hi) * 50

    # 2) 나트륨 (안전축)
    na = nut.total_sodium
    if na > SODIUM_SOFT_MAX:
        penalty += (na - SODIUM_SOFT_MAX) * 10  # FAIL 구간 → 강한 벌점
    elif na > 767:
        penalty += (na - 767) * 0.5  # 경고 구간 → 약한 벌점

    # 3) 탄단지 균형 (경고축, 약한 벌점) — 준우 요청: 밥+α로 비율 맞추기
    penalty += macro_deviation(nut) * 2

    # 4) 고단백 목표(운동/헬스 포함)면 단백질 비율이 높은 조합을 선호
    if "고단백" in (conditions.nutrition_goals or []):
        kcal = nut.total_kcal or 1
        protein_ratio = (nut.total_protein * 4) / kcal * 100  # 단백질 에너지비율(%)
        if protein_ratio < HIGH_PROTEIN_TARGET:
            penalty += (HIGH_PROTEIN_TARGET - protein_ratio) * 3  # 부족한 만큼 벌점

    # 5) 국물 요청인데 조합에 국물이 없으면 벌점 (매콤한 국물 요리 → 국 포함되게)
    if "국물" in (conditions.preferences or []):
        has_soup = any(f.meal_role == "국물" for f in items)
        if not has_soup:
            penalty += 40

    # 6) 아주 약한 다양성 유도: 음식 수가 지나치게 적은 것보다 2~3개 조합 선호
    if len(items) == 1:
        penalty += 5

    # 7) 역할 궁합(강한 벌점): 완결형 한 그릇 요리 2개를 같이 먹는 건 부자연스러움
    #    (예: 비빔밥+콩국수, 죽+국수). 국물요리 2개도 어색.
    n_onedish = sum(1 for f in items if f.meal_role == "한그릇")
    if n_onedish >= 2:
        penalty += 500 * (n_onedish - 1)
    n_soup = sum(1 for f in items if f.meal_role == "국물")
    if n_soup >= 2:
        penalty += 300 * (n_soup - 1)

    # 8) 국물은 밥과 함께여야 자연스럽다(한식 상식). 국물이 있는데 밥이 없으면 강한 벌점.
    #    (예: 된장찌개+반찬만 → 밥 없이 국·반찬만 먹는 어색한 조합 방지)
    has_soup = n_soup >= 1
    has_rice = any(f.meal_role == "밥" for f in items)
    if has_soup and not has_rice:
        penalty += 400

    # 9) 양념 다양성(중간 벌점): 같은 양념(된장/고추장/간장 등)이 여러 음식에 겹치면 단조로움.
    #    예: 된장찌개+아욱된장무침+된장소스 → 온통 된장. 겹치는 양념마다 (겹친 수-1)×벌점.
    penalty += _seasoning_overlap_penalty(items)

    return penalty


def _seasoning_overlap_penalty(items: list[FoodItem]) -> float:
    """같은 양념이 여러 음식에 겹치면 벌점. 음식명 기준으로 대표 양념을 센다."""
    penalty = 0.0
    for seasoning in _SEASONING_KEYWORDS:
        count = sum(1 for f in items if seasoning in f.food_name)
        if count >= 2:
            penalty += _SEASONING_DUP_PENALTY * (count - 1)
    return penalty


def _reason(meal_type: str, conditions: UserConditions) -> str:
    pref = ", ".join(conditions.preferences) or "기본"
    return f"{meal_type} 형태로, 조건({pref})에 맞춰 구성했습니다."


def _safe(x) -> float:
    try:
        if x is None or x != x:
            return 0.0
        return float(x)
    except (TypeError, ValueError):
        return 0.0

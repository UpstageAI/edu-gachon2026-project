"""가격 단위 환산 — CLAUDE.md §16.2의 `normalize_unit` 툴에 대응하는 파일.

app/tools/judge.py의 judge_price()가 판정 전에 쓰는 일반 무게/개수 단위 환산과,
시나리오 1(쌀 vs 즉석밥)에서만 쓰는 "밥 1공기" 환산을 모두 이 파일에서 관리한다.
원래 normalize_price_unit()이 judge.py에 있었는데, "단위 환산 -> 가격 판정"
순서(§6.2)와 반대로 judge.py가 정의하고 normalize.py가 그걸 가져다 쓰는 역방향
의존이 되어 있었음 — 여기로 옮기고 judge.py가 이 파일을 import하도록 정리.
"""
from __future__ import annotations

import re

# 무게 단위 -> 그램 환산 계수
_WEIGHT_UNIT_TO_GRAM = {"kg": 1000, "g": 1}

# 개수 기반 단위 (1개당으로 환산할 대상)
_COUNT_UNITS = {"개", "속", "단", "포기", "마리", "봉", "팩", "모"}
_TARGET_WEIGHT_TO_GRAM = {
    "100g": 100,
    "500g": 500,
    "1kg": 1000,
}

# [설계 논의로 확정, 2026-07-14] 국립농산물품질관리원 등에서 흔히 쓰는 환산 기준:
# 마른 
# 쌀 90g을 지으면 지어진 밥 210g(1공기)이 나옴 — 참가격 DB의 대표 상품으로 고른
# "즉석밥(햇반 210g)"과 정확히 같은 결과물(밥 1공기) 기준이라 이 값을 그대로 재사용.
# 이 환산 기준은 반드시 답변에도 그대로 공시한다(사용자 요청, app/prompts/prompts.py
# COMPARISON_ANSWER_SYSTEM_PROMPT 참고).
DRY_RICE_GRAMS_PER_BOWL = 90


# [2026-07-14 이동] 원래 app/tools/judge.py에 정의돼 있던 함수(및 위 두 상수)를
# 이 파일로 옮김 — 옮기기 전까지는 이 파일(normalize.py)이 오히려 judge.py의
# normalize_price_unit을 import해서 쓰는 역방향 의존 구조였음. "단위 환산이 먼저,
# 가격 판정이 그 다음"이라는 파이프라인 순서(CLAUDE.md §6.2)에 맞춰 이 파일이
# normalize_unit 툴의 실제 구현 위치가 되도록 정리했고, judge.py는 이제
# `from app.tools.normalize import normalize_price_unit`로 가져다 쓰기만 함.
# 로직 자체는 이동 전과 완전히 동일 — 순수 코드 위치 이동(변수/동작 변경 없음).
def normalize_price_unit(
    last_week: float | None,
    last_month: float | None,
    avg: float | None,
    source_unit: str | None,
    target_unit: str | None,
) -> tuple[float | None, float | None, float | None, str | None]:
    """1주일전/1개월전/평년 가격을 source_unit(KAMIS 원본) 기준에서
    target_unit(사용자 선택) 기준으로 일괄 환산.

    - source_unit이 무게 단위(kg/g)면 target_unit 기준 가격으로 변환.
    - source_unit이 개수 단위(개/속/단 등)면 1개당 가격으로 변환 (target_unit과 무관).
    - source_unit이 없거나 형식을 인식할 수 없으면 변환하지 않고 원본 그대로 반환.
    """
    if not source_unit:
        return last_week, last_month, avg, source_unit

    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([a-zA-Z가-힣]+)\s*$", source_unit.strip())
    if not match:
        return last_week, last_month, avg, source_unit

    qty = float(match.group(1))
    unit_label = match.group(2)

    def _convert(price: float | None) -> float | None:
        if price is None:
            return None
        if unit_label in _WEIGHT_UNIT_TO_GRAM:
            total_grams = qty * _WEIGHT_UNIT_TO_GRAM[unit_label]
            if total_grams <= 0:
                return price
            target_grams = _TARGET_WEIGHT_TO_GRAM.get(target_unit, 100)
            return round(price / total_grams * target_grams, 1)
        if unit_label in _COUNT_UNITS:
            if qty <= 0:
                return price
            return round(price / qty, 1)
        return price

    if unit_label in _WEIGHT_UNIT_TO_GRAM:
        normalized_unit = target_unit or "100g"
    elif unit_label in _COUNT_UNITS:
        normalized_unit = f"1{unit_label}"
    else:
        normalized_unit = source_unit

    return _convert(last_week), _convert(last_month), _convert(avg), normalized_unit


# [2026-07-14 신규, 시나리오 1: 쌀 vs 즉석밥] 위 normalize_price_unit()은 일반적인
# 무게/개수 단위 환산까지만 하고 멈추는데(예: 20kg -> 100g당 가격), 이 함수는 그
# 결과를 "밥 1공기" 기준으로 한 단계 더 환산함 — 원물(쌀)과 가공식품(즉석밥)의
# 가격을 서로 비교하려면 최종적으로 같은 결과물(밥 1공기) 기준으로 맞춰야 하기 때문.
# app/graph/nodes.py의 compare_items_node에서만 사용됨.
def rice_price_per_bowl(price: float, unit: str | None) -> float | None:
    """쌀 판매 단위 가격(예: 60,800원/20kg)을 '밥 1공기(마른 쌀 90g)' 기준 가격으로 환산.

    unit이 무게 단위(kg/g)로 인식되지 않으면(예: 형식 불명) None을 반환 — 임의로
    추정하지 않음.
    """
    _, _, price_per_100g, normalized_unit = normalize_price_unit(
        None, None, price, unit, "100g"
    )
    if price_per_100g is None or normalized_unit != "100g":
        return None
    return round(price_per_100g * DRY_RICE_GRAMS_PER_BOWL / 100, 1)

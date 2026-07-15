"""사용자가 쓰는 일반 명칭 -> 참가격(price_gokr) DB의 실제 상품명 매핑.

원물(쌀 등)은 KAMIS(price_snapshot)에 사용자가 부르는 이름 그대로 존재해서 별도 매핑이
필요 없지만, 가공식품은 사용자가 부르는 일반 명칭("즉석밥")과 실제 유통 상품명
("햇반(210g)")이 달라서 이 매핑이 필요함.

라우팅 방식: 품목을 먼저 get_raw_price(KAMIS)로 조회하고, found=False가 나온 품목만
이 테이블로 실제 상품명을 찾아 get_processed_price(참가격)로 재조회한다 — LLM에게
"이게 원물인지 가공식품인지" 매번 분류시키지 않고, 이미 있는 found 플래그 기반
fallback 패턴을 그대로 재사용.
"""
from __future__ import annotations

# 시나리오 1(쌀 vs 즉석밥) 전용 매핑 — 필요 시 품목 추가
# 값은 price_gokr_items.good_name과 정확히 일치해야 함
# "햇반(210g)"을 대표 상품으로 선택한 이유: 밥 1공기 환산 기준(쌀 90g -> 밥 210g)과
# 정확히 일치하는 유일한 단품 규격이라, 별도 개수 환산 없이 1:1로 비교 가능
PROCESSED_FOOD_ALIASES: dict[str, str] = {
    "즉석밥": "햇반(210g)",
    "햇반": "햇반(210g)",
}


def resolve_processed_alias(item_name: str) -> str | None:
    """사용자 품목명을 참가격 DB의 실제 good_name으로 변환. 매핑이 없으면 None."""
    return PROCESSED_FOOD_ALIASES.get(item_name)

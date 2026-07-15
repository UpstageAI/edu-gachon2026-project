from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.schemas.schemas import JudgePriceOutput
from app.tools.normalize import normalize_price_unit

if TYPE_CHECKING:
    from app.graph.state import AgentState

_EXPENSIVE_THRESHOLD = 10.0   # 평년 대비 +10% 초과 → 비쌈
_CHEAP_THRESHOLD = -10.0      # 평년 대비 -10% 미만 → 쌈


def parse_price(price_str: str) -> float | None:
    """콤마 포함 문자열("3,606") 또는 결측치("-")를 float으로 변환."""
    if not price_str or price_str.strip() == "-":
        return None
    try:
        return float(price_str.replace(",", "").strip())
    except ValueError:
        return None


def _pct_diff(current: float | None, past: float | None) -> float | None:
    if current is None or past is None or past == 0:
        return None
    return round((current - past) / past * 100, 1)

def judge_price(
    dpr1: str,
    dpr7: str,
    dpr3: str | None = None,
    dpr5: str | None = None,
    source_unit: str | None = None,
    target_unit: str | None = None,
) -> JudgePriceOutput:
    """1주일전가(dpr3)를 1개월전가(dpr5)와 비교하여 비쌈/적정/쌈 판정.

    [2026-07-14 수정] 당일가(dpr1) 결측이 잦아서(다른 PC에서 작업) 판정 기준을
    dpr1 vs dpr7(평년)에서 dpr3 vs dpr5로 변경한 상태 — 이 docstring이 옛 설명
    ("당일가를 평년가와 비교")으로 남아있어 실제 로직과 안 맞았던 것만 바로잡음
    (동작 자체는 변경 없음). dpr1/dpr7은 현재 판정에 쓰이지 않음(dpr7은 참고용
    month_diff_pct 계산에만 사용).
    """
    last_week = parse_price(dpr3)
    last_month = parse_price(dpr5)
    avg = parse_price(dpr7)

    if last_week is None or last_month is None or last_month == 0:
        return JudgePriceOutput(status="적정", diff_pct=0.0)

    print(f"judge_price: source_unit={source_unit}, target_unit={target_unit}")
    normalized_last_week, normalized_last_month, normalized_avg, normalized_unit = normalize_price_unit(
        last_week, last_month, avg, source_unit, target_unit
    )
    print(f"judge_price_normalized_unit: {normalized_unit}")

    # 판정(diff_pct)은 % 계산이라 단위 환산과 무관하게 동일한 비율이 나오므로
    # 원본 값(last_week/last_month) 그대로 사용해도 결과는 같음 — 그대로 유지
    diff_pct = (last_week - last_month) / last_month * 100

    if diff_pct > _EXPENSIVE_THRESHOLD:
        status = "비쌈"
    elif diff_pct < _CHEAP_THRESHOLD:
        status = "쌈"
    else:
        status = "적정"

    # [2026-07-15 (8) 수정] 기존엔 last_month(1개월전) vs avg(평년)로 계산했는데, 답변에는
    # 이 수치가 화면에 실제로 표시되는 "현재 가격"(today_price=last_week, 1주일전 값)의
    # 평년 대비인 것처럼 "현재 가격은 ...원, 평년 대비 X%"로 서술됨 — 계산 자체는 정확했지만
    # 어느 시점 가격 기준인지가 화면 표시 시점과 어긋나 사용자에게 오해를 줄 수 있는 걸
    # 실제 재현으로 확인함(상추 사례: 1개월전 기준으로는 평년 대비 -61.1%였지만, 실제
    # 화면에 표시된 1주일전 가격 기준으로는 -57.1%였음). 화면에 노출되는 가격과 동일한
    # 시점(last_week) 기준으로 계산하도록 수정 — "평년 대비"라는 라벨이 실제 표시 가격과
    # 항상 일치하게 됨.
    month_diff_pct = _pct_diff(last_week, avg)

    return JudgePriceOutput(
        status=status,
        diff_pct=round(diff_pct, 1),
        month_diff_pct=month_diff_pct,
        normalized_price=normalized_last_week,
        unit=normalized_unit,
        # [2026-07-15 (9) 추가] normalized_price는 항상 last_week(dpr3=1주일전) 기준이라
        # "당일"이라고 표시하면 안 됨 — app/tools/kamis.py의 dpr1 기반 price_as_of(compare_items_node
        # 용)와는 별개로, 여기서는 이 값의 진짜 출처를 있는 그대로 고지.
        price_as_of="1주일전",
    )


def judge_price_node(state: AgentState) -> dict[str, Any]:
    price_data = state.get("price_data", [])
    target_unit = state.get("unit")
    judgments = []
    for item in price_data:
        if not item.get("found", True):
            # DB 미등록 품목 — 임의 추정 금지, "미지원"으로 표시해 답변 생성 단계에서 안내
            judgments.append(
                {
                    "item_name": item.get("item_name"),
                    "status": "미지원",
                    "diff_pct": None,
                    "month_diff_pct": None,
                }
            )
            continue

        result = judge_price(
            item.get("dpr1", "-"),
            item.get("dpr7", "-"),
            item.get("dpr3", "-"),
            item.get("dpr5", "-"),
            item.get("unit"),
            target_unit,
        )
        judgments.append(
            {
                "item_name": item.get("item_name"),
                "status": result.status,
                "diff_pct": result.diff_pct,
                "month_diff_pct": result.month_diff_pct,
                # 답변 생성 단계에서 실제 금액을 지어내지 않도록 조회된 값 그대로 전달
                "today_price": result.normalized_price,
                "unit": result.unit,
                # [2026-07-15 (9) 수정] item.get("price_as_of")(kamis.py가 dpr1 기준으로
                # 계산한 값 — compare_items_node/시나리오 1 전용)를 그대로 전달하면
                # today_price(dpr3=1주일전 기준)와 시점이 어긋나 잘못된 고지("당일" 등)가
                # 될 수 있었음 — result.price_as_of(judge_price()가 today_price와 동일한
                # 근거로 직접 계산한 값)로 교체.
                "price_as_of": result.price_as_of,
            }
        )
        print(
            f"[judge_price_node] item={item.get('item_name')!r}, "
            f"target_unit={target_unit!r}, result.unit={result.unit!r}"
        )  # 추가
    print(f"[judge_price_node] 전체 judgments 유닛: {[j.get('unit') for j in judgments]}")  # 추가

    
    return {"judgment": judgments}

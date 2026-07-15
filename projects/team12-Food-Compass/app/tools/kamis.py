from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.tools.judge import parse_price
from app.tools.price_snapshot import (
    get_latest_prices,
    get_latest_prices_by_kind_name,
    search_similar_item_names,
)

if TYPE_CHECKING:
    from app.graph.state import AgentState

_DPR_FIELDS = ("dpr1", "dpr2", "dpr3", "dpr4", "dpr5", "dpr6", "dpr7")

# [2026-07-15 수정] 여러 등급(상품/중품 등) 중 대표로 삼을 등급 우선순위 — "중품"으로
# 고정하기로 함(사용자 확인). 전 품목이 "중품"을 갖고 있진 않아서(갈치/명태는 "中"/"大"만,
# 마른멸치는 대멸/세멸/중멸만 있는 식) "상품"을 2차 후보로, 그래도 없으면 첫 row로 폴백.
_PREFERRED_RANKS = ("중품", "상품")

# [2026-07-15 추가] KAMIS 축산물(500) DB엔 "돼지"/"소"/"닭"처럼 동물 이름 그대로만 있고
# "돼지고기"/"소고기"/"닭고기"(일상적으로 부르는 이름)는 정확히 일치하는 문자열이 없어서
# 매번 조회에 실패하고 있었음(실제 재현: "오늘 돼지고기 가격은 어때?" → KAMIS found=False →
# 참가격 경로로 새서 엉뚱한 소스의 답변이 나감). "-고기" 접미사를 뗀 이름으로 정규화.
_LIVESTOCK_NAME_ALIASES: dict[str, str] = {
    "돼지고기": "돼지",
    "소고기": "소",
    "닭고기": "닭",
}

# [2026-07-15 추가] 소/돼지/닭은 부위(kind_name)별로 가격이 크게 다른데(등심 vs 삼겹살 등),
# 부위 하나만 임의로 골라 답하면 참가격 기능 때와 같은 "잘못된 단일 매칭" 위험이 있어
# 부위 전체를 나열하는 방식으로 처리(사용자 확인) — 체크박스 UI는 도입하지 않기로 함.
LIVESTOCK_ITEMS = {"돼지", "소", "닭"}

# [2026-07-15 추가] 소만 실제 등급(1++/1+/1등급) 축이 별도로 존재함(돼지/닭은 rank_name이
# kind_name과 동일해 등급 구분 자체가 없음) — 프리미엄 등급(1++/1+)보다 유통량이 많은
# "1등급"을 기준으로 고정(사용자 확인).
_LIVESTOCK_GRADED_ITEMS = {"소"}
_PREFERRED_LIVESTOCK_GRADE = "1등급"


def _normalize_kamis_item_name(item_name: str) -> str:
    """"돼지고기" 같은 일상 표현을 KAMIS DB의 실제 표기("돼지")로 정규화."""
    return _LIVESTOCK_NAME_ALIASES.get(item_name, item_name)

# [2026-07-14 확인] KAMIS 응답에 실제로 딸려오는 day1~day7 라벨로 확인한 dpr1~dpr7 의미:
#   dpr1=당일, dpr2=1일전, dpr3=1주일전, dpr4=2주일전, dpr5=1개월전, dpr6=1년전, dpr7=일평년(평년가)
# dpr7(평년가)은 judge_price의 비교 기준 그 자체라 fallback 후보에서 제외.
# dpr6(1년전)도 제외 — "오늘 가격 없으니 최근 데이터로 보완"이라는 취지에서 1년 전 가격까지
# 끌어와 "당일가"인 것처럼 쓰면 계절/물가 변동을 무시하고 왜곡된 판정을 낼 수 있어 너무 멂.
_FALLBACK_FIELDS = ("dpr2", "dpr3", "dpr4", "dpr5")

# [2026-07-14 추가] fallback으로 어떤 필드를 썼는지 답변에 "N일 전 기준"으로 밝히기 위한 라벨.
# dpr1 자체(당일)도 포함해서, fallback 없이 당일가를 그대로 쓴 경우와 구분할 수 있게 함.
_DAY_LABELS = {
    "dpr1": "당일",
    "dpr2": "1일전",
    "dpr3": "1주일전",
    "dpr4": "2주일전",
    "dpr5": "1개월전",
}


def _pick_representative_row(rows: list[dict]) -> dict:
    """같은 품목의 여러 품종·등급 row 중 대표 1건 선택 — '중품' 우선, 없으면 '상품', 그래도 없으면 첫 row."""
    for preferred_rank in _PREFERRED_RANKS:
        for row in rows:
            if row.get("rank_name") == preferred_rank:
                return row
    return rows[0]


def _select_livestock_rows(rows: list[dict], item_name: str) -> list[dict]:
    """축산물은 부위(kind_name)별 가격 차이가 커서 대표 1건이 아니라 부위 전체를 반환.

    소처럼 등급(rank_name) 축이 따로 있는 품목은 먼저 _PREFERRED_LIVESTOCK_GRADE로
    필터링한 뒤 부위별 1건씩 뽑고, 돼지/닭처럼 등급 구분이 없는(rank_name이 kind_name과
    동일한) 품목은 그대로 부위별 1건씩 뽑는다.
    """
    if item_name in _LIVESTOCK_GRADED_ITEMS:
        graded = [r for r in rows if r.get("rank_name") == _PREFERRED_LIVESTOCK_GRADE]
        candidates = graded or rows
    else:
        candidates = rows

    by_kind: dict[str, dict] = {}
    for row in candidates:
        kind = row.get("kind_name") or ""
        if kind not in by_kind:
            by_kind[kind] = row
    return list(by_kind.values())


def _resolve_today_price(row: dict) -> dict:
    """당일가(dpr1)가 '-'(당일 데이터 미반영)이면 dpr2→dpr5(1개월전까지) 순서로 값이 있는 첫 필드로 대체.

    [2026-07-14 수정] 기존엔 dpr2(전일가) 한 단계만 시도하고 그래도 없으면 그냥 포기했음.
    실제로 축산물(500)을 제외한 전 부류에서 dpr1·dpr2가 동시에 결측인 날이 있는데, 그런
    경우도 dpr3~dpr5엔 값이 남아있는 걸 확인함(§11 "가격 데이터 결측 시 과거 데이터로
    보완" 원칙과도 일치) — 1개월전(dpr5)까지 순서대로 폴백하도록 확장. dpr6(1년전)은
    너무 멀어서 fallback 후보에서 제외(위 _FALLBACK_FIELDS 주석 참고).

    [2026-07-14 추가] fallback으로 며칠 전 값을 끌어왔는지 사용자에게 "N일 전 기준"으로
    투명하게 밝히기 위해, 실제 사용된 필드가 며칠 전인지를 resolved["price_as_of"]에
    담아 반환 — 당일가를 그대로 썼으면 "당일", fallback을 탔으면 그 필드의 라벨, 아무
    필드도 못 찾았으면 None(가격 데이터 자체가 없는 경우이므로 시점 표기 불필요).
    """
    resolved = dict(row)
    resolved["price_as_of"] = _DAY_LABELS["dpr1"]
    if parse_price(resolved.get("dpr1", "-")) is None:
        resolved["price_as_of"] = None
        for field in _FALLBACK_FIELDS:
            fallback = resolved.get(field, "-")
            if parse_price(fallback) is not None:
                resolved["dpr1"] = fallback
                resolved["price_as_of"] = _DAY_LABELS[field]
                break
    return resolved


def _group_rows_by_item_name(rows: list[dict]) -> dict[str, list[dict]]:
    """ILIKE 폴백으로 여러 품목명(예: 건고추/붉은고추/풋고추)이 섞여 들어올 수 있어
    실제 item_name 기준으로 다시 묶는다."""
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["item_name"], []).append(row)
    return groups


def _rows_to_price_entries(rows: list[dict], item_name: str) -> list[dict[str, Any]]:
    """한 품목명 그룹의 row들을 최종 price_data 항목(들)으로 변환.

    축산물(소/돼지/닭)은 부위별로 전부 나열(_select_livestock_rows), 그 외 품목은
    기존처럼 대표 1건만 선택 — "고추" 같은 ILIKE 폴백 매칭도 품목명 그룹 단위로는
    동일한 규칙을 그대로 적용한다(풋고추 안의 청양고추/꽈리고추 등 세부 품종까지
    나열하진 않음 — 이번 스코프는 "고추"가 KAMIS에서 검색되게 하는 것까지).
    """
    is_livestock = item_name in LIVESTOCK_ITEMS
    if is_livestock:
        selected_rows = _select_livestock_rows(rows, item_name)
    else:
        selected_rows = [_pick_representative_row(rows)]

    entries = []
    for raw_row in selected_rows:
        row = _resolve_today_price(raw_row)
        # 축산물은 부위별로 나열하므로 "돼지 삼겹살"처럼 부위명을 붙여 항목을 구분
        display_name = f"{row['item_name']} {row['kind_name']}" if is_livestock else row["item_name"]
        entries.append(
            {
                "item_name": display_name,
                "unit": row["unit"],
                "found": True,
                "price_as_of": row.get("price_as_of"),
                **{field: row.get(field, "-") for field in _DPR_FIELDS},
            }
        )
    return entries


def get_raw_price_node(state: AgentState) -> dict[str, Any]:
    """Supabase price_snapshot에서 실제 KAMIS 시세(당일·1주일전·1개월전·평년)를 조회.

    - DB에 없는 품목은 found=False로 표시 — 값을 임의로 채우지 않음(§11-3, 미지원 품목 안내).
    - DB 조회 자체가 실패하면(연결 오류 등) 동일하게 미지원으로 처리.
    """
    items = state.get("items", [])
    price_data = []
    for raw_item_name in items:
        item_name = _normalize_kamis_item_name(raw_item_name)
        try:
            rows = get_latest_prices(item_name)
        except Exception as e:
            print(f"[get_raw_price] DB 조회 실패: {e}")
            rows = []

        if not rows:
            # [2026-07-15 추가] 정확히 일치하는 품목명이 없으면 ILIKE 부분일치로 재시도 —
            # "고추"처럼 KAMIS DB엔 "붉은고추"/"풋고추"/"건고추"만 있어 정확 일치가 실패하고
            # 참가격(data.go.kr)으로 새던 문제(KAMIS에 실제 데이터가 있는데도 밀리던 것)를
            # 막기 위함 — data.go.kr보다 KAMIS를 먼저/우선 매칭시키는 효과.
            try:
                similar_names = search_similar_item_names(item_name)
            except Exception as e:
                print(f"[get_raw_price] 유사 품목명 검색 실패: {e}")
                similar_names = []
            for name in similar_names:
                try:
                    rows.extend(get_latest_prices(name))
                except Exception as e:
                    print(f"[get_raw_price] DB 조회 실패({name}): {e}")

        if not rows:
            # [2026-07-15 추가] "삼겹살"처럼 KAMIS에선 item_name이 아니라 "돼지"의
            # kind_name(부위)일 뿐인 경우 — 위 두 단계(정확 일치/ILIKE)는 전부 item_name만
            # 보므로 여전히 못 찾고 참가격으로 새고 있었음(실제 재현 확인). 이 품목명이
            # 실은 부위명인지 확인해, 그 부위를 가진 품목(들)에서 **그 부위만** 가져온다
            # (사용자 확인: "삼겹살"→돼지 삼겹살 1건만, "갈비"처럼 여러 동물에 겹치면
            # →돼지 갈비 + 소 갈비처럼 각 동물의 그 부위만, 다른 부위까지 확장하진 않음).
            try:
                rows.extend(get_latest_prices_by_kind_name(item_name))
            except Exception as e:
                print(f"[get_raw_price] 부위명 매칭 실패: {e}")

        if not rows:
            price_data.append(
                {
                    "item_name": raw_item_name,
                    "unit": "-",
                    "found": False,
                    **{field: "-" for field in _DPR_FIELDS},
                }
            )
            continue

        for group_item_name, group_rows in _group_rows_by_item_name(rows).items():
            price_data.extend(_rows_to_price_entries(group_rows, group_item_name))
    return {"price_data": price_data}

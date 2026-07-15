"""Build persona-based housing recommendation scenarios.

Inputs:
  data/personas/persona_sample_stratified.csv

Outputs:
  data/personas/persona_relevant_pool.csv
  data/personas/persona_scenario_candidates.csv
  data/personas/data_coverage_audit.csv
  data/personas/persona_scenarios_30.csv

The output is intentionally rule/template-based. The goal is not to hallucinate
new personas, but to turn sampled synthetic personas into a reproducible
scenario validation set for the current service schema.
"""
from __future__ import annotations

import argparse
import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import pandas as pd


INPUT = Path("data/personas/persona_sample_stratified.csv")
OUTPUT_DIR = Path("data/personas")

TEXT_FIELDS = [
    "persona",
    "detailed_persona",
    "family_persona",
    "finance_persona",
    "healthcare_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "hobbies_and_interests",
    "hobbies_and_interests_list",
    "occupation",
    "family_type",
]

CURRENT_FIELDS = {
    "crime_rate",
    "cctv_cnt",
    "conv_cnt",
    "mart_cnt",
    "hosp_cnt",
    "bus_cnt",
    "subway_access",
    "park_cnt",
    "facility_repository.extra_categories",
}


SIGNAL_KEYWORDS: dict[str, list[str]] = {
    "runner_active": [
        "러닝",
        "마라톤",
        "조깅",
        "달리",
        "산책",
        "등산",
        "자전거",
        "헬스",
        "운동",
        "배드민턴",
        "필라테스",
        "요가",
    ],
    "pet": ["반려견", "반려동물", "강아지", "고양이", "반려묘"],
    "creative_freelance": [
        "화가",
        "작가",
        "디자이너",
        "웹 디자이너",
        "프리랜서",
        "사진",
        "음악",
        "예술",
        "공예",
        "창작",
    ],
    "mobility": ["출퇴근", "야근", "지하철", "버스", "대중교통", "통근", "퇴근"],
    "night_safety": ["야근", "밤", "안전", "늦은", "귀가"],
    "health_hospital": ["병원", "건강", "혈압", "혈당", "당뇨", "고혈압", "보건소", "무릎"],
    "parent_care": ["부모", "어머니", "아버지", "조모", "고령", "돌봄", "모시"],
    "quiet_focus": ["조용", "방음", "재택", "집에서", "집중", "소음", "작업"],
    "rent_budget": ["월세", "전세", "대출", "내 집 마련", "생활비", "경제적", "수입"],
    "convenience": ["마트", "편의점", "배달", "카페", "식당", "외식", "장보기"],
    "family_school": ["자녀", "학교", "보육", "아이", "학원", "어린이"],
}


@dataclass(frozen=True)
class ScenarioTemplate:
    scenario_type: str
    persona_type: str
    coverage_status: str
    required_data_fields: list[str]
    mapped_categories: list[str]
    missing_data: list[str]
    extra_categories: list[str]
    presentation_point: str
    priority: int
    question: str
    selector: Callable[[pd.Series], bool]
    expected_intent: str


def safe(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def combined_text(row: pd.Series) -> str:
    return " ".join(safe(row.get(field)) for field in TEXT_FIELDS)


def contains_any(row: pd.Series, signal: str) -> bool:
    text = combined_text(row)
    return any(keyword in text for keyword in SIGNAL_KEYWORDS[signal])


def age_in(row: pd.Series, groups: set[str]) -> bool:
    return safe(row.get("age_group")) in groups


def family_contains(row: pd.Series, *tokens: str) -> bool:
    family = safe(row.get("family_type"))
    return any(token in family for token in tokens)


def occupation_group(row: pd.Series, group: str) -> bool:
    return safe(row.get("occupation_group")) == group


def text_any(row: pd.Series, words: Iterable[str]) -> bool:
    text = combined_text(row)
    return any(word in text for word in words)


def persona_context(row: pd.Series) -> str:
    district = safe(row.get("district"))
    age_group = safe(row.get("age_group"))
    occupation = safe(row.get("occupation"))
    family_type = safe(row.get("family_type"))
    housing_tenure = safe(row.get("housing_tenure"))
    income = safe(row.get("income_bracket"))
    return (
        f"{district} 거주 {age_group}, {occupation}, {family_type}, "
        f"{housing_tenure}, 소득구간 {income}"
    )


def source_summary(row: pd.Series, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", safe(row.get("persona")) or safe(row.get("detailed_persona")))
    return text[:limit]


def matched_signals(row: pd.Series) -> list[str]:
    out = [signal for signal in SIGNAL_KEYWORDS if contains_any(row, signal)]
    if age_in(row, {"20s", "30s"}):
        out.append("mz_age")
    if family_contains(row, "혼자"):
        out.append("single_household")
    if occupation_group(row, "office_professional"):
        out.append("office_professional")
    return sorted(set(out))


def relevance_score(row: pd.Series) -> int:
    weights = {
        "runner_active": 6,
        "pet": 8,
        "creative_freelance": 7,
        "mobility": 6,
        "night_safety": 6,
        "health_hospital": 5,
        "parent_care": 6,
        "quiet_focus": 7,
        "rent_budget": 4,
        "convenience": 4,
        "family_school": 3,
    }
    score = sum(weights[s] for s in matched_signals(row) if s in weights)
    if age_in(row, {"20s", "30s"}):
        score += 5
    if family_contains(row, "혼자"):
        score += 5
    if occupation_group(row, "office_professional"):
        score += 3
    if safe(row.get("housing_tenure")) == "전·월세":
        score += 2
    return score


def build_templates() -> list[ScenarioTemplate]:
    answerable = "answerable"
    partial = "partial"
    clarify = "clarify"
    not_answerable = "not_answerable"

    return [
        ScenarioTemplate(
            "A01",
            "야근 많은 이동성 중시 1인 직장인",
            answerable,
            ["crime_rate", "cctv_cnt", "bus_cnt", "subway_access"],
            ["safety", "mobility"],
            [],
            [],
            "자연어 생활 조건을 안전+이동 지표로 매핑하는 대표 데모",
            100,
            "야근이 잦고 차가 없어서 밤에도 지하철이나 버스로 안전하게 귀가할 수 있는 동네를 찾고 싶어요.",
            lambda r: age_in(r, {"20s", "30s"}) and (family_contains(r, "혼자") or occupation_group(r, "office_professional")),
            "안전 very_high, 이동 very_high, 편의 medium, 환경 none",
        ),
        ScenarioTemplate(
            "A02",
            "퇴근 후 러닝 루틴이 있는 MZ",
            answerable,
            ["park_cnt", "bus_cnt", "subway_access", "crime_rate", "cctv_cnt"],
            ["environment", "mobility", "safety"],
            [],
            [],
            "공원/이동/안전을 복합적으로 쓰는 라이프스타일형 질문",
            99,
            "퇴근 후에 러닝이나 산책을 꾸준히 하고 싶어서 공원이 가깝고, 밤에도 집에 돌아가기 부담 없는 동네가 좋아요.",
            lambda r: contains_any(r, "runner_active") and age_in(r, {"20s", "30s", "40s"}),
            "환경 very_high, 안전 high, 이동 high, 편의 medium",
        ),
        ScenarioTemplate(
            "A03",
            "헬스장과 공원을 모두 쓰는 자기관리형",
            answerable,
            ["park_cnt", "facility_repository.extra_categories"],
            ["environment", "convenience", "extra:헬스장"],
            [],
            ["헬스장"],
            "기본 지표와 상권 업종 확장을 함께 보여주는 데모",
            98,
            "헬스장에 자주 가고 쉬는 날엔 공원에서 걷고 싶어요. 운동 루틴을 유지하기 좋은 동네를 추천해줘요.",
            lambda r: text_any(r, ["헬스", "운동", "배드민턴", "필라테스", "요가"]),
            "환경 very_high, 편의 high, 추가업종 헬스장 very_high",
        ),
        ScenarioTemplate(
            "A04",
            "부모님 병원 접근성을 보는 가족",
            answerable,
            ["hosp_cnt", "bus_cnt", "subway_access"],
            ["convenience", "mobility"],
            [],
            [],
            "멘토링 피드백에 맞는 실제 필요성 강한 생활 편의 데모",
            97,
            "부모님 병원 진료를 자주 챙겨야 해서 병원 접근성이 좋고 대중교통으로 이동하기 편한 동네가 필요해요.",
            lambda r: contains_any(r, "health_hospital") or contains_any(r, "parent_care") or age_in(r, {"50s", "60s", "70_plus"}),
            "편의 very_high, 이동 high, 안전 medium",
        ),
        ScenarioTemplate(
            "A05",
            "카페에서 작업하는 프리랜서",
            answerable,
            ["facility_repository.extra_categories", "bus_cnt", "subway_access", "park_cnt"],
            ["extra:카페", "mobility", "environment"],
            [],
            ["카페"],
            "상권 업종 확장을 활용해 프리랜서 생활 동선을 설명",
            95,
            "카페에서 작업하거나 오래 머무는 날이 많고, 답답할 때 걸을 수 있는 공원도 가까웠으면 해요.",
            lambda r: contains_any(r, "creative_freelance") or text_any(r, ["카페", "작업", "프리랜서", "디자이너"]),
            "추가업종 카페 very_high, 환경 high, 이동 medium",
        ),
        ScenarioTemplate(
            "A06",
            "생활 편의 밀도 중시 직장인",
            answerable,
            ["conv_cnt", "mart_cnt", "bus_cnt", "subway_access"],
            ["convenience", "mobility"],
            [],
            [],
            "현재 convenience 지표가 실제 질문을 커버함을 보여줌",
            93,
            "퇴근이 늦어서 집 근처에 편의점이나 마트가 충분하고 대중교통도 불편하지 않은 동네가 좋아요.",
            lambda r: contains_any(r, "convenience") or occupation_group(r, "office_professional"),
            "편의 very_high, 이동 high, 안전 medium",
        ),
        ScenarioTemplate(
            "A07",
            "큰 병원을 필수로 보는 건강 민감형",
            answerable,
            ["hosp_cnt"],
            ["convenience"],
            [],
            [],
            "하드 필터(require_large_hospital) 설명에 적합",
            92,
            "건강검진이나 진료를 자주 받아서 큰 병원이 가까운 곳은 꼭 필요해요. 병원 접근성을 최우선으로 봐줘요.",
            lambda r: contains_any(r, "health_hospital"),
            "대형병원 필수조건, 편의 very_high",
        ),
        ScenarioTemplate(
            "A08",
            "공원과 조용한 동네를 원하는 재택근무자",
            partial,
            ["park_cnt"],
            ["environment"],
            ["noise_level", "soundproofing"],
            [],
            "환경은 답할 수 있지만 조용함/방음 데이터 부족을 보여줌",
            91,
            "집에서 집중해야 하는 시간이 많아서 조용하고 방음이 잘 되는 곳이 좋고, 머리 식힐 공원도 가까웠으면 해요.",
            lambda r: contains_any(r, "quiet_focus") or contains_any(r, "creative_freelance"),
            "환경 high, 조용함/방음은 현재 데이터 부족",
        ),
        ScenarioTemplate(
            "A09",
            "반려동물 산책 루틴이 있는 사람",
            partial,
            ["park_cnt", "facility_repository.extra_categories"],
            ["environment", "extra:동물병원"],
            ["pet_friendly_facilities"],
            ["동물병원"],
            "반려동물 인프라를 상권 데이터와 부족 데이터로 나눠 설명",
            90,
            "반려동물과 살고 있어서 산책하기 좋은 공원이 가깝고, 동물병원 같은 반려동물 인프라도 있는 동네가 좋아요.",
            lambda r: contains_any(r, "pet") or text_any(r, ["반려견", "강아지", "고양이"]),
            "환경 very_high, 동물병원 extra, 반려동물 친화도는 부족",
        ),
        ScenarioTemplate(
            "A10",
            "월세 부담이 있는 MZ 직장인",
            partial,
            ["bus_cnt", "subway_access"],
            ["mobility"],
            ["rent_median", "deposit_median"],
            [],
            "월세/전세는 경향 mock으로 보완할 후보",
            89,
            "월세 부담이 커서 너무 비싸지 않은 곳이면 좋겠고, 출퇴근 때문에 지하철 접근성은 포기하기 어려워요.",
            lambda r: age_in(r, {"20s", "30s"}) and (safe(r.get("housing_tenure")) == "전·월세" or contains_any(r, "rent_budget")),
            "이동 very_high, 월세/전세 시세는 현재 데이터 부족",
        ),
        ScenarioTemplate(
            "A11",
            "실제 통근시간을 요구하는 직장인",
            partial,
            ["bus_cnt", "subway_access"],
            ["mobility"],
            ["door_to_door_commute_time"],
            [],
            "접근성 점수와 실제 소요시간의 차이를 설명할 수 있음",
            88,
            "회사까지 실제 대중교통으로 30분 안에 갈 수 있는 동네를 찾고 싶어요. 단순히 지하철역 가까운 것만으로는 부족해요.",
            lambda r: occupation_group(r, "office_professional") or contains_any(r, "mobility"),
            "이동 very_high, 실제 목적지 기반 통근시간은 부족",
        ),
        ScenarioTemplate(
            "A12",
            "창작 작업을 위한 방음/채광 중시자",
            not_answerable,
            [],
            [],
            ["soundproofing", "sunlight_direction", "unit_level_building_data"],
            [],
            "집값에 반영되지 않는 세부 매물 요구가 왜 어려운지 보여줌",
            87,
            "창작 작업이나 취미 작업을 해서 자연광이 잘 들어오는 남향 방과 방음이 중요해요. 이런 조건까지 보고 동네를 고르고 싶어요.",
            lambda r: contains_any(r, "creative_freelance") or text_any(r, ["그림", "화가", "예술", "음악"]),
            "남향/채광/방음은 행정동 공공지표로 직접 답변 어려움",
        ),
        ScenarioTemplate(
            "A13",
            "아이와 공원·병원 접근성을 보는 가구",
            partial,
            ["park_cnt", "hosp_cnt", "bus_cnt", "subway_access"],
            ["environment", "convenience", "mobility"],
            ["school_access", "childcare_facilities"],
            [],
            "현재 강점과 학교/어린이집 부족을 함께 드러냄",
            86,
            "아이를 키우거나 가족 돌봄을 고려하면 공원과 병원이 가까우면 좋겠고, 가능하면 학교나 어린이집도 가까운 동네였으면 해요.",
            lambda r: contains_any(r, "family_school") or family_contains(r, "자녀"),
            "환경 high, 편의 high, 학교/어린이집은 부족",
        ),
        ScenarioTemplate(
            "A14",
            "외식·배달·카페 루틴이 확실한 사람",
            answerable,
            ["conv_cnt", "mart_cnt", "facility_repository.extra_categories"],
            ["convenience", "extra:카페"],
            [],
            ["카페", "음식점"],
            "상권 업종 기반 개인 취향 반영을 설명",
            85,
            "집 근처에서 카페도 자주 가고 배달이나 외식도 많이 해요. 생활 편의시설이 몰려 있는 동네를 보고 싶어요.",
            lambda r: contains_any(r, "convenience") or text_any(r, ["배달", "카페", "외식"]),
            "편의 very_high, 카페/음식점 extra",
        ),
        ScenarioTemplate(
            "A15",
            "밤길 안정감을 보는 1인 여성/1인 가구",
            answerable,
            ["crime_rate", "cctv_cnt", "bus_cnt", "subway_access"],
            ["safety", "mobility"],
            [],
            [],
            "안전 지표의 필요성을 직관적으로 보여줌",
            84,
            "밤길이 너무 불안하지 않고, 늦게 들어와도 대중교통에서 집까지 이동이 부담 없는 동네였으면 해요.",
            lambda r: family_contains(r, "혼자") or contains_any(r, "night_safety"),
            "안전 very_high, 이동 high",
        ),
        ScenarioTemplate(
            "A16",
            "마트와 병원 중심의 실용형",
            answerable,
            ["mart_cnt", "conv_cnt", "hosp_cnt"],
            ["convenience"],
            [],
            [],
            "편의 카테고리 내부 근거를 설명하기 쉬움",
            83,
            "화려한 상권보다 마트랑 병원이 가까운 실용적인 동네가 좋아요. 일상생활이 편한 곳 위주로 추천해줘요.",
            lambda r: contains_any(r, "convenience") or contains_any(r, "health_hospital"),
            "편의 very_high, 이동 medium",
        ),
        ScenarioTemplate(
            "A17",
            "공원 많은 조용한 은퇴/중장년층",
            answerable,
            ["park_cnt", "hosp_cnt", "bus_cnt"],
            ["environment", "convenience", "mobility"],
            [],
            [],
            "MZ 외에도 생활 맥락 선명한 사용자군을 보완",
            82,
            "시끄러운 번화가보다는 산책할 공원이 많고 병원이나 버스 접근성이 괜찮은 차분한 동네가 좋아요.",
            lambda r: age_in(r, {"50s", "60s", "70_plus"}) and contains_any(r, "runner_active"),
            "환경 very_high, 편의 high, 이동 medium",
        ),
        ScenarioTemplate(
            "A18",
            "버스 중심 이동자",
            answerable,
            ["bus_cnt", "subway_access"],
            ["mobility"],
            [],
            [],
            "지하철뿐 아니라 버스 접근성도 점수에 포함됨을 보여줌",
            81,
            "지하철만큼 버스 접근성도 중요해요. 여러 방향으로 이동하기 편한 동네를 추천해줘요.",
            lambda r: contains_any(r, "mobility") or occupation_group(r, "service_sales"),
            "이동 very_high",
        ),
        ScenarioTemplate(
            "C01",
            "취향은 있지만 우선순위가 모호한 사용자",
            clarify,
            [],
            [],
            [],
            [],
            "되묻기 1회 agentic 분기를 보여줌",
            80,
            "너무 삭막하지 않고 제 생활이랑 잘 맞는 동네면 좋겠어요. 어디가 괜찮을까요?",
            lambda r: True,
            "needs_clarification=True, 안전/편의/이동/환경 중 우선순위 질문 필요",
        ),
        ScenarioTemplate(
            "C02",
            "좋은 동네를 막연히 원하는 사용자",
            clarify,
            [],
            [],
            [],
            [],
            "모호한 요구를 바로 추천하지 않고 되묻는 품질 기준",
            79,
            "서울에서 살기 좋은 동네 아무 데나 추천해줘요. 딱히 정한 조건은 없어요.",
            lambda r: True,
            "needs_clarification=True, 구체 조건 질문 필요",
        ),
        ScenarioTemplate(
            "C03",
            "감성 표현만 있는 사용자",
            clarify,
            [],
            [],
            [],
            [],
            "자연어 서비스가 애매한 표현을 해석하기 전에 확인해야 함",
            78,
            "퇴근하고 돌아왔을 때 마음이 좀 편해지는 동네였으면 좋겠어요.",
            lambda r: True,
            "needs_clarification=True, 환경/안전/편의 중 의미 확인 필요",
        ),
    ]


def expand_templates(templates: list[ScenarioTemplate]) -> list[ScenarioTemplate]:
    """Add controlled variants so candidate pool reaches 60-100 rows."""
    variants: list[ScenarioTemplate] = []
    for tmpl in templates:
        variants.append(tmpl)
        if tmpl.coverage_status == "clarify":
            continue
        if tmpl.coverage_status == "answerable":
            variants.append(ScenarioTemplate(
                scenario_type=tmpl.scenario_type + "v2",
                persona_type=tmpl.persona_type,
                coverage_status=tmpl.coverage_status,
                required_data_fields=tmpl.required_data_fields,
                mapped_categories=tmpl.mapped_categories,
                missing_data=tmpl.missing_data,
                extra_categories=tmpl.extra_categories,
                presentation_point=tmpl.presentation_point,
                priority=tmpl.priority - 20,
                question=make_variant_question(tmpl.question),
                selector=tmpl.selector,
                expected_intent=tmpl.expected_intent,
            ))
        if tmpl.coverage_status in {"partial", "not_answerable"}:
            variants.append(ScenarioTemplate(
                scenario_type=tmpl.scenario_type + "v2",
                persona_type=tmpl.persona_type,
                coverage_status=tmpl.coverage_status,
                required_data_fields=tmpl.required_data_fields,
                mapped_categories=tmpl.mapped_categories,
                missing_data=tmpl.missing_data,
                extra_categories=tmpl.extra_categories,
                presentation_point=tmpl.presentation_point,
                priority=tmpl.priority - 20,
                question=tmpl.question + " 현재 데이터로 어디까지 판단 가능한지도 같이 알려줘요.",
                selector=tmpl.selector,
                expected_intent=tmpl.expected_intent,
            ))
    return variants


def make_variant_question(question: str) -> str:
    if "추천해" in question:
        return question.replace("추천해", "비교해서 추천해")
    if question.endswith("요."):
        return question[:-1] + " 후보별 장단점도 같이 보고 싶어요."
    return question + " 후보별 장단점도 같이 보고 싶어요."


def build_relevant_pool(df: pd.DataFrame, limit: int = 500) -> pd.DataFrame:
    out = df.copy()
    out["matched_signals"] = out.apply(lambda row: "|".join(matched_signals(row)), axis=1)
    out["relevance_score"] = out.apply(relevance_score, axis=1)
    columns = [
        "uuid",
        "district",
        "age",
        "age_group",
        "sex",
        "occupation",
        "occupation_group",
        "family_type",
        "housing_type",
        "housing_tenure",
        "income_bracket",
        "economic_activity_status",
        "matched_signals",
        "relevance_score",
        "persona",
        "detailed_persona",
        "family_persona",
        "finance_persona",
        "healthcare_persona",
        "sports_persona",
        "arts_persona",
        "hobbies_and_interests",
    ]
    existing = [col for col in columns if col in out.columns]
    out = out.sort_values(["relevance_score", "uuid"], ascending=[False, True])
    return out.loc[out["relevance_score"] > 0, existing].head(limit)


def choose_rows_for_template(df: pd.DataFrame, tmpl: ScenarioTemplate, used: set[str], per_template: int) -> list[pd.Series]:
    matches = df[df.apply(tmpl.selector, axis=1)].copy()
    if matches.empty:
        matches = df.copy()
    matches["relevance_score"] = matches.apply(relevance_score, axis=1)
    matches = matches.sort_values(["relevance_score", "uuid"], ascending=[False, True])

    chosen: list[pd.Series] = []
    for _, row in matches.iterrows():
        key = safe(row.get("uuid"))
        if key in used:
            continue
        chosen.append(row)
        used.add(key)
        if len(chosen) >= per_template:
            break
    for _, row in matches.iterrows():
        if len(chosen) >= per_template:
            break
        chosen.append(row)
    return chosen


def scenario_row(index: int, tmpl: ScenarioTemplate, row: pd.Series) -> dict[str, str]:
    return {
        "scenario_id": f"S{index:03d}",
        "scenario_type": tmpl.scenario_type,
        "persona_type": tmpl.persona_type,
        "source_uuid": safe(row.get("uuid")),
        "source_district": safe(row.get("district")),
        "persona_context": persona_context(row),
        "source_persona_summary": source_summary(row),
        "user_question": personalize_question(tmpl.question, row),
        "expected_intent": tmpl.expected_intent,
        "mapped_categories": "|".join(tmpl.mapped_categories),
        "extra_categories": "|".join(tmpl.extra_categories),
        "required_data_fields": "|".join(tmpl.required_data_fields),
        "coverage_status": tmpl.coverage_status,
        "missing_data": "|".join(tmpl.missing_data),
        "mock_or_data_action": action_for_missing(tmpl.missing_data, tmpl.coverage_status),
        "presentation_point": tmpl.presentation_point,
        "selection_priority": str(tmpl.priority),
        "matched_signals": "|".join(matched_signals(row)),
    }


def personalize_question(question: str, row: pd.Series) -> str:
    district = safe(row.get("district")).replace("서울-", "")
    age_group = safe(row.get("age_group"))
    occupation = safe(row.get("occupation"))
    family_type = safe(row.get("family_type"))
    tenure = safe(row.get("housing_tenure"))

    identity = " ".join(part for part in [age_group, occupation] if part)
    living_parts = []
    if district:
        living_parts.append(f"지금은 {district} 쪽에 살고")
    if family_type:
        living_parts.append(f"{family_type} 형태로 지내고")
    if tenure:
        living_parts.append(f"현재 주거는 {tenure}예요")

    if identity and living_parts:
        return f"저는 {identity}이고, {', '.join(living_parts)}. {question}"
    if identity:
        return f"저는 {identity}입니다. {question}"
    if living_parts:
        return f"{', '.join(living_parts)}. {question}"
    return question


def action_for_missing(missing: list[str], status: str) -> str:
    if status == "answerable":
        return "current_schema"
    if status == "clarify":
        return "clarification_flow"
    actions = []
    if any(item in missing for item in ["rent_median", "deposit_median"]):
        actions.append("light_mock_or_public_rent_trend")
    if "door_to_door_commute_time" in missing:
        actions.append("mock_or_transit_api")
    if any(item in missing for item in ["noise_level", "soundproofing"]):
        actions.append("mock_or_mark_schema_gap")
    if "pet_friendly_facilities" in missing:
        actions.append("use_facility_data_plus_mock")
    if any(item in missing for item in ["sunlight_direction", "unit_level_building_data"]):
        actions.append("future_unit_level_data")
    if any(item in missing for item in ["school_access", "childcare_facilities"]):
        actions.append("public_school_childcare_data")
    return "|".join(actions) if actions else "review_needed"


def build_candidates(df: pd.DataFrame, target: int = 84) -> pd.DataFrame:
    templates = expand_templates(build_templates())
    used: set[str] = set()
    rows: list[dict[str, str]] = []
    per_template = 3
    for tmpl in sorted(templates, key=lambda t: t.priority, reverse=True):
        for source_row in choose_rows_for_template(df, tmpl, used, per_template):
            rows.append(scenario_row(len(rows) + 1, tmpl, source_row))
            if len(rows) >= target:
                return pd.DataFrame(rows)
    return pd.DataFrame(rows)


def build_audit(candidates: pd.DataFrame) -> pd.DataFrame:
    audit_columns = [
        "scenario_id",
        "persona_type",
        "user_question",
        "mapped_categories",
        "required_data_fields",
        "coverage_status",
        "missing_data",
        "mock_or_data_action",
        "presentation_point",
    ]
    return candidates[audit_columns].copy()


def select_final_30(candidates: pd.DataFrame) -> pd.DataFrame:
    selected_parts = []

    def base_type(value: str) -> str:
        return value.replace("v2", "")

    def pick_diverse(statuses: set[str], n: int) -> pd.DataFrame:
        pool = candidates[candidates["coverage_status"].isin(statuses)].copy()
        pool["selection_priority_num"] = pool["selection_priority"].astype(int)
        pool["base_type"] = pool["scenario_type"].map(base_type)
        pool = pool.sort_values(["selection_priority_num", "scenario_id"], ascending=[False, True])

        picked_indices: list[int] = []
        seen_base: set[str] = set()
        for idx, row in pool.iterrows():
            base = safe(row.get("base_type"))
            if base in seen_base:
                continue
            picked_indices.append(idx)
            seen_base.add(base)
            if len(picked_indices) >= n:
                break

        if len(picked_indices) < n:
            for idx, _ in pool.iterrows():
                if idx in picked_indices:
                    continue
                picked_indices.append(idx)
                if len(picked_indices) >= n:
                    break

        return pool.loc[picked_indices].drop(columns=["selection_priority_num", "base_type"])

    def pick(status: str, n: int, include_prefixes: list[str] | None = None) -> pd.DataFrame:
        pool = candidates[candidates["coverage_status"] == status].copy()
        if include_prefixes:
            preferred = pool[pool["scenario_type"].str[:3].isin(include_prefixes)]
            rest = pool[~pool.index.isin(preferred.index)]
            pool = pd.concat([preferred, rest], ignore_index=True)
        pool["selection_priority_num"] = pool["selection_priority"].astype(int)
        pool = pool.sort_values(["selection_priority_num", "scenario_id"], ascending=[False, True])
        return pool.head(n).drop(columns=["selection_priority_num"])

    # Preserve the agreed ratio: 18 answerable, 9 partial/not-answerable, 3 clarify.
    selected_parts.append(pick_diverse({"answerable"}, 18))
    selected_parts.append(pick_diverse({"partial", "not_answerable"}, 9))

    selected_parts.append(pick_diverse({"clarify"}, 3))

    final = pd.concat(selected_parts, ignore_index=True)
    final["final_id"] = [f"F{i:02d}" for i in range(1, len(final) + 1)]
    columns = ["final_id"] + [col for col in final.columns if col != "final_id"]
    return final[columns]


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding="utf-8-sig", quoting=csv.QUOTE_MINIMAL)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--candidate-target", type=int, default=84)
    parser.add_argument("--pool-limit", type=int, default=500)
    args = parser.parse_args()

    df = pd.read_csv(args.input)
    relevant_pool = build_relevant_pool(df, limit=args.pool_limit)
    candidates = build_candidates(df, target=args.candidate_target)
    audit = build_audit(candidates)
    final_30 = select_final_30(candidates)

    write_csv(relevant_pool, args.output_dir / "persona_relevant_pool.csv")
    write_csv(candidates, args.output_dir / "persona_scenario_candidates.csv")
    write_csv(audit, args.output_dir / "data_coverage_audit.csv")
    write_csv(final_30, args.output_dir / "persona_scenarios_30.csv")

    print({
        "relevant_pool": len(relevant_pool),
        "candidates": len(candidates),
        "audit": len(audit),
        "final_30": len(final_30),
        "coverage_counts": candidates["coverage_status"].value_counts().to_dict(),
        "final_coverage_counts": final_30["coverage_status"].value_counts().to_dict(),
    })


if __name__ == "__main__":
    main()

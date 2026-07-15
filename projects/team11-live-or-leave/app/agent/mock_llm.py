"""
Mock LLM — 실제 Solar API 호출을 대체하는 결정론적 스텁.

목적: LLM 없이도 ReAct 루프의 흐름(관측→판단→도구호출→종합)을
      끝까지 검증한다. 실제 구현에서는 이 클래스만 Solar API 호출로 교체하면 된다.

입구/출구 두 역할을 규칙 기반으로 흉내낸다:
  - parse_intent: 자연어에서 키워드를 보고 중요도 라벨을 채운다. 구·근처
    하드필터(FilterClause)는 여기 없다 — UI 구조화 입력에서 직접 오므로
    LLM(과 이 mock)이 텍스트에서 추론할 대상이 아니다.
  - explain: 추천지의 실제 지표 수치를 인용해 근거 문장을 만든다.
"""
from __future__ import annotations

from app.agent.unsupported_requirements import (
    detect_unsupported_requirements,
    format_unsupported_requirements,
)
from app.schemas.domain import CATEGORY_CAVEATS
from app.schemas.tools import CategoryPreference, Importance, ParsedIntent

# 키워드 → 카테고리 매핑 (실제 LLM의 의미 이해를 규칙으로 근사)
_KW = {
    "safety": ["안전", "밤", "치안", "범죄", "cctv", "무서"],
    "convenience": ["편의", "편의점", "마트", "병원", "장보", "쇼핑"],
    "mobility": ["지하철", "교통", "출퇴근", "야근", "차 없", "대중교통", "역"],
    "environment": ["공원", "산책", "조용", "자연", "녹지", "한적"],
}

# 카테고리별 기여도가 raw score/가중치 대신 사용자에게 보일 자연어 문장.
# (Step 2/3 UX 개선: 내부 계산은 그대로 두고 문구만 자연어로 바꾼다.)
_CATEGORY_REASON = {
    "safety": "체감 안전도가 높아 늦은 시간에도 비교적 안심하고 다닐 수 있는 동네입니다",
    "convenience": "편의점·마트·병원 같은 생활 편의시설 접근성이 좋습니다",
    "mobility": "대중교통(버스·지하철) 접근성이 좋아 이동 부담이 적습니다",
    "environment": "공원 등 녹지 접근성이 좋아 답답하지 않은 환경입니다",
}

# 자유 텍스트 → 실제 상권업종소분류명 매핑 (닫힌 집합만 사용, LLM이 새 라벨을 지어내지 않게)
_FACILITY_SYNONYMS: dict[str, list[str]] = {
    "버거": ["버거"],
    "햄버거": ["버거"],
    "치킨": ["치킨"],
    "피자": ["피자"],
    "카페": ["카페"],
    "커피": ["카페"],
    "헬스장": ["헬스장"],
    "헬스": ["헬스장"],
    "운동": ["헬스장", "수영장", "종합 스포츠시설"],
    "수영": ["수영장"],
}

def _match_facility_categories(text: str) -> list[str]:
    t = text.lower()
    matched: list[str] = []
    for kw, categories in _FACILITY_SYNONYMS.items():
        if kw in t:
            for c in categories:
                if c not in matched:
                    matched.append(c)
    return matched


class MockLLM:
    def parse_intent(self, text: str) -> ParsedIntent:
        t = text.lower()
        labels: dict[str, Importance] = {}
        for cat, kws in _KW.items():
            hit = sum(1 for k in kws if k in t)
            if hit >= 2:
                labels[cat] = Importance.VERY_HIGH
            elif hit == 1:
                labels[cat] = Importance.HIGH
            else:
                labels[cat] = Importance.NONE

        pref = CategoryPreference(**labels)
        extra = _match_facility_categories(text)

        # 4개 카테고리도 모호하고 업종 언급도 없으면 성향 모호 → 되묻기
        if all(v == Importance.NONE for v in labels.values()) and not extra:
            return ParsedIntent(
                preference=pref,
                needs_clarification=True,
                clarify_question="어떤 점을 가장 중요하게 보세요? (안전 / 편의 / 교통 / 환경)",
            )
        return ParsedIntent(preference=pref, extra_categories=extra)

    def explain(self, user_text: str, result: dict) -> str:
        """출구 역할: 실제 수치 + 선택 근거(가중치·카테고리별 기여도)를 내부적으로만
        참고해 자연어 설명을 만든다. raw score/가중치/기여도 숫자, 영어 카테고리명은
        사용자 문장에 직접 노출하지 않는다 — 그건 지도 hover와 "적용된 필터 검증"
        expander(streamlit_app.py)에 이미 별도로 노출된다."""
        recs = result["recommendations"]
        if not recs:
            return "조건에 맞는 지역을 찾지 못했습니다."

        weights = result.get("weights", {})
        priorities = [c for c, w in sorted(weights.items(), key=lambda x: -x[1]) if w > 0]
        has_extra_facility = any(r.get("extra_facilities") for r in recs)

        blocks = []
        for r in recs:
            raw = r["scores"]["raw"]
            contrib = r.get("contributions", {})
            drivers = [c for c, v in sorted(contrib.items(), key=lambda x: -x[1]) if v > 0][:2]
            reasons = [_CATEGORY_REASON[c] for c in drivers if c in _CATEGORY_REASON]
            if not reasons:
                reasons = ["여러 조건을 고르게 충족하는 동네입니다"]

            parts = [f"**{r['gu']} {r['dong']}**", " ".join(f"{s}." for s in reasons)]

            if "대형병원" in user_text and raw["hosp_cnt"] == 0:
                parts.append("다만 요청하신 대형병원은 근처에서 확인되지 않았습니다.")

            for cat, cnt in r.get("extra_facilities", {}).items():
                if cnt > 0:
                    parts.append(f"요청하신 '{cat}'도 이 동네에 {cnt}곳 있습니다.")
                else:
                    parts.append(f"다만 요청하신 '{cat}'은 이 동네에서는 확인되지 않았습니다.")

            blocks.append("\n".join(parts))

        message = "\n\n".join(blocks)

        # 가중치/기여도 자체는 여전히 "어떤 방법론 각주를 붙일지" 내부 판단에만 쓰고,
        # 사용자에게는 숫자 없는 자연어 각주(caveat)만 보여준다.
        caveats = [CATEGORY_CAVEATS[c] for c in priorities if c in CATEGORY_CAVEATS]
        if has_extra_facility:
            caveats.append("직접 요청하신 업종은 반경 1km가 아니라 해당 행정동에 등록된 업소 수 기준입니다.")
        if caveats:
            message += "\n\n" + "\n".join(f"참고: {c}" for c in caveats)

        unsupported = detect_unsupported_requirements(user_text)
        if unsupported:
            message += "\n\n※ " + format_unsupported_requirements(unsupported)
        return message

    def explain_stream(self, user_text: str, result: dict):
        """SolarLLM.explain_stream과 동일한 인터페이스. 실제 스트리밍 없이
        explain()의 결과를 공백 단위로 잘라 흉내낸다 (SSE 배선을 네트워크 없이 테스트하기 위함)."""
        msg = self.explain(user_text, result)
        words = msg.split(" ")
        for i, word in enumerate(words):
            yield word if i == len(words) - 1 else word + " "

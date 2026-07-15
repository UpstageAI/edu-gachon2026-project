"""
Upstage Solar API 어댑터 — RecommendationAgent(loop.py)의 기본 LLM 구현.

mock_llm.MockLLM과 동일한 인터페이스(parse_intent, explain)를 구현한다.
MockLLM은 프로덕션 경로에서는 더 이상 쓰이지 않고(실제 Solar API 검증 완료),
테스트에서 RecommendationAgent(llm=MockLLM())처럼 명시적으로 주입할 때만 쓰인다.

교체 원칙 (HANDOFF.md 설계원칙 2·3 준수):
  - parse_intent: LLM은 4단계 라벨만 출력. 숫자 생성 금지.
  - explain: 제공된 수치만 근거로. 수치에 없는 내용 추측 금지.
  - 파싱 실패 폴백·합=1 정규화는 서비스 계층(scoring)이 이미 처리.

Solar API는 OpenAI 호환 엔드포인트(https://api.upstage.ai/v1)라 LiteLLM의
openai-compatible 경유(model="openai/<모델명>", api_base 지정)로 호출한다.
litellm import는 _call 안에서 지연 로딩해, 패키지가 없어도 이 모듈을
import하는 데는 지장이 없게 한다.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app.agent.intent_sanitizer import explicitly_requested_categories, should_force_clarification
from app.agent.unsupported_requirements import (
    detect_unsupported_requirements,
    format_unsupported_requirements,
)
from app.data.facility_repository import get_facility_repository
from app.schemas.domain import CATEGORY_CAVEATS
from app.schemas.tools import CategoryPreference, Importance, ParsedIntent

# 프로젝트 루트의 .env (없으면 조용히 무시됨) — UPSTAGE_API_KEY 등을 여기서 읽는다.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

_langfuse_configured = False


def _configure_langfuse_tracing() -> None:
    """LANGFUSE_* 키가 설정된 경우에만 LiteLLM 호출을 Langfuse로 추적한다."""
    global _langfuse_configured
    if _langfuse_configured:
        return
    _langfuse_configured = True
    if not os.environ.get("LANGFUSE_PUBLIC_KEY"):
        return
    import litellm
    litellm.success_callback = ["langfuse"]
    litellm.failure_callback = ["langfuse"]

DEFAULT_MODEL = "solar-pro2-251215"
DEFAULT_API_BASE = "https://api.upstage.ai/v1"

_PARSE_SYSTEM_BASE = """사용자의 동네 선호를 분석해 아래 4개 카테고리의 중요도를
각각 very_high / high / medium / none 중 하나로만 판단해 JSON으로 출력하라.
설명·마크다운 금지. 숫자 금지. 형식:
{"safety":"", "convenience":"", "mobility":"", "environment":"",
 "extra_categories": [], "needs_clarification": false, "clarify_question": null}
- safety: 안전(범죄 적음·CCTV 많음)
- convenience: 편의(편의점·마트·병원)
- mobility: 이동(지하철·버스 접근성)
- environment: 환경(공원·녹지)
- extra_categories: 사용자가 실제 시설/업종명을 명시적으로 말한 경우(예: "버거집",
  "헬스장", "카페")에만 아래 목록에서 골라 채운다. 직업·나이·가구형태 같은 배경
  정보로 업종을 추론하지 말 것. 예: "회계사"라고 해서 "세무사"를 넣지 말 것,
  "편의가 좋다"라고 해서 "편의점"을 넣지 말 것. 목록 밖 문자열 생성 금지:
  __CATEGORIES__
- needs_clarification: 4개 카테고리도 모호하고 업종 요구도 없으면 true,
  clarify_question에 질문

참고: "구 안에서만"/"OO 근처" 같은 지역·거리 조건은 이 텍스트가 아니라 별도
UI(구 선택, 기준 장소 입력)로 사용자가 직접 지정한다 — 여기서는 안전·편의·
이동·환경 선호와 업종 언급만 본다."""

_EXPLAIN_SYSTEM = """아래 추천 동네들의 실제 지표 수치와 선택 근거(사용자 선호 가중치,
각 동네의 카테고리별 기여도)는 왜 이 순서로 추천됐는지 "판단"할 때만 내부적으로
참고하고, 사용자에게 보여줄 문장에는 그 판단 과정을 그대로 드러내지 마라.

절대 사용자 문장에 그대로 쓰지 말 것 (판단 근거로 참고하는 것은 괜찮음):
- 가중치·기여도 숫자 (예: "0.526", "기여도 0.4058")
- 종합 점수 (예: "종합 0.83")
- 범죄율·CCTV·편의점·마트·병원·버스·공원의 실제 개수/대수/곳 수 (예: "공원 24곳",
  "CCTV 766대"). 이건 사용자가 직접 요청한 업종이 아닌, 스코어링에 쓰인 일반
  지표라서 몇 곳/몇 대인지는 절대 쓰지 말고 "많다/좋다/우수하다/부족하다" 같은
  정성적 표현으로만 바꿔 말하라.
- "safety"/"convenience"/"mobility"/"environment" 같은 영어 카테고리명
대신 그 의미를 자연어로 풀어 설명하라.
  나쁜 예: "공원이 24곳 있고 CCTV가 766대로 밀집되어 있어 mobility 가중치 0.526,
  기여도 0.4058로 상위권입니다."
  좋은 예: "대중교통 접근성이 좋아 늦은 퇴근 후에도 이동 부담이 적고, 공원과 녹지도
  풍부해 산책하기 좋습니다."

추천 동네마다 "{구} {동}" 이름을 밝히고 2~3문장으로 왜 추천하는지 설명하라.
사용자가 직접 요청한 업종(예: 버거, 헬스장)은 위 규칙의 예외다 — 이건 스코어링용
일반 지표가 아니라 사용자가 콕 집어 물어본 것이므로, 실제로 몇 곳 있는지 자연스러운
문장으로 언급하고(예: "요청하신 헬스장도 3곳 있습니다"), 0곳이면 반영되지 않았음을
솔직히 명시하라.

각 지표의 방향성(판단에만 참고, 숫자로는 절대 언급하지 말 것):
- 범죄율(crime_rate): 낮을수록 좋음(안전)
- CCTV·편의점·마트·병원·버스·공원 개수: 많을수록/높을수록 좋음
- 지하철 접근성(subway_access, 0~1 값): 1에 가까울수록 좋음(역과 가까움),
  0에 가까울수록 나쁨(역과 멂). "0에 가까울수록 가깝다"처럼 반대로 말하지 말 것.

사용자가 중요하게 본 항목의 지표 산출 방식(예: 구 단위 상속값, 밀도로 정규화됨)에
오해 소지가 있다면 숫자 없이 짧은 자연어로만 짚어줘라(예: "범죄율은 동 단위가 아니라
자치구 전체 평균이 반영된 값입니다").

제공된 수치·안내에 없는 내용은 추측하지 말 것.
요구를 충족하지 못하는 부분은 솔직히 명시할 것.
프롬프트에 "현재 데이터로 직접 평가할 수 없는 사용자 요구"가 포함되어 있으면,
그 항목은 추천 근거로 추정하지 말고 "이 부분은 현재 데이터로 직접 판단하기 어렵습니다"처럼
자연스러운 한계 설명으로 반드시 언급할 것(예: 방음·소음은 현재 데이터로 직접 판단 불가).

출력 직전 스스로 점검할 것: 방금 쓴 문장에 "OO곳"/"OO대"/"OO개"처럼 숫자+단위가
붙은 표현이 있는가? 있다면 그게 사용자가 직접 요청한 업종(예: 헬스장 3곳)이 아닌
이상(공원·CCTV·버스·편의점·마트·병원 등 일반 지표라면) 반드시 숫자를 지우고
"풍부하다/많다/좋다/부족하다" 같은 정성적 표현으로 다시 써라. 공원 개수도 예외 없이
이 규칙을 따른다(예: "공원 24곳" 금지 → "공원 등 녹지가 풍부"로)."""


def _build_parse_system() -> str:
    categories = ", ".join(sorted(get_facility_repository().categories()))
    return _PARSE_SYSTEM_BASE.replace("__CATEGORIES__", categories)


class SolarLLM:
    def __init__(self, model: str | None = None):
        self.model = model or os.environ.get("SOLAR_MODEL", DEFAULT_MODEL)
        self.api_base = os.environ.get("UPSTAGE_API_BASE", DEFAULT_API_BASE)
        self.api_key = os.environ.get("UPSTAGE_API_KEY")

    def _call(self, system: str, user: str) -> str:
        if not self.api_key:
            raise RuntimeError("UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.")

        import litellm  # 지연 로딩: mock만 쓰는 환경에서는 패키지가 없어도 무방
        _configure_langfuse_tracing()

        resp = litellm.completion(
            model=f"openai/{self.model}",
            api_base=self.api_base,
            api_key=self.api_key,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.1,  # 재현성 위해 낮게
            num_retries=2,  # 일시적 connection error 대비 (HANDOFF.md 트러블슈팅 참고)
        )
        return resp.choices[0].message.content

    def _call_stream(self, system: str, user: str):
        """explain_stream()용 토큰 스트리밍 호출. 제너레이터라 첫 next() 호출 전까지는
        본문이 실행되지 않으므로, api_key 누락 에러도 실제 반복(iterate) 시점에 발생한다."""
        if not self.api_key:
            raise RuntimeError("UPSTAGE_API_KEY 환경변수가 설정되지 않았습니다.")

        import litellm  # 지연 로딩: mock만 쓰는 환경에서는 패키지가 없어도 무방
        _configure_langfuse_tracing()

        response = litellm.completion(
            model=f"openai/{self.model}",
            api_base=self.api_base,
            api_key=self.api_key,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": user}],
            temperature=0.1,
            num_retries=2,
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta

    def parse_intent(self, text: str) -> ParsedIntent:
        """구·근처 하드필터(FilterClause)는 이 메서드가 아예 모른다 — UI의
        구조화 입력에서 직접 오고(loop.py 참고), 여기선 4개 카테고리 선호와
        extra_categories(선택 언급 업종)만 파싱한다. 하드필터를 LLM이 텍스트에서
        추론할 기회 자체가 없으니, "선택 문장이 필수로 오인식"되는 부류의 버그가
        구조적으로 발생할 수 없다."""
        raw = self._call(_build_parse_system(), text)
        try:
            data = json.loads(raw.strip().strip("`").lstrip("json").strip())
            # 모델이 "언급 안 된 카테고리"를 프롬프트 지시(4단계 라벨 중 하나)를
            # 어기고 빈 문자열로 채우는 경우가 실측됨(예: safety=""). 빈 값·누락은
            # "none"(관계없음)으로 관대하게 처리한다 — 안 그러면 Importance("")가
            # ValueError를 던져 이 함수 전체가 except로 떨어지고, 카테고리 3개는
            # 이미 잘 파싱됐어도(예: environment=high) 전부 버려진 채 강제
            # 되묻기로 빠진다(부분 파싱 실패가 전체 실패로 확대되는 문제).
            pref = CategoryPreference(
                safety=Importance(data.get("safety") or "none"),
                convenience=Importance(data.get("convenience") or "none"),
                mobility=Importance(data.get("mobility") or "none"),
                environment=Importance(data.get("environment") or "none"),
            )
            categories = get_facility_repository().categories()
            extra = [c for c in data.get("extra_categories", []) if c in categories]
            extra = explicitly_requested_categories(text, extra)

            needs_clarification = bool(data.get("needs_clarification", False))
            clarify_question = data.get("clarify_question")
            if not extra and should_force_clarification(text, extra):
                needs_clarification = True
                clarify_question = (
                    "어떤 기준을 가장 중요하게 볼까요? "
                    "(안전 / 교통 / 생활 편의 / 공원·환경 / 예산 등)"
                )

            return ParsedIntent(
                preference=pref,
                extra_categories=extra,
                needs_clarification=needs_clarification,
                clarify_question=clarify_question,
            )
        except Exception:
            # 폴백: 파싱 실패 시 되묻기 (scoring이 균등분배도 처리 가능)
            return ParsedIntent(
                preference=CategoryPreference(
                    safety=Importance.NONE, convenience=Importance.NONE,
                    mobility=Importance.NONE, environment=Importance.NONE),
                needs_clarification=True,
                clarify_question="어떤 점을 가장 중요하게 보세요? (안전/편의/교통/환경)",
            )

    def _build_explain_prompt(self, user_text: str, result: dict) -> tuple[str, str] | None:
        """explain/explain_stream 공용 프롬프트 빌더. 추천이 없으면 None(고정 문구로 대체)."""
        recs = result["recommendations"]
        if not recs:
            return None
        # 추천지 실제 수치 + 선택 근거(가중치·기여도)를 프롬프트에 담아 근거 강제
        weights = result.get("weights", {})
        priorities = [c for c, w in sorted(weights.items(), key=lambda x: -x[1]) if w > 0]
        facts = [f"사용자 선호 가중치: {weights}"]
        caveats = [CATEGORY_CAVEATS[c] for c in priorities if c in CATEGORY_CAVEATS]
        if any(r.get("extra_facilities") for r in recs):
            caveats.append("직접 요청하신 업종은 반경 1km가 아니라 해당 행정동에 등록된 업소 수 기준입니다.")
        if caveats:
            facts.append("지표 가공 방식 안내: " + " / ".join(caveats))
        unsupported = detect_unsupported_requirements(user_text)
        if unsupported:
            facts.append(
                "현재 데이터로 직접 평가할 수 없는 사용자 요구: "
                + format_unsupported_requirements(unsupported)
            )
        for r in recs:
            raw = r["scores"]["raw"]
            facts.append(
                f"{r['gu']} {r['dong']} (종합 {r['total_score']}, "
                f"카테고리별 기여도 {r.get('contributions', {})}, "
                f"요청 업종 현황 {r.get('extra_facilities', {})}): "
                f"범죄율 {raw['crime_rate']}/만명, "
                f"CCTV {raw['cctv_cnt']}, 편의점 {raw['conv_cnt']}, 마트 {raw['mart_cnt']}, "
                f"병원 {raw['hosp_cnt']}, 버스 {raw['bus_cnt']}, "
                f"지하철접근성 {raw['subway_access']}, 공원 {raw['park_cnt']}")
        user = f"사용자 요구: {user_text}\n추천지 지표:\n" + "\n".join(facts)
        return _EXPLAIN_SYSTEM, user

    def explain(self, user_text: str, result: dict) -> str:
        prompt = self._build_explain_prompt(user_text, result)
        if prompt is None:
            return "조건에 맞는 지역을 찾지 못했습니다."
        return self._call(*prompt)

    def explain_stream(self, user_text: str, result: dict):
        """SSE 컨트롤러용 토큰 스트리밍 버전. 청크(str)를 순서대로 yield한다."""
        prompt = self._build_explain_prompt(user_text, result)
        if prompt is None:
            yield "조건에 맞는 지역을 찾지 못했습니다."
            return
        yield from self._call_stream(*prompt)

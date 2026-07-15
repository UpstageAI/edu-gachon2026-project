"""
ReAct 루프 오케스트레이터.

흐름: 관측(사용자 입력) → 판단(입구 LLM 의도 파싱)
      → [모호하면 되묻기 1회로 종료]
      → 행동(recommend 도구 호출) → 관측(결과)
      → 종합(출구 LLM 근거 설명)

앞선 논의대로 '도구 자율 연쇄'는 절제한다. 흐름은 입구→도구→출구로 고정하되,
되묻기라는 최소한의 agentic 분기만 둔다. max_steps로 무한 루프를 차단한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.agent.solar_llm import SolarLLM
from app.agent.tools import ToolExecutor
from app.data.csv_repository import CsvDongRepository
from app.schemas.tools import FilterClause, RecommendTool


@dataclass
class AgentResult:
    kind: str                       # "recommendation" | "clarify"
    message: str
    trace: list[str] = field(default_factory=list)  # ReAct 관측/행동 로그
    data: dict | None = None


class RecommendationAgent:
    def __init__(self, llm=None, max_steps: int = 4):
        repo = CsvDongRepository()
        # 프로덕션 기본값은 실제 Solar API. llm=MockLLM() 등으로 테스트에서만 교체.
        self.llm = llm or SolarLLM()
        self.tools = ToolExecutor(repo)
        self.max_steps = max_steps

    def run(
        self, user_text: str, top_n: int = 3,
        required_filters: list[FilterClause] | None = None,
    ) -> AgentResult:
        """top_n을 늘리면(예: 지도용 전체 스코어링) data에는 top_n개가 다 담기지만,
        출구 LLM 설명(explain)은 항상 상위 3개만 근거로 삼는다 — 425개를 전부
        자연어로 설명하는 건 낭비고 의미도 없다.

        required_filters(구·근처 하드필터)는 LLM이 아니라 호출부(UI의 구조화
        입력)가 직접 준다 — parse_intent는 이제 선호(가중치)·extra_categories만
        본다. LLM이 하드필터를 판단할 기회 자체가 없으니 "선택 텍스트가 필수로
        오인식되는" 부류의 버그가 이 경로에서는 구조적으로 불가능하다."""
        trace: list[str] = []
        steps = 0

        # --- 판단: 입구 LLM 의도 파싱 (선호·extra_categories만) ---
        steps += 1
        intent = self.llm.parse_intent(user_text)
        trace.append(f"[step {steps}] parse_intent → {intent.preference.model_dump()} "
                     f"(extra={intent.extra_categories}, "
                     f"clarify={intent.needs_clarification})")

        # --- agentic 분기: 모호하면 되묻기로 종료. 구·근처 구조화 입력이
        # 있어도 LLM이 모호하다고 판단하면 되묻는다 — 필터가 "이 동네를 찾는
        # 기준"은 될 수 있어도 "선호(가중치)가 명확하다"는 보장은 아니다. ---
        if intent.needs_clarification:
            trace.append(f"[step {steps}] needs_clarification → 되묻기 반환")
            return AgentResult(
                kind="clarify",
                message=intent.clarify_question or "조금 더 구체적으로 알려주세요.",
                trace=trace,
            )

        # --- 행동: recommend 도구 호출 ---
        steps += 1
        if steps > self.max_steps:
            return AgentResult(kind="clarify", message="처리 한도를 초과했습니다.", trace=trace)
        tool_args = RecommendTool(
            preference=intent.preference,
            extra_categories=intent.extra_categories,
            required_filters=required_filters or [],
            top_n=top_n,
        )
        # stream()은 이 구간 실패를 이미 SSE error 이벤트로 우아하게 처리하지만,
        # run()(Streamlit이 씀)은 이 보호막이 없어서 Kakao 호출 한도 초과 같은
        # 일시적 도구 실패가 그대로 위로 튀어 Streamlit 스크립트 전체가 죽었다.
        # data 없이도 UI가 이미 처리할 줄 아는 kind="clarify" 경로로 우아하게 종료한다.
        try:
            result = self.tools.recommend(tool_args)
        except Exception as e:
            trace.append(f"[step {steps}] tool:recommend → 실패 ({e!r})")
            return AgentResult(
                kind="clarify",
                message="일시적으로 조건을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.",
                trace=trace,
            )
        top = [r["gu"] for r in result["recommendations"][:3]]
        trace.append(f"[step {steps}] tool:recommend → "
                     f"required_filters(구조화 입력)="
                     f"{[c.model_dump(exclude_none=True) for c in tool_args.required_filters]}, "
                     f"weights={result['weights']} top={top}")

        # --- 종합: 출구 LLM 근거 설명 (항상 상위 3개만) ---
        steps += 1
        explain_input = {**result, "recommendations": result["recommendations"][:3]}
        # 여기서 실패해도 스코어링 결과(data)는 이미 유효하다 — 지도는 그대로
        # 보여주고 문구만 안내문으로 대체한다(추천 결과 자체를 버리지 않는다).
        try:
            message = self.llm.explain(user_text, explain_input)
            trace.append(f"[step {steps}] explain → 근거 설명 생성 (상위 {len(top)}건)")
        except Exception as e:
            trace.append(f"[step {steps}] explain → 실패, 안내 문구로 대체 ({e!r})")
            message = "추천 동네는 찾았지만 설명 문구 생성에 실패했습니다. 아래 지도를 참고해주세요."

        return AgentResult(
            kind="recommendation", message=message, trace=trace, data=result
        )

    def stream(
        self, user_text: str, top_n: int = 3,
        required_filters: list[FilterClause] | None = None,
    ):
        """SSE 컨트롤러(main.py)용 제너레이터 버전의 run().

        run()과 동일한 흐름(파싱→[되묻기]→도구→설명)을 따르되, 설명 단계를
        토큰 단위 이벤트로 흘려보낸다. 실패해도 예외를 밖으로 던지지 않고
        {"type": "error"} 이벤트로 알린다 — SSE는 응답이 이미 시작된 상태라
        HTTP 상태 코드로는 실패를 표현할 수 없기 때문이다.

        top_n을 늘리면(예: 지도 API 소비자) meta.data.recommendations에는
        top_n개가 다 담기지만, run()과 마찬가지로 설명(explain_stream)은
        항상 상위 3개만 근거로 삼는다 — 안 그러면 top_n=500일 때 프롬프트에
        500개 동네 원본 수치를 통째로 실어보내게 된다.

        required_filters는 run()과 동일하게 호출부(UI)가 직접 준다.

        이벤트 종류: meta(kind/trace/[data]) → delta(text)* → done, 또는 error(message).
        """
        trace: list[str] = []
        try:
            steps = 1
            intent = self.llm.parse_intent(user_text)
            trace.append(f"[step {steps}] parse_intent → {intent.preference.model_dump()} "
                         f"(extra={intent.extra_categories}, "
                         f"clarify={intent.needs_clarification})")

            if intent.needs_clarification:
                trace.append(f"[step {steps}] needs_clarification → 되묻기 반환")
                yield {"type": "meta", "kind": "clarify", "trace": list(trace)}
                yield {"type": "delta", "text": intent.clarify_question or "조금 더 구체적으로 알려주세요."}
                yield {"type": "done"}
                return

            steps += 1
            if steps > self.max_steps:
                yield {"type": "meta", "kind": "clarify", "trace": list(trace)}
                yield {"type": "delta", "text": "처리 한도를 초과했습니다."}
                yield {"type": "done"}
                return
            tool_args = RecommendTool(
                preference=intent.preference,
                extra_categories=intent.extra_categories,
                required_filters=required_filters or [],
                top_n=top_n,
            )
            result = self.tools.recommend(tool_args)
            top = [r["gu"] for r in result["recommendations"][:3]]
            trace.append(f"[step {steps}] tool:recommend → "
                         f"required_filters(구조화 입력)="
                         f"{[c.model_dump(exclude_none=True) for c in tool_args.required_filters]}, "
                         f"weights={result['weights']} top={top}")

            steps += 1
            trace.append(f"[step {steps}] explain_stream → 근거 설명 스트리밍 시작 (상위 {len(top)}건)")
            yield {"type": "meta", "kind": "recommendation", "trace": list(trace), "data": result}

            explain_input = {**result, "recommendations": result["recommendations"][:3]}
            for chunk in self.llm.explain_stream(user_text, explain_input):
                yield {"type": "delta", "text": chunk}

            yield {"type": "done"}
        except Exception as e:
            yield {"type": "error", "message": str(e)}

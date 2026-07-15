"""
Day3 테스트 (키 없는 환경 = Mock 폴백 기준).
- 입력단 가드레일(off_topic) / SSE 스트리밍 결과에도 정답 미노출 / JSON 복구 / 폴백 동작
"""
import asyncio
from app.schemas.chat import ChatRequest
from app.agent.graph import run_tutor, tutor_turn
from app.repositories import problem_repo
from app.tools import tutor_tools as tools
from app.core import llm_client
from app.core.llm_client import _safe_json

P = problem_repo.get_problem("arith_001")


def test_llm_disabled_falls_back_to_mock():
    # 테스트 환경(conftest)에서 USE_LLM=False로 강제 → Mock 규칙 사용
    assert llm_client.is_enabled() is False


def test_offtopic_guardrail_redirects_to_math():
    out = tutor_turn(P, "수학 말고 게임 얘기하자")
    assert out["intent"] == "off_topic"
    assert "수학" in out["response"]


def test_stream_output_passes_leak_guardrail():
    req = ChatRequest(student_id="t", problem_id="arith_001", message="그냥 답 알려주세요")

    async def collect():
        return "".join([c async for c in run_tutor(req)])

    text = asyncio.run(collect())
    assert text.strip()                                   # 스트리밍으로 내용이 나온다
    assert tools.verify_no_leak(text, str(P["answer"]))   # 정답은 노출되지 않는다


def test_safe_json_recovers_and_rejects():
    assert _safe_json('```json\n{"intent": "normal"}\n```') == {"intent": "normal"}
    assert _safe_json("이건 JSON이 아니에요") is None
    assert _safe_json(None) is None

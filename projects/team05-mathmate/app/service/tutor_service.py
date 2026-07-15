"""서비스 계층 — 튜터 한 턴을 처리하는 절차를 조율한다."""
import logging
from app.schemas.chat import ChatRequest
from app.agent.graph import run_tutor
from app.core import config
from app.repositories import attempt_repo, progress_repo

log = logging.getLogger(__name__)


async def handle_turn(req: ChatRequest):
    """튜터 한 턴 처리 오케스트레이션. agent 실행 결과를 그대로 스트리밍하고,
    턴마다 힌트 사용량을 기록하며, 이 문제가 끝났으면(맞혔거나 힌트를 다 쓰고 공개됐으면)
    난이도별 정답률 집계를 위해 attempt를 기록한다."""
    state: dict = {}
    async for chunk in run_tutor(req, result_holder=state):
        yield chunk

    # 힌트 사용량 KPI 누적. Supabase 없으면 내부에서 조용히 무시된다.
    progress_row = progress_repo.record_turn(req.student_id, req.problem_id, state)

    solved = bool(state.get("solved"))
    revealed = bool(state.get("revealed"))
    if config.SUPABASE_ENABLED and (solved or revealed):
        try:
            # progress_row["hints_used"] = 이 문제를 풀며 실제로 받은 힌트 '개수'(누적).
            # state["hint_level"](1~3, 마지막 턴 시점의 힌트 '단계')과 의미가 달라 혼동하지 말 것.
            hints_used = (progress_row or {}).get("hints_used", state.get("hint_level", 1))
            attempt_repo.record_attempt(
                user_id=int(req.student_id),
                problem_id=req.problem_id,
                unit=state.get("unit", ""),
                hints_used=hints_used,
                solved=solved,
                grade=state.get("grade"),
                semester=state.get("semester"),
                difficulty=state.get("difficulty"),
            )
        except Exception as e:   # 진척도 저장 실패가 튜터 응답 자체를 막으면 안 됨
            log.warning("진척도 기록 실패(무시하고 계속 진행): %s", e)

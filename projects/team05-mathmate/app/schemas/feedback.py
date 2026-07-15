"""단원별 진척도(피드백) 스키마."""
from pydantic import BaseModel


class UnitMastery(BaseModel):
    unit: str
    problems_attempted: int             # 스스로 해결한 문제 수
    avg_hints_used: float | None        # 스스로 해결한 문제의 평균 힌트 수(해결한 게 없으면 None)
    mastery_level: str
    revealed_count: int = 0             # 힌트를 다 쓰고 튜터가 정답을 공개한 문제 수
    success_rate: float = 0.0           # 스스로 해결 / 전체 시도(해결+공개) 비율(%) — 취약 단원 판단 기준
    accuracy_by_difficulty: dict[str, float | None] = {}   # 이 단원 안에서의 난이도별 정답률(%)


class OverallSummary(BaseModel):
    total_attempts: int
    total_hints_used: int
    accuracy_by_difficulty: dict[str, float | None]   # {"쉬움": .., "중간": .., "어려움": ..}
    message: str


class FeedbackResponse(BaseModel):
    summary: OverallSummary
    items: list[UnitMastery]
    weakest_unit: str | None

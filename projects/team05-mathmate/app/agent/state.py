"""LangGraph State — 노드 사이 공유 데이터.
팀원 초안 필드를 유지하고, 병합에 필요한 response/solved 를 추가했다.
"""
from typing import TypedDict


class TutorState(TypedDict, total=False):
    messages: list          # 대화 이력 (Sliding Window: Day5)
    problem: dict           # 현재 문제 (problems.sample.json 한 항목)
    answer: str             # 정답 (유출 검증용, 학생 노출 금지)
    student_attempt: str    # 학생의 최근 풀이/답
    intent: str             # normal | answer_seeking | off_topic
    diagnosis: dict         # {stuck_point, is_correct, solved}
    hint_level: int         # 이번 턴에 줄 힌트 구체화 단계 (1~3)
    prior_hint_level: int   # 이전 턴들까지 도달했던 최고 힌트 단계 (Supabase progress에서 조회, 없으면 0)
    hint: str               # 생성된 힌트
    response: str           # 학생에게 보낼 최종 문장
    leak_check: bool        # 정답 유출 검증 결과 (True=안전)
    solved: bool            # 최종 정답 도달 여부
    revealed: bool          # 힌트 3단계를 다 쓰고도 못 풀어 정답을 공개했는지

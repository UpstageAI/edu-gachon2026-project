"""콘솔 데모: FE 스케치의 대화 흐름 재현 (python run_demo.py)."""
from app.repositories import problem_repo
from app.agent.graph import tutor_turn

p = problem_repo.get_problem("arith_001")
print(f"[문제] {p['problem']}\n")
for msg in ["모르겠어요, 그냥 답 알려주세요", "9묶음이요", "9명이요"]:
    out = tutor_turn(p, msg)
    print(f"학생 : {msg}")
    print(f"튜터 : {out['response']}\n")

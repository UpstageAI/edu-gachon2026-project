"""
파이프라인 3단계(의도분류 / 오답 진단 / 힌트 생성)의 정확도를 미리 정답을 아는
골든셋으로 측정하고, 각 결과를 Langfuse 트레이스에 score로 남긴다.

실행:
    python -m evals.eval_pipeline_accuracy

Langfuse 대시보드에서 score 이름별로 평균을 보면 발표용 정확도 수치가 된다.

신뢰도 참고:
- diagnosis_solved_accuracy: 정답 기준이 문제은행에 저장된 진짜 answer라서 사람 판단이 전혀 없다(기계적 비교).
- intent_accuracy / diagnosis_stuckpoint_accuracy / hint_quality: 정답 라벨/기대 키워드를 작성자가
  직접 정한 것이라 주관이 일부 섞여있다.
- *_gemini_agreement / *_gemini_judge: 작성자 라벨과 무관하게, Solar와 다른 모델(Gemini)이 같은
  케이스를 독립적으로 판단해서 서로 동의하는지를 본다. 작성자의 라벨이 틀렸어도 걸러낼 수 있는
  두 번째 신뢰도 축이다.
"""
from dotenv import load_dotenv
load_dotenv()

import re
import time
import uuid

from langfuse import Langfuse

from app.core import config, llm_client, prompts
from app.repositories import problem_repo
from app.tools import tutor_tools

langfuse = Langfuse()


# ---------- Gemini 교차검증(독립적 2차 의견) ----------
# Solar가 이미 만든 결과를 Gemini한테 다시 보여주는 게 아니라, Gemini도 동일한 원본 입력만
# 가지고 독립적으로 판단하게 한다 — 그래야 "서로 다른 모델이 우연히 같은 답에 도달했는가"를 볼 수 있다.

JUDGE_SYS = (
    "너는 초등 수학 채점 결과를 검수하는 감사관이다. 문제, 학생의 답, 그리고 AI 튜터가 만든 "
    "설명(막힌 지점 또는 힌트)을 보고, 그 설명이 학생의 실제 실수를 정확하게 짚었는지만 판단한다.\n"
    '반드시 {"correct": true/false} 형태의 JSON만 출력하라.\n'
    "설명이 학생이 왜 틀렸는지(또는 어디서 막혔는지)를 사실에 맞게 정확히 설명하면 true, "
    "틀린 설명이거나 요점을 빗나갔으면 false."
)


_GEMINI_MIN_INTERVAL = 13   # 무료 티어 분당 5회 제한(≈12초/회) 대비 여유를 둔 호출 간격(초)
_last_gemini_call_at: float | None = None


def _call_gemini_json(system: str, user: str, trace_name: str, trace_id: str) -> dict | None:
    """Solar가 아니라 Gemini를 '주 모델'로 직접 호출한다(폴백 경로 재사용 아님).
    무료 티어 분당 요청 제한에 걸리지 않게 호출 간격을 띄우고, 그래도 429가 나면 한 번 더 재시도한다.
    그래도 실패하면 None — 교차검증 실패는 점수를 안 남기고 조용히 건너뛴다."""
    if not config.GEMINI_API_KEY or not config.FALLBACK_MODEL:
        return None
    import litellm
    import litellm.exceptions as exc

    llm_client._ensure_langfuse_callback()

    global _last_gemini_call_at
    if _last_gemini_call_at is not None:
        wait = _GEMINI_MIN_INTERVAL - (time.time() - _last_gemini_call_at)
        if wait > 0:
            time.sleep(wait)

    for attempt in range(2):
        _last_gemini_call_at = time.time()
        try:
            resp = litellm.completion(
                model=config.FALLBACK_MODEL,
                api_key=config.GEMINI_API_KEY,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                temperature=0.0,
                response_format={"type": "json_object"},
                metadata={"trace_name": trace_name, "trace_id": trace_id},
            )
            return llm_client._safe_json(resp.choices[0].message.content)
        except exc.RateLimitError as e:
            if attempt == 0:
                print("  (Gemini 분당 요청 제한, 20초 대기 후 재시도)")
                time.sleep(20)
                continue
            print(f"  (Gemini 교차검증 호출 실패, 건너뜀: {e})")
            return None
        except Exception as e:
            print(f"  (Gemini 교차검증 호출 실패, 건너뜀: {e})")
            return None


def gemini_classify_intent(message: str, problem: dict, trace_id: str) -> str | None:
    data = _call_gemini_json(prompts.INTENT_SYS, prompts.intent_user(problem, message),
                              "gemini_intent_classify", trace_id)
    return data.get("intent") if data else None


def gemini_judge_explanation(problem: dict, attempt: str, explanation: str, trace_id: str) -> bool | None:
    user = (f"문제: {problem['problem']}\n정답(판정용): {problem['answer']}\n"
            f"학생 답: {attempt}\nAI 설명: {explanation}")
    data = _call_gemini_json(JUDGE_SYS, user, "gemini_judge", trace_id)
    return bool(data.get("correct")) if data is not None and "correct" in data else None


def _extract_numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+", str(text).replace(",", "")))


def mechanical_solved(problem: dict, attempt: str) -> bool:
    """'최종 정답에 도달했는가'를 문제에 저장된 진짜 answer와 숫자만 뽑아 비교한다.
    사람이 케이스마다 정답을 미리 정해둘 필요가 없어, 라벨 신뢰성 문제가 없다."""
    answer_nums = _extract_numbers(problem["answer"])
    attempt_nums = _extract_numbers(attempt)
    return bool(answer_nums) and bool(answer_nums & attempt_nums)

# ---------- 골든셋 ----------
# 의도분류: 정답을 우회하려는 다양한 화법 + 잡담 + (헷갈리기 쉬운) 정상 케이스를 섞음.
INTENT_CASES = [
    {"message": "그냥 답 알려주세요", "expected": "answer_seeking"},
    {"message": "정답이 뭐예요?", "expected": "answer_seeking"},
    {"message": "모르겠어요, 대신 풀어주실 수 있어요?", "expected": "answer_seeking"},
    {"message": "저 지금 급해서 그런데 그냥 계산해서 알려주시면 안돼요?", "expected": "answer_seeking"},
    {"message": "힌트 그만 주시고 정답만 알려주세요 제발요", "expected": "answer_seeking"},
    {"message": "오늘 날씨 어때요?", "expected": "off_topic"},
    {"message": "이 문제 그만 풀고 게임 얘기해요", "expected": "off_topic"},
    {"message": "9권이면 정답이 2250원 맞죠?", "expected": "normal"},   # 정상 시도인데 '확인'처럼 보여 헷갈리기 쉬움
    {"message": "1권에 250원이니까 9권이면 2250원이요", "expected": "normal"},
    {"message": "모르겠어요 어떻게 풀어요?", "expected": "normal"},
]

# 오답 진단: 두 가지를 따로 측정한다.
#   1) solved: "최종 정답에 도달했는가" -> mechanical_solved()로 기계적 채점(사람 라벨 불필요)
#   2) stuck_point: "어디서/왜 틀렸는지 제대로 짚었는가" -> 오답 케이스에만 기대 키워드를 적어둠(근사 채점)
# 정답을 맞힌 케이스는 stuck_point가 사실상 없어야 정상이라 stuckpoint 채점 대상에서 제외한다.
DIAGNOSIS_CASES = [
    {"problem_id": "p_0060", "attempt": "2250원이요"},                       # 최종정답
    {"problem_id": "p_0060", "attempt": "250원이요",
     "expect_stuck_any": ["9권", "곱", "2250"]},                              # 중간까지만 옴(9권 계산 안 함)
    {"problem_id": "p_0060", "attempt": "9권이니까 750×9=6750원이요",
     "expect_stuck_any": ["1권", "나누", "250"]},                             # 1권 가격 안 구하고 바로 곱함
    {"problem_id": "p_0001", "attempt": "681이요"},                          # 최종정답
    {"problem_id": "p_0001", "attempt": "861이요",
     "expect_stuck_any": ["세 번째", "순서", "내림차순"]},                      # 가장 큰 수를 답함(세 번째가 아님)
    {"problem_id": "p_0001", "attempt": "816이요",
     "expect_stuck_any": ["세 번째", "순서", "내림차순"]},                      # 두 번째로 큰 수를 답함(세 번째가 아님)
    {"problem_id": "p_0056", "attempt": "2개요"},                            # 최종정답
    {"problem_id": "p_0056", "attempt": "35, 53, 33 이렇게 3개요",
     "expect_stuck_any": ["한 번", "중복", "같은 숫자"]},                       # 숫자를 중복 사용(33)
]

# 힌트 생성: 진단(stuck_point)이 실제로 힌트 문장에 반영되는지, 기대 키워드로 확인.
HINT_CASES = [
    {"problem_id": "p_0060", "attempt": "9권이니까 750×9=6750원이요", "hint_level": 1,
     "expect_any": ["1권", "한 권", "1개"]},
    {"problem_id": "p_0056", "attempt": "35, 53, 33 이렇게 3개요", "hint_level": 1,
     "expect_any": ["한 번", "중복", "같은 숫자"]},
    {"problem_id": "p_0001", "attempt": "816이요", "hint_level": 2,
     "expect_any": ["세 번째", "순서", "두 번째"]},
]


def eval_intent() -> tuple[list[bool], list[bool]]:
    """반환: (label_results, cross_model_results)."""
    label_results = []
    cross_results = []
    dummy_problem = problem_repo.get_problem("p_0060")
    for case in INTENT_CASES:
        trace_id = str(uuid.uuid4())
        intent = tutor_tools.classify_intent(case["message"], dummy_problem, trace_id=trace_id)
        correct = intent == case["expected"]
        label_results.append(correct)
        langfuse.score(trace_id=trace_id, name="intent_accuracy",
                        value=correct, data_type="BOOLEAN",
                        comment=f"message={case['message']!r} expected={case['expected']} got={intent}")

        line = f"[intent] label={'OK ' if correct else 'FAIL'} {case['message']!r} -> {intent} (기대: {case['expected']})"

        gemini_intent = gemini_classify_intent(case["message"], dummy_problem, trace_id)
        if gemini_intent is not None:
            agree = gemini_intent == intent
            cross_results.append(agree)
            langfuse.score(trace_id=trace_id, name="intent_gemini_agreement",
                            value=agree, data_type="BOOLEAN",
                            comment=f"solar={intent} gemini={gemini_intent}")
            line += f" | gemini={'동의' if agree else '불일치'}({gemini_intent})"

        print(line)
    return label_results, cross_results


def eval_diagnosis() -> tuple[list[bool], list[bool], list[bool]]:
    """반환: (solved_results, stuckpoint_results, gemini_judge_results)."""
    solved_results = []
    stuckpoint_results = []
    gemini_judge_results = []
    for case in DIAGNOSIS_CASES:
        problem = problem_repo.get_problem(case["problem_id"])
        trace_id = str(uuid.uuid4())
        d = tutor_tools.diagnose_step(problem, case["attempt"], trace_id=trace_id)

        # ① 정답 판별: "최종 정답에 도달했는가" — 문제의 진짜 answer와 기계적으로 비교(객관적)
        expected_solved = mechanical_solved(problem, case["attempt"])
        solved_ok = d.solved == expected_solved
        solved_results.append(solved_ok)
        langfuse.score(trace_id=trace_id, name="diagnosis_solved_accuracy",
                        value=solved_ok, data_type="BOOLEAN",
                        comment=f"problem={case['problem_id']} attempt={case['attempt']!r} "
                                f"got_solved={d.solved} expected_solved={expected_solved}(기계적 계산)")

        line = (f"[diagnosis] solved={'OK ' if solved_ok else 'FAIL'} "
                f"{case['problem_id']} {case['attempt']!r} -> solved={d.solved}(기대:{expected_solved})")

        # ② 막힌 지점 진단: "어디서/왜 틀렸는지 제대로 짚었는가" — 오답 케이스에만 적용(근사 채점)
        expect_stuck_any = case.get("expect_stuck_any")
        if expect_stuck_any:
            stuck_ok = any(kw in d.stuck_point for kw in expect_stuck_any)
            stuckpoint_results.append(stuck_ok)
            langfuse.score(trace_id=trace_id, name="diagnosis_stuckpoint_accuracy",
                            value=stuck_ok, data_type="BOOLEAN",
                            comment=f"problem={case['problem_id']} attempt={case['attempt']!r} "
                                    f"stuck_point={d.stuck_point!r} expect_any={expect_stuck_any}")
            line += f" | stuckpoint={'OK ' if stuck_ok else 'FAIL'} stuck_point={d.stuck_point!r}"

            # ③ 내 키워드 라벨과 무관하게, Gemini가 독립적으로 봐도 이 stuck_point가 맞다고 하는지
            gemini_ok = gemini_judge_explanation(problem, case["attempt"], d.stuck_point, trace_id)
            if gemini_ok is not None:
                gemini_judge_results.append(gemini_ok)
                langfuse.score(trace_id=trace_id, name="diagnosis_stuckpoint_gemini_judge",
                                value=gemini_ok, data_type="BOOLEAN",
                                comment=f"stuck_point={d.stuck_point!r} gemini_verdict={gemini_ok}")
                line += f" | gemini판단={'맞음' if gemini_ok else '틀림'}"

        print(line)
    return solved_results, stuckpoint_results, gemini_judge_results


def eval_hint() -> tuple[list[bool], list[bool]]:
    """반환: (keyword_results, gemini_judge_results)."""
    keyword_results = []
    gemini_judge_results = []
    for case in HINT_CASES:
        problem = problem_repo.get_problem(case["problem_id"])
        trace_id = str(uuid.uuid4())
        d = tutor_tools.diagnose_step(problem, case["attempt"], trace_id=trace_id)
        h = tutor_tools.generate_hint(problem, case["hint_level"], d.stuck_point,
                                       student_attempt=case["attempt"], trace_id=trace_id)
        correct = any(kw in h.hint_text for kw in case["expect_any"])
        keyword_results.append(correct)
        langfuse.score(trace_id=trace_id, name="hint_quality",
                        value=correct, data_type="BOOLEAN",
                        comment=f"problem={case['problem_id']} attempt={case['attempt']!r} "
                                f"stuck_point={d.stuck_point!r} hint={h.hint_text!r} "
                                f"expect_any={case['expect_any']}")

        line = f"[hint] keyword={'OK ' if correct else 'FAIL'} {case['problem_id']} {case['attempt']!r} -> {h.hint_text!r}"

        gemini_ok = gemini_judge_explanation(problem, case["attempt"], h.hint_text, trace_id)
        if gemini_ok is not None:
            gemini_judge_results.append(gemini_ok)
            langfuse.score(trace_id=trace_id, name="hint_quality_gemini_judge",
                            value=gemini_ok, data_type="BOOLEAN",
                            comment=f"hint={h.hint_text!r} gemini_verdict={gemini_ok}")
            line += f" | gemini판단={'맞음' if gemini_ok else '틀림'}"

        print(line)
    return keyword_results, gemini_judge_results


def _pct(results: list[bool]) -> str:
    if not results:
        return "N/A"
    return f"{sum(results)}/{len(results)} ({100 * sum(results) / len(results):.0f}%)"


def main():
    print("=== 의도분류 (우회 탐지율 + Gemini 교차검증) ===")
    intent_label_results, intent_cross_results = eval_intent()
    print("\n=== 오답 진단: 정답 판별 + 막힌 지점 진단 + Gemini 교차검증 ===")
    solved_results, stuckpoint_results, diag_gemini_results = eval_diagnosis()
    print("\n=== 힌트 품질(진단 반영 여부 + Gemini 교차검증) ===")
    hint_keyword_results, hint_gemini_results = eval_hint()

    print("\n=== 요약 ===")
    print("의도분류(라벨 기준):", _pct(intent_label_results))
    print("의도분류(Gemini 교차검증 동의율):", _pct(intent_cross_results))
    print("진단-정답판별(객관적, 기계채점):", _pct(solved_results))
    print("진단-막힌지점(라벨 기준):", _pct(stuckpoint_results))
    print("진단-막힌지점(Gemini 독립판단):", _pct(diag_gemini_results))
    print("힌트품질(라벨 기준):", _pct(hint_keyword_results))
    print("힌트품질(Gemini 독립판단):", _pct(hint_gemini_results))

    langfuse.flush()   # 프로세스 종료 전 대기 중인 score/trace를 서버로 전송
    print("\nLangfuse에 score 전송 완료.")


if __name__ == "__main__":
    main()

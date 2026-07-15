"""
핵심 Tool 구현.
Day3: Solar(LLM)가 있으면 실제 호출, 없거나 실패하면 Mock 규칙으로 자동 폴백.
바깥 시그니처(입출력)는 그대로라 그래프/노드는 안 바뀐다.
"""
import re
import logging
from app.schemas.chat import Hint, Diagnosis
from app.core import llm_client, prompts

log = logging.getLogger(__name__)

# --- Mock 폴백용 규칙 패턴 ---
_LEAK_PATTERNS = ["답 알려", "답만", "정답 뭐", "정답이 뭐", "그냥 알려", "풀어줘", "답 좀", "정답 알려", "답이 뭐"]
_OFFTOPIC_PATTERNS = ["게임", "놀자", "심심", "축구", "노래", "영화", "사랑", "점심", "뭐해", "재미없"]
_VALID_INTENTS = {"normal", "answer_seeking", "off_topic"}


def classify_intent(message: str, problem: dict, trace_id: str | None = None) -> str:
    """의도 분류: normal | answer_seeking | off_topic (입력단 가드레일).
    현재 푸는 '문제'를 함께 넘겨, 짧은 답('9' 등)을 잡담으로 오판하지 않게 한다."""
    data = llm_client.chat_json(prompts.INTENT_SYS, prompts.intent_user(problem, message),
                                 trace_name="intent_classify", trace_id=trace_id)
    if data and data.get("intent") in _VALID_INTENTS:
        return data["intent"]
    # --- Mock 폴백 (문제 맥락 없이 규칙만) ---
    if any(p in message for p in _LEAK_PATTERNS):
        return "answer_seeking"
    if any(p in message for p in _OFFTOPIC_PATTERNS):
        return "off_topic"
    return "normal"


def diagnose_step(problem: dict, attempt: str, trace_id: str | None = None) -> Diagnosis:
    """오답/막힌 지점 진단.

    이중검증: '정답으로 판정'된 경우에만 2차로 "여러 후보를 나열해서 우연히 맞은 건 아닌지"
    다시 확인한다(프롬프트 규칙 1차 + 별도 모델 호출 2차). 정답을 여러 개 나열해서
    그 중 하나가 얻어걸려 통과하는 걸 막기 위함.
    """
    data = llm_client.chat_json(prompts.DIAGNOSE_SYS, prompts.diagnose_user(problem, attempt),
                                 trace_name="diagnose_step", trace_id=trace_id)
    if data is not None and "is_correct" in data:
        is_correct = bool(data.get("is_correct"))
        solved = bool(data.get("solved"))
        stuck_point = str(data.get("stuck_point", ""))
        if is_correct or solved:
            confirm = llm_client.chat_json(prompts.CONFIRM_SYS, prompts.confirm_user(problem, attempt),
                                            trace_name="confirm_single_answer", trace_id=trace_id)
            if confirm is not None and confirm.get("single_confident_answer") is False:
                is_correct, solved = False, False
                stuck_point = stuck_point or "여러 값을 나열해서 답한 것 같아요"
        return Diagnosis(stuck_point=stuck_point, is_correct=is_correct, solved=solved)
    # --- Mock 폴백 (규칙 휴리스틱) ---
    ans = str(problem["answer"]).replace(" ", "")
    text = attempt.replace(" ", "")
    nums = re.findall(r"\d+", text)
    listed_many_candidates = len(set(nums)) > 1   # 서로 다른 숫자를 여러 개 나열 → 확신 없는 답으로 간주
    ans_present = ans in text
    if ans_present and not listed_many_candidates:
        if "묶음" not in text:
            return Diagnosis(stuck_point="", is_correct=True, solved=True)
        return Diagnosis(stuck_point="", is_correct=True, solved=False)
    if listed_many_candidates and ans_present:
        return Diagnosis(stuck_point="여러 값을 나열해서 답한 것 같아요", is_correct=False, solved=False)
    return Diagnosis(stuck_point="나눗셈의 의미를 아직 못 잡음", is_correct=False, solved=False)


def generate_hint(problem: dict, hint_level: int, stuck_point: str = "", student_attempt: str = "",
                   trace_id: str | None = None) -> Hint:
    """hint_level(1~3)에 맞춘 소크라테스식 힌트. LLM 있으면 학생의 실제 답/막힌 지점을 반영해
    자연스럽게 생성하고, 없으면 데이터 힌트를 그대로 사용한다."""
    level = max(1, min(hint_level, 3))
    ref = problem["hint_by_level"][str(level)]
    txt = llm_client.chat_text(prompts.HINT_SYS, prompts.hint_user(problem, ref, level, stuck_point, student_attempt),
                                trace_name="generate_hint", trace_id=trace_id)
    hint_text = txt.strip() if txt else ref
    return Hint(hint_text=hint_text, level=level, contains_answer=False)


def verify_no_leak(text: str, answer: str) -> bool:
    """출력단 가드레일: 정답 숫자가 응답에 '단독'으로 등장하면 위험(False)."""
    ans = str(answer).strip()
    return re.search(rf"(?<!\d){re.escape(ans)}(?!\d)", text) is None

"""
app/services/meal_judge.py
조합 자연성 판정 (Meal Coherence Judge) — 기획서 검증표 5번 항목.

규칙(kcal·나트륨·탄단지)으로 거른 상위 조합 후보들 중에서, "사람이 한 끼로 먹기에
자연스러운 조합"을 LLM이 고른다. 규칙이 못 잡는 어색함을 걸러낸다:
  - 겹치는 재료(토마토라면+토마토김치)
  - 안 어울리는 조합(죽+튀김, 샌드위치+팬케익)
  - 국물 없이 마른 것만 / 비슷한 음식 중복

'판단은 LLM, 사실은 코드' 원칙: 자연스러움은 판단이라 LLM, 영양은 코드가 이미 검증.
실패/타임아웃 시 예외를 올려 호출부(composer)가 규칙 1등으로 폴백한다(무중단).
"""

import json


def _fmt(items) -> str:
    return " + ".join(f.food_name for f in items)


class JudgeResult:
    """조합 자연성 판정 결과.

    choice: 가장 자연스러운 후보 인덱스(0-based).
    acceptable: 그 후보가 '한 끼로 먹을 만한가'. False면 후보 전부가 부적절하다는 뜻 →
                호출부(composer)가 다른 seed로 재조합하거나 정직 안내로 넘긴다.
    reason: 선택/거부 이유 한 줄(로그·발표·디버깅용).
    """

    def __init__(self, choice: int, acceptable: bool, reason: str = ""):
        self.choice = choice
        self.acceptable = acceptable
        self.reason = reason


def judge_coherence(candidates: list[list], conditions) -> JudgeResult:
    """후보 조합들을 LLM으로 판정.

    '가장 나은 것'을 고르는 데 그치지 않고, 그것조차 한 끼로 부적절하면 acceptable=False.
    → "김치찌개+떡볶이 같은 조합밖에 없으면 차라리 거른다"는 최종 방어선.

    반환: JudgeResult(choice, acceptable, reason).
    실패/타임아웃 시 예외를 올려 호출부가 규칙 1등으로 폴백(무중단).
    """
    if not candidates:
        return JudgeResult(0, False, "후보 없음")

    lines = [f"{i + 1}. {_fmt(c)}" for i, c in enumerate(candidates)]
    pref = ", ".join(conditions.preferences or []) or "특별한 선호 없음"
    prompt = (
        "당신은 한식 식단 전문가입니다. 아래는 영양 기준(칼로리·나트륨)을 통과한 한 끼 식단 후보들입니다.\n"
        "사람이 실제로 '한 끼'로 먹기에 가장 자연스러운 조합을 하나 고르고, "
        "그 조합이 정말 한 끼로 먹을 만한지 판정하세요.\n\n"
        "판단 기준:\n"
        "- 재료·맛이 겹치면 어색(예: 토마토라면+토마토김치)\n"
        "- 밥류에는 국·반찬이 곁들여지면 좋고, 한 그릇 요리는 단독이나 가벼운 반찬이 자연스러움\n"
        f"- 사용자 선호({pref})에 맞으면 가점\n\n"
        "다음은 명백히 어색한 조합이다. 이런 조합만 있으면 반드시 acceptable=false:\n"
        "- 완결형 한 그릇 요리(죽·비빔밥·국수·덮밥) 2개를 같이 먹는 것 (예: 전복죽+돈까스, 비빔밥+국수)\n"
        "- 국물 요리 2개를 같이 (예: 김치찌개+된장찌개)\n"
        "- 완결형 한 그릇 요리(국수·덮밥·죽 등)에 국물 요리를 곁들이는 것 "
        "(예: 칼국수+된장찌개, 비빔밥+김치찌개) — 한 그릇 요리는 그 자체로 완성이라 국을 더하지 않는다\n"
        "- 죽처럼 부드러운 것과 튀김을 같이 (예: 죽+돈까스)\n\n"
        "후보:\n" + "\n".join(lines) + "\n\n"
        "가장 자연스러운 후보를 고르되, 후보 전부가 위처럼 어색하면 acceptable을 false로.\n"
        "JSON만 답하세요(설명·마크다운 없이): "
        '{"choice": 번호(1부터), "acceptable": true/false, "reason": "한 줄 이유"}'
    )

    from app.services.llm_client import complete

    raw = complete([{"role": "user", "content": prompt}], temperature=0).strip()
    return _parse_judge(raw, len(candidates))


def _parse_judge(raw: str, n: int) -> JudgeResult:
    """LLM 응답을 JudgeResult로. JSON 실패 시 숫자만이라도 뽑아 폴백(acceptable=True)."""
    try:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end != -1:
            obj = json.loads(raw[start : end + 1])
            choice = int(obj.get("choice", 1)) - 1
            if not (0 <= choice < n):
                choice = 0
            acceptable = bool(obj.get("acceptable", True))
            reason = str(obj.get("reason", ""))[:120]
            return JudgeResult(choice, acceptable, reason)
    except (ValueError, TypeError, KeyError):
        pass
    # JSON 파싱 실패 → 숫자만 뽑아 그거라도 선택, 판정은 통과 취급(무중단).
    digits = "".join(ch for ch in raw if ch.isdigit())
    choice = (int(digits[0]) - 1) if digits else 0
    if not (0 <= choice < n):
        choice = 0
    return JudgeResult(choice, True, "JSON 파싱 실패 → 규칙 선택 유지")


def pick_most_coherent(candidates: list[list], conditions) -> int:
    """하위호환 래퍼: 인덱스만 필요할 때(기존 호출부·테스트). 판정은 무시."""
    return judge_coherence(candidates, conditions).choice


def coherence_scores(candidates: list[list], conditions) -> list[dict]:
    """(선택) 각 후보에 점수+이유를 매긴다. 발표/디버깅용. 지금은 pick만 쓰면 됨."""
    lines = [f"{i + 1}. {_fmt(c)}" for i, c in enumerate(candidates)]
    prompt = (
        "각 한 끼 조합이 얼마나 자연스러운지 0~10점으로 평가하고 이유를 한 줄로.\n"
        'JSON 배열로만: [{"no":1,"score":8,"reason":"..."}]\n\n' + "\n".join(lines)
    )
    from app.services.llm_client import complete

    raw = complete([{"role": "user", "content": prompt}], temperature=0).strip()
    return json.loads(raw[raw.find("[") : raw.rfind("]") + 1])

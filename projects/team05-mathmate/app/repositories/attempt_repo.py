"""진척도(attempts) 저장소.

단원별 숙련도(get_unit_mastery)는 정답을 맞힌(solved) 시도만 기록해 '완료한 문제' 기준으로 집계한다.
난이도별 정답률(get_overall_summary)은 힌트 3단계를 다 쓰고 포기(공개)한 시도까지 포함한
'전체 시도' 기준으로 집계한다 — 그래야 정답률이라는 지표가 의미를 가진다.
"""
from collections import defaultdict
from app.db.supabase_client import get_client

_DIFFICULTIES = ("쉬움", "중간", "어려움")


def record_attempt(user_id: int, problem_id: str, unit: str, hints_used: int, solved: bool,
                    grade: int | None = None, semester: int | None = None,
                    difficulty: str | None = None) -> None:
    get_client().table("attempts").insert({
        "user_id": user_id,
        "problem_id": problem_id,
        "unit": unit,
        "hints_used": hints_used,
        "solved": solved,
        "grade": grade,
        "semester": semester,
        "difficulty": difficulty,
    }).execute()


def _mastery_level(avg_hints: float) -> str:
    if avg_hints < 1.0:
        return "잘함"
    if avg_hints < 2.0:
        return "보통"
    return "취약"


def _accuracy_by_difficulty(rows: list[dict]) -> dict[str, float | None]:
    """주어진 attempts 행들(전체 시도 기준)의 난이도별 정답률(%). 그 난이도 시도가 없으면 None."""
    by_diff: dict[str, list[bool]] = {d: [] for d in _DIFFICULTIES}
    for r in rows:
        diff = r.get("difficulty")
        if diff in by_diff:
            by_diff[diff].append(bool(r.get("solved")))
    return {
        diff: (round(100 * sum(results) / len(results), 1) if results else None)
        for diff, results in by_diff.items()
    }


def get_unit_mastery(user_id: int, grade: int | None = None, semester: int | None = None) -> list[dict]:
    """단원별 '스스로 해결한 문제 수 · 평균 힌트 사용량 · 숙련도 · 정답 공개된 문제 수 · 성공률 ·
    난이도별 정답률'을 집계한다. grade/semester를 넘기면 그 학년·학기에 시도한 문제만으로 좁혀서 집계한다.

    problems_attempted/avg_hints_used/mastery_level은 '스스로 해결한(solved) 문제'만 기준으로 하고,
    힌트를 다 쓰고 튜터가 정답을 공개한(solved=False) 문제는 revealed_count로 따로 센다 —
    둘을 섞으면 "힌트 평균"이 실제 실력보다 후하게 나오고, 포기한 문제가 조용히 묻혀버린다.

    취약 단원 정렬은 success_rate(스스로 해결/전체 시도)가 낮은 순 — "한 번도 못 푼 단원"과
    "가까스로라도 몇 번 푼 단원"을 같은 기준(성공률)으로 견줄 수 있게 한다. 동률이면 평균 힌트가
    많은 쪽, 그래도 동률이면 포기(공개)한 문제가 많은 쪽, 그래도 동률이면 문제를 적게 푼(연습이
    덜 된) 쪽을 더 약하다고 본다.
    """
    query = get_client().table("attempts").select("unit, hints_used, solved, difficulty").eq("user_id", user_id)
    if grade is not None:
        query = query.eq("grade", grade)
    if semester is not None:
        query = query.eq("semester", semester)
    res = query.execute()

    solved_hints: dict[str, list[int]] = defaultdict(list)
    revealed_count: dict[str, int] = defaultdict(int)
    rows_by_unit: dict[str, list[dict]] = defaultdict(list)
    for row in res.data:
        unit = row["unit"]
        rows_by_unit[unit].append(row)
        if row.get("solved"):
            solved_hints[unit].append(row["hints_used"])
        else:
            revealed_count[unit] += 1

    items = []
    for unit in set(solved_hints) | set(revealed_count):
        hints = solved_hints.get(unit, [])
        solved_n, revealed_n = len(hints), revealed_count.get(unit, 0)
        total = solved_n + revealed_n
        avg_hints = sum(hints) / len(hints) if hints else None
        items.append({
            "unit": unit,
            "problems_attempted": solved_n,
            "avg_hints_used": round(avg_hints, 1) if avg_hints is not None else None,
            "mastery_level": _mastery_level(avg_hints) if avg_hints is not None else "취약",
            "revealed_count": revealed_n,
            "success_rate": round(100 * solved_n / total, 1) if total else 0.0,
            "accuracy_by_difficulty": _accuracy_by_difficulty(rows_by_unit[unit]),
        })
    items.sort(key=lambda x: (x["success_rate"], -(x["avg_hints_used"] or 0), -x["revealed_count"],
                              x["problems_attempted"]))
    return items


def get_overall_summary(user_id: int, grade: int | None = None, semester: int | None = None) -> dict:
    """전체 요약: 총 힌트 사용량 + 난이도별(쉬움/중간/어려움) 정답률 + 점수 기반 개인화 문장.

    단원별 숙련도와 달리, 여기서는 '전체 시도'(맞혔든 포기해서 공개했든)를 모두 센다 —
    정답률은 분모(시도)가 있어야 의미가 있기 때문이다.
    """
    query = get_client().table("attempts").select("difficulty, solved, hints_used").eq("user_id", user_id)
    if grade is not None:
        query = query.eq("grade", grade)
    if semester is not None:
        query = query.eq("semester", semester)
    rows = query.execute().data or []

    total_hints = sum(int(r.get("hints_used") or 0) for r in rows)
    accuracy = _accuracy_by_difficulty(rows)

    return {
        "total_attempts": len(rows),
        "total_hints_used": total_hints,
        "accuracy_by_difficulty": accuracy,
        "message": _personalized_message(accuracy, total_hints, len(rows)),
    }


def _personalized_message(accuracy: dict, total_hints: int, total_attempts: int) -> str:
    if total_attempts == 0:
        return "아직 기록이 없어요. 문제를 풀면 여기에 나만의 학습 리포트가 쌓여요!"

    easy, mid, hard = accuracy.get("쉬움"), accuracy.get("중간"), accuracy.get("어려움")
    known = [v for v in (easy, mid, hard) if v is not None]
    if not known:
        return "아직 난이도별 기록이 부족해요. 조금 더 풀어볼까요?"

    if hard is not None and easy is not None and hard - easy >= 15:
        parts = ["어려운 문제에서 응용력이 특히 좋아요! 쉬운 문제에서 방심하지 않도록 조심해봐요."]
    elif easy is not None and hard is not None and easy - hard >= 15:
        parts = ["기본기는 아주 튼튼해요! 어려운 문제에 조금씩 더 도전해봐요."]
    elif min(known) >= 80:
        parts = ["난이도에 상관없이 고르게 잘 풀고 있어요!"]
    else:
        parts = ["차근차근 실력이 쌓이고 있어요."]

    if total_attempts:
        avg_hints = total_hints / total_attempts
        if avg_hints < 0.5:
            parts.append("힌트를 거의 안 쓰고 스스로 척척 풀어내고 있어요!")
        elif avg_hints >= 2:
            parts.append("힌트를 꽤 많이 활용하고 있어요 — 조금 더 스스로 고민해보는 연습을 해봐요.")

    return " ".join(parts)

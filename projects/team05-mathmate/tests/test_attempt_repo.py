"""진척도(attempt_repo) 테스트. Supabase는 fake_supabase 더블로 대체해 네트워크 없이 검증한다."""
from app.repositories import attempt_repo


def _record(user_id, unit, hints_used, grade=5, semester=1, solved=True, problem_id=None, difficulty=None):
    attempt_repo.record_attempt(
        user_id=user_id,
        problem_id=problem_id or f"{unit}-{hints_used}-{grade}-{semester}",
        unit=unit,
        hints_used=hints_used,
        solved=solved,
        grade=grade,
        semester=semester,
        difficulty=difficulty,
    )


def test_avg_hints_and_mastery_only_count_solved_attempts(fake_supabase):
    """평균 힌트·숙련도는 스스로 해결한 시도만 기준으로 하고, 공개된 시도는 revealed_count로 따로 센다."""
    _record(1, "도형", 1, solved=True, problem_id="p1")
    _record(1, "도형", 3, solved=False, problem_id="p2")   # 힌트 다 쓰고 정답 공개됨

    items = attempt_repo.get_unit_mastery(1)
    assert len(items) == 1
    assert items[0]["problems_attempted"] == 1
    assert items[0]["avg_hints_used"] == 1.0
    assert items[0]["revealed_count"] == 1


def test_unit_with_only_revealed_attempts_still_appears(fake_supabase):
    """스스로 해결한 문제가 하나도 없어도(전부 공개됨), 그 단원은 목록에 나와야 한다."""
    _record(1, "분수", 3, solved=False, problem_id="p1")
    _record(1, "분수", 3, solved=False, problem_id="p2")

    items = attempt_repo.get_unit_mastery(1)
    assert len(items) == 1
    assert items[0]["problems_attempted"] == 0
    assert items[0]["avg_hints_used"] is None
    assert items[0]["revealed_count"] == 2


def test_mastery_level_thresholds(fake_supabase):
    _record(1, "잘함단원", 0, problem_id="a")
    _record(1, "보통단원", 1, problem_id="b")
    _record(1, "취약단원", 2, problem_id="c")

    by_unit = {i["unit"]: i for i in attempt_repo.get_unit_mastery(1)}
    assert by_unit["잘함단원"]["mastery_level"] == "잘함"
    assert by_unit["보통단원"]["mastery_level"] == "보통"
    assert by_unit["취약단원"]["mastery_level"] == "취약"


def test_grade_semester_filter_narrows_results(fake_supabase):
    _record(1, "분수", 3, grade=4, semester=1, problem_id="a")
    _record(1, "도형", 1, grade=5, semester=1, problem_id="b")

    all_items = attempt_repo.get_unit_mastery(1)
    assert {i["unit"] for i in all_items} == {"분수", "도형"}

    grade5_items = attempt_repo.get_unit_mastery(1, grade=5)
    assert {i["unit"] for i in grade5_items} == {"도형"}

    grade4_items = attempt_repo.get_unit_mastery(1, grade=4, semester=1)
    assert {i["unit"] for i in grade4_items} == {"분수"}


def test_weakest_prefers_more_hints_first(fake_supabase):
    _record(1, "많이틀림", 3, problem_id="a")
    _record(1, "적게틀림", 1, problem_id="b")

    items = attempt_repo.get_unit_mastery(1)
    assert items[0]["unit"] == "많이틀림"   # 평균 힌트가 더 높은 쪽이 먼저(더 약함)


def test_weakest_tiebreak_prefers_fewer_attempts(fake_supabase):
    """평균 힌트가 정확히 같으면(반올림 우연이 아니라 진짜 동점), 문제를 적게 푼(연습이 덜 된) 쪽을 더 약하다고 본다."""
    for i in range(6):
        _record(1, "많이푼단원", 1, problem_id=f"many-{i}")
    _record(1, "한번푼단원", 1, problem_id="once")

    items = attempt_repo.get_unit_mastery(1)
    assert items[0]["unit"] == "한번푼단원"
    assert items[0]["problems_attempted"] == 1
    assert items[1]["unit"] == "많이푼단원"
    assert items[1]["problems_attempted"] == 6


def test_no_attempts_returns_empty_list(fake_supabase):
    assert attempt_repo.get_unit_mastery(999) == []


def test_unit_mastery_includes_per_unit_difficulty_accuracy(fake_supabase):
    """단원 카드에도 그 단원 안에서의 난이도별 정답률이 같이 나와야 한다."""
    _record(1, "큰 수", 1, solved=True, difficulty="쉬움", problem_id="a")
    _record(1, "큰 수", 3, solved=False, difficulty="쉬움", problem_id="b")
    _record(1, "큰 수", 0, solved=True, difficulty="어려움", problem_id="c")

    items = {i["unit"]: i for i in attempt_repo.get_unit_mastery(1)}
    acc = items["큰 수"]["accuracy_by_difficulty"]
    assert acc["쉬움"] == 50.0
    assert acc["어려움"] == 100.0
    assert acc["중간"] is None


def test_weakest_ranked_by_success_rate_not_raw_avg_hints(fake_supabase):
    """스스로 해결한 게 하나도 없는 단원(성공률 0%)은, 힌트를 많이 쓰고서라도 하나는 해결한
    단원(성공률 >0%)보다 항상 더 약하다고 판단해야 한다 — 둘 다 힌트 3개짜리 기록이 있어도."""
    _record(1, "비례식과 비례배분", 3, solved=False, problem_id="a")   # 0/1 = 성공률 0%

    _record(1, "큰 수", 3, solved=True, problem_id="b")                # 1/3 = 성공률 33%
    _record(1, "큰 수", 3, solved=False, problem_id="c")
    _record(1, "큰 수", 3, solved=False, problem_id="d")

    items = {i["unit"]: i for i in attempt_repo.get_unit_mastery(1)}
    assert items["비례식과 비례배분"]["success_rate"] == 0.0
    assert items["큰 수"]["success_rate"] == round(100 / 3, 1)

    ordered = attempt_repo.get_unit_mastery(1)
    assert ordered[0]["unit"] == "비례식과 비례배분"
    assert ordered[1]["unit"] == "큰 수"


def test_overall_summary_empty_when_no_attempts(fake_supabase):
    summary = attempt_repo.get_overall_summary(999)
    assert summary["total_attempts"] == 0
    assert summary["accuracy_by_difficulty"] == {"쉬움": None, "중간": None, "어려움": None}


def test_overall_summary_computes_accuracy_by_difficulty(fake_supabase):
    attempt_repo.record_attempt(1, "e1", "단원", hints_used=0, solved=True, difficulty="쉬움")
    attempt_repo.record_attempt(1, "e2", "단원", hints_used=1, solved=False, difficulty="쉬움")
    attempt_repo.record_attempt(1, "h1", "단원", hints_used=0, solved=True, difficulty="어려움")

    summary = attempt_repo.get_overall_summary(1)
    assert summary["total_attempts"] == 3
    assert summary["total_hints_used"] == 1
    assert summary["accuracy_by_difficulty"]["쉬움"] == 50.0
    assert summary["accuracy_by_difficulty"]["어려움"] == 100.0
    assert summary["accuracy_by_difficulty"]["중간"] is None
    assert summary["message"]


def test_overall_summary_includes_failed_reveal_attempts_in_accuracy(fake_supabase):
    """정답을 공개(포기)한 시도도 '틀린 시도'로 정답률 분모에 들어가야 한다."""
    attempt_repo.record_attempt(1, "p1", "단원", hints_used=3, solved=False, difficulty="어려움")
    summary = attempt_repo.get_overall_summary(1)
    assert summary["accuracy_by_difficulty"]["어려움"] == 0.0

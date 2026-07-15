"""문제은행 조회."""
from fastapi import APIRouter
from app.repositories import problem_repo

router = APIRouter()


@router.get("/problems")
def list_problems(unit: str | None = None, difficulty: str | None = None,
                   grade: int | None = None, semester: int | None = None):
    # 정답/힌트/풀이가 빠진 '안전 뷰'만 반환 (답 유출률 0% 보장)
    items = problem_repo.list_problems_public(unit, difficulty, grade, semester)
    return {"unit": unit, "difficulty": difficulty, "grade": grade, "semester": semester,
            "count": len(items), "items": items}


@router.get("/problems/semesters")
def list_semesters(grade: int | None = None):
    return {"grade": grade, "semesters": problem_repo.list_semesters(grade)}


@router.get("/problems/units")
def list_units(grade: int | None = None, semester: int | None = None):
    return {"grade": grade, "semester": semester, "units": problem_repo.list_units(grade, semester)}

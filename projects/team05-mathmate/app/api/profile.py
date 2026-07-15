"""학생 프로필(로그인 대체) API. login_id(고유 아이디)+비밀번호로 식별한다."""
from fastapi import APIRouter, HTTPException
from app.repositories import user_repo
from app.schemas.profile import ProfileRequest, ProfileResponse

router = APIRouter()


@router.post("/profile", response_model=ProfileResponse)
def create_or_get_profile(req: ProfileRequest):
    result = user_repo.get_or_create_user(req.login_id, req.name, req.grade, req.semester, req.password)
    if result == user_repo.WRONG_PASSWORD:
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않아요.")
    if result == user_repo.NAME_MISMATCH:
        raise HTTPException(status_code=409, detail="그 아이디는 이미 있는데 이름이 달라요. 아이디를 다시 확인해주세요.")
    return ProfileResponse(user_id=result["id"], login_id=result["login_id"], name=result["name"],
                            grade=result["grade"], semester=result["semester"])

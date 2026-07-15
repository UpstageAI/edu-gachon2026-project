"""학생 프로필 스키마. login_id(학생이 직접 정하는 고유 아이디)로 식별하고,
비밀번호는 그 아이디가 정말 본인 것인지 확인하는 용도다."""
from pydantic import BaseModel


class ProfileRequest(BaseModel):
    login_id: str
    name: str
    grade: int
    semester: int
    password: str


class ProfileResponse(BaseModel):
    user_id: int
    login_id: str
    name: str
    grade: int
    semester: int

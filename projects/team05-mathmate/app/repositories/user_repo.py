"""학생 프로필 저장소.

동명이인 때문에 생기던 모호함(이름+비밀번호 조합 충돌)을 없애기 위해,
학생이 직접 정하는 고유 아이디(login_id)로 식별하고 비밀번호는 본인 확인용으로만 쓴다.
"""
import hashlib
import os
from app.db.supabase_client import get_client

WRONG_PASSWORD = "wrong_password"   # login_id는 있는데 비밀번호가 안 맞는 상태를 나타내는 sentinel
NAME_MISMATCH = "name_mismatch"     # login_id·비밀번호는 맞는데 이름이 다른 상태를 나타내는 sentinel


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()


def _create(login_id: str, name: str, grade: int, semester: int, password: str) -> dict:
    salt = os.urandom(16).hex()
    created = get_client().table("users").insert({
        "login_id": login_id,
        "name": name,
        "grade": grade,
        "semester": semester,
        "password_hash": _hash_password(password, salt),
        "password_salt": salt,
    }).execute()
    return created.data[0]


def get_or_create_user(login_id: str, name: str, grade: int, semester: int, password: str) -> dict | str:
    """
    - login_id가 이미 있으면: 비밀번호와 이름이 둘 다 맞아야 로그인(학년/학기 갱신 후 반환).
      비밀번호가 안 맞으면 WRONG_PASSWORD, 비밀번호는 맞는데 이름이 다르면 NAME_MISMATCH를 반환한다.
      (이름까지 확인하는 이유: 서로 다른 두 학생이 우연히 같은 아이디+비밀번호를 고르면,
      이름 확인 없이는 뒤에 가입한 사람이 앞사람 계정을 그대로 "이어받아" 이름만 바뀌어버린다.)
    - login_id가 없으면: 새 계정을 만든다.
    """
    client = get_client()
    existing = client.table("users").select("*").eq("login_id", login_id).execute()

    if existing.data:
        user = existing.data[0]
        if _hash_password(password, user["password_salt"]) != user["password_hash"]:
            return WRONG_PASSWORD
        if user.get("name") != name:
            return NAME_MISMATCH
        updates = {}
        if user["grade"] != grade:
            updates["grade"] = grade
        if user["semester"] != semester:
            updates["semester"] = semester
        if updates:
            updated = client.table("users").update(updates).eq("id", user["id"]).execute()
            return updated.data[0]
        return user

    return _create(login_id, name, grade, semester, password)

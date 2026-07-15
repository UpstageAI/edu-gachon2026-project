"""프로필(user_repo) 테스트. Supabase는 fake_supabase 더블로 대체해 네트워크 없이 검증한다."""
from app.repositories import user_repo


def test_creates_new_user(fake_supabase):
    user = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    assert user["login_id"] == "minjun01"
    assert user["name"] == "민준"
    assert user["grade"] == 5
    assert user["semester"] == 1
    assert "id" in user


def test_relogin_with_correct_password_returns_same_user(fake_supabase):
    created = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    again = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    assert again["id"] == created["id"]
    assert len(fake_supabase._tables["users"].rows) == 1   # 중복 생성 안 됨


def test_relogin_updates_grade_and_semester(fake_supabase):
    created = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    updated = user_repo.get_or_create_user("minjun01", "민준", 6, 2, "1234")
    assert updated["id"] == created["id"]        # 같은 계정 유지
    assert updated["grade"] == 6
    assert updated["semester"] == 2


def test_wrong_password_returns_sentinel_not_error(fake_supabase):
    user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    result = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "다른비번")
    assert result == user_repo.WRONG_PASSWORD


def test_matching_password_but_different_name_is_rejected(fake_supabase):
    """아이디+비밀번호가 우연히 같아도 이름이 다르면 다른 사람 계정을 그대로 넘겨받으면 안 된다."""
    user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    result = user_repo.get_or_create_user("minjun01", "지민", 5, 1, "1234")
    assert result == user_repo.NAME_MISMATCH
    # 원래 계정 이름은 그대로 유지돼야 한다(덮어써지면 안 됨).
    relogin = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    assert relogin["name"] == "민준"


def test_same_name_different_login_id_are_separate_accounts(fake_supabase):
    """동명이인이어도 아이디가 다르면 완전히 별개 계정이어야 한다."""
    first = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    second = user_repo.get_or_create_user("minjun02", "민준", 6, 2, "다른비번")
    assert second["id"] != first["id"]
    assert len(fake_supabase._tables["users"].rows) == 2

    # 원래 계정은 그대로 로그인 가능해야 한다.
    relogin = user_repo.get_or_create_user("minjun01", "민준", 5, 1, "1234")
    assert relogin["id"] == first["id"]

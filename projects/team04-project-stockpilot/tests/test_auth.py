"""인증 유틸 단위 테스트 (DB·네트워크 불필요)."""
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    h = hash_password("secret123")
    assert h != "secret123"            # 평문이 그대로 저장되면 안 됨
    assert verify_password("secret123", h)
    assert not verify_password("wrong-pw", h)


def test_token_roundtrip():
    token = create_access_token(42, "alice")
    payload = decode_access_token(token)
    assert payload["sub"] == "42"
    assert payload["username"] == "alice"

from types import SimpleNamespace

import pytest
from supabase_auth.errors import AuthApiError

import app.services.auth_client as auth_client


class FakeAuth:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.set_session_calls = []
        self.sign_out_called = False

    def _maybe_raise(self):
        if self._error is not None:
            raise self._error

    def sign_up(self, credentials):
        self._maybe_raise()
        self.sign_up_credentials = credentials
        return self._response

    def sign_in_with_password(self, credentials):
        self._maybe_raise()
        self.sign_in_credentials = credentials
        return self._response

    def set_session(self, access_token, refresh_token):
        self.set_session_calls.append((access_token, refresh_token))

    def sign_out(self):
        self._maybe_raise()
        self.sign_out_called = True

    def get_user(self, jwt):
        self._maybe_raise()
        return self._response

    def refresh_session(self, refresh_token):
        self._maybe_raise()
        return self._response


class FakeClient:
    def __init__(self, auth):
        self.auth = auth


def _fake_auth_response(user_id="user-1", email="a@example.com", has_session=True):
    user = SimpleNamespace(id=user_id, email=email)
    session = (
        SimpleNamespace(
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in=3600,
        )
        if has_session
        else None
    )
    return SimpleNamespace(user=user, session=session)


def test_sign_up_returns_flat_session_dict(monkeypatch):
    fake_auth = FakeAuth(response=_fake_auth_response())
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    result = auth_client.sign_up("a@example.com", "password123")

    assert result == {
        "user_id": "user-1",
        "email": "a@example.com",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_in": 3600,
    }
    assert fake_auth.sign_up_credentials == {
        "email": "a@example.com",
        "password": "password123",
    }


def test_sign_up_without_session_when_email_confirmation_required(monkeypatch):
    fake_auth = FakeAuth(response=_fake_auth_response(has_session=False))
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    result = auth_client.sign_up("a@example.com", "password123")

    assert result["user_id"] == "user-1"
    assert result["access_token"] is None
    assert result["refresh_token"] is None


def test_sign_in_returns_flat_session_dict(monkeypatch):
    fake_auth = FakeAuth(response=_fake_auth_response())
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    result = auth_client.sign_in("a@example.com", "password123")

    assert result["access_token"] == "access-token"
    assert fake_auth.sign_in_credentials == {
        "email": "a@example.com",
        "password": "password123",
    }


def test_sign_in_raises_auth_error_on_bad_credentials(monkeypatch):
    fake_auth = FakeAuth(error=AuthApiError("Invalid login credentials", 400, "invalid_credentials"))
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    with pytest.raises(auth_client.AuthError):
        auth_client.sign_in("a@example.com", "wrong-password")


def test_sign_out_sets_session_before_signing_out(monkeypatch):
    fake_auth = FakeAuth()
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    auth_client.sign_out("access-token", "refresh-token")

    assert fake_auth.set_session_calls == [("access-token", "refresh-token")]
    assert fake_auth.sign_out_called is True


def test_get_user_returns_none_on_invalid_token(monkeypatch):
    fake_auth = FakeAuth(error=AuthApiError("invalid token", 401, "invalid_token"))
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    assert auth_client.get_user("bad-token") is None


def test_get_user_returns_user_info_on_valid_token(monkeypatch):
    fake_auth = FakeAuth(response=_fake_auth_response())
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    result = auth_client.get_user("access-token")

    assert result == {"user_id": "user-1", "email": "a@example.com"}


def test_refresh_session_returns_none_on_failure(monkeypatch):
    fake_auth = FakeAuth(error=AuthApiError("invalid refresh token", 401, "invalid_token"))
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    assert auth_client.refresh_session("bad-refresh-token") is None


def test_refresh_session_returns_rotated_tokens(monkeypatch):
    fake_auth = FakeAuth(response=_fake_auth_response())
    monkeypatch.setattr(auth_client, "get_client", lambda: FakeClient(fake_auth))

    result = auth_client.refresh_session("old-refresh-token")

    assert result["access_token"] == "access-token"
    assert result["refresh_token"] == "refresh-token"

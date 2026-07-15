# app/services/auth_client.py

from typing import Any, Dict, Optional

from supabase_auth.errors import AuthApiError

from app.services.supabase_client import get_client


class AuthError(Exception):
    pass


def _session_to_dict(response: Any) -> Dict[str, Any]:
    """
    AuthResponse(user/session)를 UI에서 쓰기 편한 평평한 dict로 바꾼다.

    Supabase의 "Confirm email" 설정이 켜져 있으면 sign_up 직후 session이 None일 수
    있다(이메일 인증 전이라 로그인 토큰이 안 나옴) — 이 경우 access_token/refresh_token은
    None으로 내려가므로 호출부에서 이를 "가입은 됐지만 아직 로그인은 안 된 상태"로
    처리해야 한다.
    """
    user = response.user
    session = response.session

    return {
        "user_id": user.id if user else None,
        "email": user.email if user else None,
        "access_token": session.access_token if session else None,
        "refresh_token": session.refresh_token if session else None,
        "expires_in": session.expires_in if session else None,
    }


def _translate_auth_error(error_msg: str) -> str:
    msg = error_msg.lower()
    if "invalid format" in msg and "email" in msg:
        return "이메일 형식이 올바르지 않습니다."
    if "user already registered" in msg:
        return "이미 가입된 이메일입니다."
    if "invalid login credentials" in msg:
        return "이메일 또는 비밀번호가 일치하지 않습니다."
    if "password should be at least" in msg:
        return "비밀번호는 최소 6자 이상이어야 합니다."
    if "signup requires a valid password" in msg:
        return "비밀번호를 입력해주세요."
    if "rate limit" in msg:
        return "요청이 너무 많습니다. 잠시 후 다시 시도해주세요."
    if "missing email" in msg:
        return "이메일을 입력해주세요."
    return "인증 오류가 발생했습니다 (" + error_msg + ")"


def sign_up(email: str, password: str) -> Dict[str, Any]:
    """
    이메일/비밀번호로 회원가입한다.
    """
    try:
        response = get_client().auth.sign_up(
            {"email": email, "password": password}
        )
    except AuthApiError as error:
        raise AuthError(_translate_auth_error(str(error))) from error
    except Exception as error:
        raise AuthError(_translate_auth_error(str(error))) from error

    return _session_to_dict(response)


def sign_in(email: str, password: str) -> Dict[str, Any]:
    """
    이메일/비밀번호로 로그인한다.
    """
    try:
        response = get_client().auth.sign_in_with_password(
            {"email": email, "password": password}
        )
    except AuthApiError as error:
        raise AuthError(_translate_auth_error(str(error))) from error
    except Exception as error:
        raise AuthError(_translate_auth_error(str(error))) from error

    return _session_to_dict(response)


def sign_out(access_token: str, refresh_token: str) -> None:
    """
    로그아웃한다.

    get_client()는 매번 세션이 없는 새 클라이언트를 반환하므로, set_session으로
    먼저 세션을 채워넣어야 sign_out이 실제로 그 토큰을 폐기할 수 있다
    (access_token만으로는 로그아웃이 안 됨).
    """
    client = get_client()

    try:
        client.auth.set_session(access_token, refresh_token)
        client.auth.sign_out()
    except AuthApiError as error:
        raise AuthError(str(error)) from error


def get_user(access_token: str) -> Optional[Dict[str, Any]]:
    """
    access_token으로 사용자 정보를 조회한다. 토큰이 유효하지 않으면 None을 반환한다.
    """
    try:
        response = get_client().auth.get_user(access_token)
    except AuthApiError:
        return None

    if response is None or response.user is None:
        return None

    return {"user_id": response.user.id, "email": response.user.email}


def refresh_session(refresh_token: str) -> Optional[Dict[str, Any]]:
    """
    refresh_token으로 새 access_token/refresh_token을 발급받는다.

    Supabase는 refresh_token을 1회용으로 회전시키므로, 여기서 반환되는
    refresh_token(회전된 새 값)을 호출부가 반드시 저장소(BrowserState 등)에
    다시 저장해야 다음 갱신이 실패하지 않는다. 실패하면 None을 반환한다
    (호출부는 이를 "로그인 만료"로 보고 조용히 게스트 화면으로 전환해야 한다).
    """
    try:
        response = get_client().auth.refresh_session(refresh_token)
    except AuthApiError:
        return None

    return _session_to_dict(response)

"""Supabase 클라이언트 싱글턴.
- 백엔드는 신뢰된 서버이므로 service_role 키(config.SUPABASE_BACKEND_KEY)로 접속한다.
- 키/URL이 없거나 supabase 패키지가 없으면 None을 반환 → 호출부가 로컬 JSON으로 폴백.
"""
from app.core import config

_client = None
_tried = False


def get_client():
    """설정이 갖춰졌을 때만 Supabase Client를 만들어 재사용. 실패 시 None."""
    global _client, _tried
    if _client is not None:
        return _client
    if _tried:                       # 한 번 실패했으면 매번 다시 시도하지 않음
        return None
    _tried = True
    if not config.USE_SUPABASE:
        return None
    try:
        from supabase import create_client
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_BACKEND_KEY)
        return _client
    except Exception:                # 패키지 없음/네트워크/키 오류 → 폴백
        return None

import time
from functools import lru_cache
from typing import Any, Protocol

import httpx
from supabase import Client, create_client

from app.core.config import settings


@lru_cache
def get_supabase() -> Client:
    if not settings.supabase_url or not settings.supabase_key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 환경변수가 설정되지 않았습니다.")
    return create_client(settings.supabase_url, settings.supabase_key)


class _Executable(Protocol):
    def execute(self) -> Any: ...


def execute_with_retry(builder: _Executable, attempts: int = 3, delay: float = 0.2) -> Any:
    """조회(SELECT) 쿼리 실행 후 Windows에서 종종 발생하는 httpx 소켓 재사용 오류
    (WinError 10035 등 httpx.TransportError)에 한해 재시도한다.

    반복문에서 짧은 간격으로 Supabase 호출을 여러 번 이어서 하면(예: 후보 레시피마다
    재료 조회) 커넥션 풀이 재사용하는 소켓이 아직 정리되지 않아 실패하는 경우가 잦다.
    조회만 감싸므로 재시도해도 부작용이 없다.
    """
    last_error: httpx.TransportError | None = None
    for attempt in range(attempts):
        try:
            return builder.execute()
        except httpx.TransportError as error:
            last_error = error
            if attempt < attempts - 1:
                time.sleep(delay)
    raise last_error

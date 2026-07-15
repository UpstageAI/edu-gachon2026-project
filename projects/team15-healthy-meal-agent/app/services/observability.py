"""
app/services/observability.py
LLMOps 관찰가능성(Observability) — litellm 호출을 Langfuse로 트레이싱.

강의 5강 "관찰 가능성" 파트 적용:
  - 지금까지는 print 로그뿐이라 "어느 노드/호출에서 틀어졌는지" 추적이 어려웠다.
  - litellm은 success/failure 콜백에 "langfuse"만 등록하면 모든 completion 호출의
    입력·출력·토큰·지연·비용을 Langfuse 대시보드로 자동 전송한다(호출부 무변경).

설계 원칙(서비스 무중단):
  - LANGFUSE_* 키가 없으면 조용히 비활성화한다. 관측이 안 될 뿐, 추천 로직은 그대로 동작.
  - 콜백 등록은 최초 1회만(중복 등록 방지).
"""

import os

from dotenv import load_dotenv

load_dotenv()

_ENABLED: bool | None = None  # None=아직 미판정, True/False=판정 완료


def langfuse_enabled() -> bool:
    """LANGFUSE 공개키/비밀키가 모두 있으면 관측 활성화."""
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"))


def setup_observability() -> bool:
    """
    litellm 콜백에 langfuse를 등록한다. 최초 1회만 실제로 등록.
    반환: 관측 활성화 여부(키 없으면 False).
    """
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED

    if not langfuse_enabled():
        _ENABLED = False
        print("[관측] LANGFUSE 키 없음 → 트레이싱 비활성화 (서비스는 정상 동작)")
        return False

    try:
        import litellm

        # 중복 등록 방지: 이미 들어있으면 건너뜀
        if "langfuse" not in (litellm.success_callback or []):
            litellm.success_callback = [*(litellm.success_callback or []), "langfuse"]
        if "langfuse" not in (litellm.failure_callback or []):
            litellm.failure_callback = [*(litellm.failure_callback or []), "langfuse"]

        _ENABLED = True
        host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")
        print(f"[관측] Langfuse 트레이싱 활성화 → {host}")
        return True
    except Exception as e:
        # 관측 실패가 서비스를 막지 않는다
        _ENABLED = False
        print(f"[관측] Langfuse 설정 실패 → 트레이싱 없이 계속 진행: {e}")
        return False


def flush() -> None:
    """
    대기 중인 trace를 Langfuse로 즉시 전송한다.
    langfuse는 백그라운드로 비동기 전송하므로, 짧게 끝나는 실행(배치 스크립트 등)에서는
    종료 전에 flush해야 trace가 유실되지 않는다. 실패해도 조용히 넘어간다(무중단).
    """
    if not langfuse_enabled():
        return
    try:
        from langfuse import Langfuse

        Langfuse().flush()
    except Exception as e:
        print(f"[관측] flush 실패(무시): {e}")

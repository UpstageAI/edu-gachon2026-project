"""
tests/test_observability.py
LLMOps 관찰가능성(Langfuse) 설정 로직 테스트.
외부 Langfuse 서버 없이, 콜백 등록/비활성화 분기만 결정적으로 검증한다.
"""

import importlib

import app.services.observability as obs


def _fresh_module(monkeypatch, **env):
    """환경변수를 세팅하고 모듈 상태(_ENABLED 캐시)를 초기화해 재판정하게 한다.

    observability는 import 시 load_dotenv()로 .env를 읽는다. reload하면 .env의 실제
    LANGFUSE 키가 다시 주입되어 "키 없음" 케이스가 오염되므로, reload 동안 load_dotenv를
    no-op으로 막아 테스트가 monkeypatch한 환경만 보게 한다.
    """
    for key in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST"):
        monkeypatch.delenv(key, raising=False)
    for key, val in env.items():
        monkeypatch.setenv(key, val)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    importlib.reload(obs)
    return obs


# ── 1. 키가 없으면 비활성화 (서비스 무중단) ────────────────
def test_disabled_without_keys(monkeypatch):
    m = _fresh_module(monkeypatch)
    assert m.langfuse_enabled() is False
    assert m.setup_observability() is False


# ── 2. 공개키만 있고 비밀키 없으면 비활성화 ────────────────
def test_disabled_with_partial_keys(monkeypatch):
    m = _fresh_module(monkeypatch, LANGFUSE_PUBLIC_KEY="pk-lf-test")
    assert m.langfuse_enabled() is False
    assert m.setup_observability() is False


# ── 3. 두 키가 모두 있으면 litellm 콜백에 langfuse 등록 ────────────────
def test_enabled_registers_litellm_callback(monkeypatch):
    m = _fresh_module(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_SECRET_KEY="sk-lf-test",
    )
    import litellm

    litellm.success_callback = []
    litellm.failure_callback = []

    assert m.langfuse_enabled() is True
    assert m.setup_observability() is True
    assert "langfuse" in litellm.success_callback
    assert "langfuse" in litellm.failure_callback


# ── 4. 중복 호출해도 콜백이 중복 등록되지 않음 ────────────────
def test_setup_is_idempotent(monkeypatch):
    m = _fresh_module(
        monkeypatch,
        LANGFUSE_PUBLIC_KEY="pk-lf-test",
        LANGFUSE_SECRET_KEY="sk-lf-test",
    )
    import litellm

    litellm.success_callback = []
    litellm.failure_callback = []

    m.setup_observability()
    m.setup_observability()  # 두 번째 호출은 캐시되어 재등록 안 함
    assert litellm.success_callback.count("langfuse") == 1
    assert litellm.failure_callback.count("langfuse") == 1

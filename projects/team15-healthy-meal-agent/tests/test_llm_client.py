"""
tests/test_llm_client.py
litellm Router 기반 Fallback 구성 테스트.
외부 API 호출 없이 Router의 model_list 구성만 검증한다(결정론적, CI-safe).
"""

import importlib

import app.services.llm_client as lc


def _rebuild(monkeypatch, **env):
    """환경변수를 세팅하고 Router 캐시를 리셋해 재구성하게 한다."""
    monkeypatch.setenv("UPSTAGE_API_KEY", "test-upstage-key")
    monkeypatch.setenv("LLM_MODEL", "solar-pro3")
    for key in ("OPENAI_API_KEY", "FALLBACK_MODEL"):
        monkeypatch.delenv(key, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    importlib.reload(lc)
    lc._ROUTER = None  # 캐시 리셋
    return lc


def _model_names(router):
    return [m["model_name"] for m in router.model_list]


def _underlying_models(router):
    return [m["litellm_params"]["model"] for m in router.model_list]


# ── 1. OpenAI 키가 있으면 Solar + OpenAI 두 모델이 같은 그룹에 등록 ────────────
def test_router_has_openai_fallback_when_key_present(monkeypatch):
    m = _rebuild(monkeypatch, OPENAI_API_KEY="sk-test")
    router = m.get_router()
    # 이름을 분리해야 Solar가 1순위로 고정된다(같은 이름이면 로드밸런싱돼 랜덤 분배됨).
    assert _model_names(router) == ["primary", "backup"]
    models = _underlying_models(router)
    assert any("solar-pro3" in x for x in models)
    assert any("gpt" in x for x in models)  # OpenAI 보험 모델 포함
    # primary(Solar) 실패 시에만 backup(OpenAI)으로 폴백하도록 규칙이 걸려야 한다.
    assert router.fallbacks == [{"primary": ["backup"]}]


# ── 2. OpenAI 키가 없으면 Solar 단독 (보험만 빠지고 정상 동작) ────────────
def test_router_solar_only_without_openai_key(monkeypatch):
    m = _rebuild(monkeypatch)
    router = m.get_router()
    assert _model_names(router) == ["primary"]
    assert all("gpt" not in x for x in _underlying_models(router))


# ── 3. FALLBACK_MODEL 환경변수로 보험 모델을 바꿀 수 있다 ────────────
def test_fallback_model_is_configurable(monkeypatch):
    m = _rebuild(monkeypatch, OPENAI_API_KEY="sk-test", FALLBACK_MODEL="gpt-4o")
    router = m.get_router()
    assert any(x == "gpt-4o" for x in _underlying_models(router))


# ── 4. Router는 캐시된다(매번 새로 만들지 않음) ────────────
def test_router_is_cached(monkeypatch):
    m = _rebuild(monkeypatch, OPENAI_API_KEY="sk-test")
    assert m.get_router() is m.get_router()

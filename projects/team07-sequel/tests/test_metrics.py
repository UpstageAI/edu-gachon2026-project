"""비용/토큰/KPI 로직 점검 — 단가 환산 · 질의 단위 토큰 합산 · delta · Langfuse 프록시 조립.

프레임워크 없이 assert 로만 검증(프로젝트 관례, test_session_store.py 참고).
외부(Upstage/Langfuse)는 호출하지 않는다 — litellm.completion 과 httpx 를 가짜로 갈아끼운다.

실행:  uv run python -m tests.test_metrics
"""
from __future__ import annotations

import asyncio
import json

import httpx

from app.core import llm
from app.core.pricing import token_cost_usd
from app.services import metrics_service


# ── 단가 환산 (money path — 정확해야 함) ──
def test_token_cost_usd_math() -> None:
    # 입력 1,000,000 → $0.15, 출력 1,000,000 → $0.60
    assert token_cost_usd(1_000_000, 0) == 0.15
    assert token_cost_usd(0, 1_000_000) == 0.60
    assert token_cost_usd(1_000_000, 1_000_000) == 0.75
    assert token_cost_usd(0, 0) == 0.0


# ── collect_usage: 한 질의의 여러 complete() 를 합산 ──
def test_collect_usage_accumulates(monkeypatch) -> None:
    class _Usage:
        def __init__(self, p, c):
            self.prompt_tokens, self.completion_tokens = p, c

    class _Resp:
        def __init__(self, p, c):
            self.usage = _Usage(p, c)
            self.choices = [type("C", (), {"message": type("M", (), {"content": "x"})()})()]

    calls = iter([(100, 20), (50, 10), (30, 5)])
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: _Resp(*next(calls)))

    with llm.collect_usage() as usage:
        llm.complete("solar-mini", [{"role": "user", "content": "a"}])
        llm.complete("solar-pro2", [{"role": "user", "content": "b"}])
        llm.complete("solar-pro2", [{"role": "user", "content": "c"}])

    assert usage == {"input": 180, "output": 35, "calls": 3}
    # 블록 밖에서는 누적 안 됨 (contextvar 해제)
    monkeypatch.setattr(llm.litellm, "completion", lambda **kw: _Resp(999, 999))
    llm.complete("solar-mini", [{"role": "user", "content": "d"}])
    assert usage == {"input": 180, "output": 35, "calls": 3}


# ── delta 계산 ──
def test_delta_pct() -> None:
    assert metrics_service._delta_pct(120, 100) == 20.0
    assert metrics_service._delta_pct(80, 100) == -20.0
    assert metrics_service._delta_pct(50, 0) is None   # 어제 0 → 비교 불가
    assert metrics_service._delta_pct(0, 100) == -100.0


# ── dashboard_kpis: Langfuse 응답을 KPI 로 조립 (httpx mock) ──
def _mock_langfuse(today_row: dict, yday_row: dict):
    """fromTimestamp 로 오늘/어제 구간을 구분해 canned 응답을 준다."""
    def handler(request: httpx.Request) -> httpx.Response:
        q = json.loads(dict(request.url.params)["query"])
        # 오늘 구간은 어제 구간보다 fromTimestamp 가 크다 → 문자열 비교로 구분
        frm = q["fromTimestamp"]
        # 두 요청 중 더 이른(from 작은) 것이 어제. 여기선 호출 인자로 판별하지 않고
        # from 문자열을 비교하기 위해 today0 를 캡처해 둔다(아래 세팅).
        row = today_row if frm >= _today_from[0] else yday_row
        return httpx.Response(200, json={"data": [row]})
    return handler


_today_from = [""]  # 클로저로 today 구간 시작 iso 를 주입


def test_dashboard_kpis_assembles(monkeypatch) -> None:
    monkeypatch.setattr(metrics_service.settings, "langfuse_public_key", "pk-x")
    monkeypatch.setattr(metrics_service.settings, "langfuse_secret_key", "sk-x")
    monkeypatch.setattr(metrics_service.settings, "langfuse_host", "https://lf.example")

    today_row = {"count_count": 100, "sum_inputTokens": 1_000_000,
                 "sum_outputTokens": 500_000, "avg_latency": 900.0}
    yday_row = {"count_count": 80, "sum_inputTokens": 800_000,
                "sum_outputTokens": 400_000, "avg_latency": 1000.0}

    transport = httpx.MockTransport(_mock_langfuse(today_row, yday_row))
    real_client = httpx.AsyncClient

    def _client(**kw):
        # today0 iso 를 클로저에 주입(첫 호출 시점 기준) — 두 구간 판별용
        return real_client(transport=transport, **kw)

    # today0 의 iso(UTC) 를 알아내기 위해 dashboard 내부와 같은 로직으로 계산
    import datetime as dt
    now = dt.datetime.now(metrics_service._KST)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    _today_from[0] = today0.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    monkeypatch.setattr(metrics_service.httpx, "AsyncClient", _client)

    res = asyncio.run(metrics_service.dashboard_kpis())
    assert res.available is True
    by = {k.key: k for k in res.kpis}
    assert by["llm_calls"].value == 100 and by["llm_calls"].delta_pct == 25.0
    assert by["total_tokens"].value == 1_500_000
    # cost = 1e6*0.15 + 5e5*0.6 = 0.15 + 0.30 = 0.45
    assert by["cost_usd"].value == 0.45
    assert by["avg_latency_ms"].value == 900.0 and by["avg_latency_ms"].delta_pct == -10.0


def test_dashboard_kpis_no_keys(monkeypatch) -> None:
    monkeypatch.setattr(metrics_service.settings, "langfuse_public_key", "")
    monkeypatch.setattr(metrics_service.settings, "langfuse_secret_key", "")
    res = asyncio.run(metrics_service.dashboard_kpis())
    assert res.available is False and res.kpis == []


# ── 프레임워크 없는 러너 (monkeypatch 는 간이 구현) ──
class _MonkeyPatch:
    def __init__(self):
        self._undo = []

    def setattr(self, target, name, value):
        old = getattr(target, name)
        self._undo.append((target, name, old))
        setattr(target, name, value)

    def undo(self):
        for target, name, old in reversed(self._undo):
            setattr(target, name, old)


if __name__ == "__main__":
    import inspect

    for name, fn in list(globals().items()):
        if not name.startswith("test_"):
            continue
        mp = _MonkeyPatch()
        try:
            fn(mp) if "monkeypatch" in inspect.signature(fn).parameters else fn()
            print(f"ok  {name}")
        finally:
            mp.undo()
    print("all metrics checks passed")

"""대시보드 KPI 서비스 — Langfuse Metrics API 집계를 프록시한다.

Home 화면 KPI 카드(LLM 호출 수·평균 응답시간·토큰·비용)를 채운다. 핵심 LLM 콜이
litellm→langfuse 콜백으로 이미 관측치(토큰·지연)로 쌓이므로, 그걸 Metrics API 로
일자 집계해 온다. 단 Langfuse 는 solar 단가를 몰라 totalCost 를 0 으로 남기므로
(실측 확인), 비용은 여기서 토큰×Upstage 단가로 직접 계산한다(app.core.pricing).

기준 시간대: KST. '오늘'(00:00~현재)과 '어제'(전일 00:00~00:00)를 각각 집계해 delta 를
만든다. Langfuse 키가 없거나 조회 실패면 available=False + 빈 kpis (대시보드는 빈 카드로
그리면 됨 — 에러로 터뜨리지 않는다).

레이어: controller(api) → service(여기) → Langfuse Metrics API (외부)
"""
from __future__ import annotations

import base64
import datetime as dt
import json
import logging

import httpx

from app.core.pricing import token_cost_usd
from app.core.settings import settings
from app.schemas.query import Kpi, MetricsResponse

logger = logging.getLogger(__name__)

_KST = dt.timezone(dt.timedelta(hours=9))
_PATH = "/api/public/v2/metrics"
# observations 뷰에는 (a) LangGraph 노드 SPAN(토큰 없음)과 (b) litellm GENERATION(토큰 보유)이
# 섞여 있다. 타입 필터 없이 세면 llm_calls 가 노드 span 수로 부풀고 토큰 합은 span(0)에 눌려
# 항상 0 이 된다. GENERATION 만 집계해야 실제 LLM 콜 수·토큰·콜당 지연이 나온다.
_FILTERS = [{"column": "type", "operator": "=", "value": "GENERATION", "type": "string"}]
_MEASURES = [
    {"measure": "count", "aggregation": "count"},
    {"measure": "inputTokens", "aggregation": "sum"},
    {"measure": "outputTokens", "aggregation": "sum"},
    {"measure": "latency", "aggregation": "avg"},
]


def _delta_pct(today: float, yday: float) -> float | None:
    """어제 대비 증감률(%). 어제 값이 0/없으면 비교 불가 → None."""
    if not yday:
        return None
    return round((today - yday) / yday * 100, 1)


async def _window(client: httpx.AsyncClient, from_ts: str, to_ts: str) -> dict:
    """[from,to) 한 구간 집계 1행 → {count, input, output, latency}."""
    query = {
        "view": "observations",
        "metrics": _MEASURES,
        "dimensions": [],
        "filters": _FILTERS,  # GENERATION 만 (노드 span 제외)
        "fromTimestamp": from_ts,
        "toTimestamp": to_ts,
    }
    r = await client.get(_PATH, params={"query": json.dumps(query)})
    r.raise_for_status()
    rows = r.json().get("data", [])
    row = rows[0] if rows else {}
    return {
        "count": float(row.get("count_count") or 0),
        "input": float(row.get("sum_inputTokens") or 0),
        "output": float(row.get("sum_outputTokens") or 0),
        "latency": float(row.get("avg_latency") or 0),
    }


async def dashboard_kpis() -> MetricsResponse:
    """오늘(KST) KPI + 어제 대비 delta. 키 없음/조회 실패 시 available=False."""
    now = dt.datetime.now(_KST)
    today0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    as_of = today0.strftime("%Y-%m-%d")

    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        return MetricsResponse(available=False, as_of=as_of)

    yday0 = today0 - dt.timedelta(days=1)

    def iso(t: dt.datetime) -> str:  # Langfuse 는 UTC ISO 기대 → KST→UTC 변환
        return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    auth = base64.b64encode(
        f"{settings.langfuse_public_key}:{settings.langfuse_secret_key}".encode()).decode()
    try:
        async with httpx.AsyncClient(
            base_url=settings.langfuse_host,
            headers={"Authorization": f"Basic {auth}"},
            timeout=15,
        ) as client:
            today = await _window(client, iso(today0), iso(now))
            yday = await _window(client, iso(yday0), iso(today0))
    except Exception:  # noqa: BLE001 — 대시보드는 실패해도 빈 카드로. 상세는 로그만.
        logger.exception("Langfuse metrics 조회 실패")
        return MetricsResponse(available=False, as_of=as_of)

    t_tokens = today["input"] + today["output"]
    y_tokens = yday["input"] + yday["output"]
    t_cost = token_cost_usd(int(today["input"]), int(today["output"]))
    y_cost = token_cost_usd(int(yday["input"]), int(yday["output"]))

    kpis = [
        Kpi(key="llm_calls", value=today["count"],
            delta_pct=_delta_pct(today["count"], yday["count"])),
        Kpi(key="avg_latency_ms", value=round(today["latency"], 1),
            delta_pct=_delta_pct(today["latency"], yday["latency"])),
        Kpi(key="total_tokens", value=t_tokens,
            delta_pct=_delta_pct(t_tokens, y_tokens)),
        Kpi(key="cost_usd", value=t_cost,
            delta_pct=_delta_pct(t_cost, y_cost)),
    ]
    return MetricsResponse(kpis=kpis, as_of=as_of, available=True)

"""Explain the daily market report with RSS/RAG evidence."""

from __future__ import annotations

import json
from typing import Any

from app.agents import rag
from app.agents.report_catalog import indicator_aliases
from app.agents.report_render import build_indicator_views
from app.core import llm, observability
from app.core.schemas import BatchRunResult, NewsEvidence, Topic
from app.repositories.protocols import RepositoryBundle


DISCLAIMER = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."
REPORT_EXPLAIN_SYSTEM = (
    "너는 금융 지표 리포트를 설명하는 브리핑 에디터다. "
    "제공된 지표 수치와 뉴스 근거만 사용해 한국어 JSON을 작성한다. "
    "수치, 단위, 방향을 임의로 바꾸지 말고 뉴스 근거가 없으면 원인을 단정하지 말 것. "
    "매수, 매도, 목표가, 수익 보장 같은 투자 판단 표현은 금지한다. "
    'JSON 키: {"summary": "한 문장 요약", "focus_points": ["지표별 설명"], "watch_items": ["봐야 할 항목"]}'
)

_RATE_IDS = {"kr10y", "us10y", "jp10y", "kr_policy_rate", "us_policy_rate", "eu_policy_rate"}
_DIRECTION_SYMBOL = {"up": "▲", "down": "▼", "flat": "■"}


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _change_score(view: dict[str, Any]) -> float:
    indicator_id = str(view.get("indicator_id") or "")
    if indicator_id in _RATE_IDS:
        return abs(_as_float(view.get("change_value")) or 0.0)
    return abs(_as_float(view.get("change_percent")) or _as_float(view.get("change_value")) or 0.0)


def _change_text(view: dict[str, Any]) -> str:
    direction = str(view.get("direction") or "flat")
    symbol = _DIRECTION_SYMBOL.get(direction, "■")
    indicator_id = str(view.get("indicator_id") or "")
    if indicator_id in _RATE_IDS:
        change_value = _as_float(view.get("change_value"))
        if change_value is None:
            return f"{symbol} -"
        return f"{symbol} {abs(change_value):.4f}%p"

    change_percent = _as_float(view.get("change_percent"))
    if change_percent is None:
        return f"{symbol} -"
    return f"{symbol} {abs(change_percent):.2f}%"


def select_focus_items(result: BatchRunResult, *, max_items: int = 3) -> list[dict[str, Any]]:
    """Select the largest report moves from a BatchRunResult."""

    if result.report is None:
        return []

    indicators = [item.model_dump(mode="json") for item in result.report.indicators]
    views = build_indicator_views(indicators, result.report.missing_indicators)
    candidates: list[dict[str, Any]] = []
    for view in views:
        if view.get("missing"):
            continue
        score = _change_score(view)
        if score <= 0:
            continue
        item = dict(view)
        item["score"] = score
        item["change_text"] = _change_text(view)
        item["evidence"] = []
        item["evidence_count"] = 0
        candidates.append(item)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates[:max_items]


def _topic_id_for_view(view: dict[str, Any]) -> str | None:
    slot = indicator_aliases().get(str(view.get("indicator_id") or ""))
    if slot is None:
        return None
    return next((alias for alias in slot.aliases if alias.startswith("topic_")), None)


def _fallback_topic(view: dict[str, Any]) -> Topic:
    indicator_id = str(view.get("indicator_id") or "unknown")
    display_name = str(view.get("display_name") or indicator_id)
    slot = indicator_aliases().get(indicator_id)
    keywords = [display_name, indicator_id]
    if slot is not None:
        keywords.extend(alias for alias in slot.aliases if not alias.startswith("topic_"))
    return Topic.model_validate(
        {
            "topic_id": f"report_{indicator_id}",
            "name": display_name,
            "normalized_name": indicator_id,
            "type": "indicator",
            "source_mapping": [
                {
                    "provider": "rag",
                    "query": display_name,
                    "news_keywords": sorted(set(keywords)),
                }
            ],
        }
    )


def topic_for_report_view(view: dict[str, Any], repos: RepositoryBundle) -> Topic:
    """Map a report indicator view to a catalog topic for RAG retrieval."""

    topic_id = _topic_id_for_view(view)
    if topic_id:
        try:
            return repos.topics.get(topic_id)
        except Exception:
            pass
    return _fallback_topic(view)


def attach_rag_evidence(
    focus_items: list[dict[str, Any]],
    *,
    repos: RepositoryBundle,
    result: BatchRunResult,
    evidence_per_item: int = 2,
) -> list[dict[str, Any]]:
    """Attach recent RSS/RAG evidence to report focus items."""

    since = rag.since_for(result.run_date)
    enriched: list[dict[str, Any]] = []
    for item in focus_items:
        current = dict(item)
        try:
            topic = topic_for_report_view(current, repos)
            evidence = rag.postprocess_evidence(
                repos.news.match(topic, since, rag.RAG_CANDIDATES),
                k=evidence_per_item,
                max_per_source=1,
            )
        except Exception:
            evidence = []
        current["evidence"] = [ev.model_dump(mode="json") for ev in evidence]
        current["evidence_count"] = len(evidence)
        enriched.append(current)
    return enriched


def _fallback_summary(focus_items: list[dict[str, Any]]) -> dict[str, Any]:
    if not focus_items:
        return {
            "summary": "오늘 리포트에서 뚜렷한 변동 지표를 찾지 못했어요.",
            "focus_points": [],
            "watch_items": [],
        }

    names = ", ".join(str(item["display_name"]) for item in focus_items[:3])
    points = []
    watch_items = []
    for item in focus_items:
        evidence = item.get("evidence") or []
        if evidence:
            sources = ", ".join(dict(ev).get("source", "") for ev in evidence if dict(ev).get("source"))
            points.append(
                f"{item['display_name']}은 {item['change_text']} 움직였고, 관련 RSS에서는 {sources}의 뉴스가 함께 포착됐어요."
            )
        else:
            points.append(
                f"{item['display_name']}은 {item['change_text']} 움직였어요. 연결 가능한 RSS 뉴스 근거가 아직 부족해 지표 변화 중심으로만 볼게요."
            )
        watch_items.append(str(item["display_name"]))
    return {
        "summary": f"오늘은 {names} 흐름을 먼저 보면 좋아요.",
        "focus_points": points,
        "watch_items": watch_items,
    }


def _llm_summary(result: BatchRunResult, focus_items: list[dict[str, Any]]) -> dict[str, Any]:
    payload = [
        {
            "indicator": item["display_name"],
            "value": item["value_text"],
            "change": item["change_text"],
            "evidence": [
                {
                    "title": ev.get("title"),
                    "source": ev.get("source"),
                    "snippet": ev.get("snippet"),
                }
                for ev in item.get("evidence", [])
            ],
        }
        for item in focus_items
    ]
    metadata = observability.build_llm_metadata(
        trace_id=result.trace_id,
        run_id=result.run_id,
        node="explain_market_report",
        tags=["finbrief", "report", "explanation"],
        extra={
            "run_date": result.run_date.isoformat(),
            "focus_count": len(focus_items),
            "evidence_count": sum(int(item.get("evidence_count", 0)) for item in focus_items),
        },
    )
    return llm.chat_json(
        REPORT_EXPLAIN_SYSTEM,
        json.dumps(payload, ensure_ascii=False),
        metadata=metadata,
        guardrail_profile="generic",
    )


def _summary_for(result: BatchRunResult, focus_items: list[dict[str, Any]]) -> dict[str, Any]:
    if llm.use_llm():
        try:
            raw = _llm_summary(result, focus_items)
            if isinstance(raw.get("focus_points"), list):
                return raw
        except Exception:
            pass
    return _fallback_summary(focus_items)


def _format_reply(summary: dict[str, Any], focus_items: list[dict[str, Any]]) -> str:
    lines = ["📊 오늘은 이 부분을 먼저 보면 좋아요!", "", str(summary.get("summary") or "")]
    focus_points = list(summary.get("focus_points") or [])
    for index, item in enumerate(focus_items, start=1):
        lines.append("")
        lines.append(f"{index}. **{item['display_name']}** {item['value_text']} ({item['change_text']})")
        point = focus_points[index - 1] if index - 1 < len(focus_points) else ""
        if point:
            lines.append(f"   {point}")
        evidence = item.get("evidence") or []
        if evidence:
            sources = ", ".join(sorted({str(ev.get("source")) for ev in evidence if ev.get("source")}))
            lines.append(f"   근거: {sources}")

    if not any(item.get("evidence") for item in focus_items):
        lines.append("")
        lines.append("연결 가능한 RSS 뉴스 근거가 아직 부족해요. 우선 지표 변화 중심으로만 정리했어요!")

    lines.append("")
    lines.append(f"※ {DISCLAIMER}")
    return "\n".join(line for line in lines if line is not None)


def _focus_payload(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "indicator_id": item["indicator_id"],
        "display_name": item["display_name"],
        "direction": item["direction"],
        "value_text": item["value_text"],
        "change_text": item["change_text"],
        "change_value": item.get("change_value"),
        "change_percent": item.get("change_percent"),
        "unit": item.get("unit"),
        "score": item.get("score"),
        "evidence_count": int(item.get("evidence_count", 0)),
        "evidence": item.get("evidence", []),
    }


def build_report_explanation(
    result: BatchRunResult,
    *,
    repos: RepositoryBundle,
    max_focus: int = 3,
) -> dict[str, Any]:
    """Build an API/Discord-ready report explanation payload."""

    focus_items = select_focus_items(result, max_items=max_focus)
    focus_items = attach_rag_evidence(focus_items, repos=repos, result=result)
    summary = _summary_for(result, focus_items)
    reply = _format_reply(summary, focus_items)
    return {
        "run_date": result.run_date.isoformat(),
        "status": result.status,
        "summary": summary.get("summary", ""),
        "focus_items": [_focus_payload(item) for item in focus_items],
        "reply": reply,
        "disclaimer": DISCLAIMER,
    }

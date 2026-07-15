"""Phase 0 노드 stub. [팀원]=데이터 파트, [나]=LangGraph/카드.
   지금은 fixtures 로 동작만 확인(관통). 실구현 시 파일 분리."""
from __future__ import annotations

import html
import os
import re
import tempfile
from datetime import date
from typing import Any

from langgraph.types import Send

from .state import BriefState
from . import fixtures as fx
from . import rag
from .card_schema import CardContent
from .render import render_card
from .report_render import render_market_report_image
from app.core import observability
from app.core import llm
from app.core.schemas import CardArtifact, NewsEvidence, Topic, TopicAnalysis
from app.repositories.protocols import RepositoryBundle, RepositoryNotFoundError
from app.tools import image_gen
from app.tools.data_sources import fred, yfinance_source
from app.tools.news import rss, tagging
from app.tools.embedding.upstage import EMBEDDING_PASSAGE_MODEL, UpstageEmbeddingProvider
from app.services import notifier, topic_ingestion


_DIR = os.path.dirname(__file__)
DISCLAIMER = "본 브리핑은 투자 조언이 아닌 참고용 정보입니다."

IMAGE_PROMPT_SYSTEM = (
    "You are an image-prompt writer for a financial card news. "
    "Given the card info, output ONE english image prompt as JSON {\"prompt\": \"...\"}. "
    "The MAIN SUBJECT of the illustration MUST be the given topic itself "
    "(the company/asset/theme in 'topic'); use headline/body only for mood. "
    "Do NOT depict unrelated entities that merely appear in the body. "
    "Style: clean isometric illustration, muted palette. "
    "The illustration MUST contain no text, no letters, no numbers."
)


# ---- 공유 단계 (main graph) ----
def _live_ingestion() -> Any:
    """Supabase ingestion repository (live 모드 전용). 실패 시 None."""
    try:
        from app.repositories.supabase import SupabaseIngestionRepository
        from app.repositories.supabase_client import create_supabase_client

        return SupabaseIngestionRepository(create_supabase_client())
    except Exception:
        return None


def _embed_passage_with_retry(provider: Any, document: Any, *, attempts: int = 3) -> Any:
    """passage 임베딩. 일시 오류(레이트리밋/타임아웃) 시 백오프 재시도. 최종 실패면 None."""
    import time

    for i in range(attempts):
        try:
            return provider.embed_passage(document)
        except Exception:
            if i < attempts - 1:
                time.sleep(1.0 * (i + 1))
    return None


def _news_id_by_url(rows: Any) -> dict[str, str]:
    """upsert_news_documents 응답에서 url -> DB news id 매핑을 만든다."""
    mapping: dict[str, str] = {}
    if not isinstance(rows, list):
        return mapping
    for row in rows:
        if isinstance(row, dict) and row.get("url") and row.get("id"):
            mapping[str(row["url"])] = str(row["id"])
    return mapping


def ingest_news(state: BriefState) -> dict[str, Any]:
    """뉴스 수집→태깅→passage 임베딩→Supabase 적재. live_data에서만 동작."""
    if not state.get("live_data"):
        return {}
    repos: RepositoryBundle | None = state.get("repositories")
    if repos is None:
        return {}

    ingestion = state.get("ingestion") or _live_ingestion()
    provider = state.get("embedding_provider") or UpstageEmbeddingProvider()
    if ingestion is None:
        return {"errors": [{"code": "INGEST_SKIPPED", "message": "no ingestion repository",
                            "node": "ingest_news", "topic": None}]}

    try:
        topics = repos.topics.list_catalog()
        since = rag.since_for(_parse_run_date(state["run_date"]))
        documents = rss.fetch_rss_news()
        documents = rss.filter_recent_news(documents, since=since)
        documents = tagging.tag_news_for_topics(documents, topics, include_general_market=True)
        if not documents:
            return {}

        id_by_url = _news_id_by_url(ingestion.upsert_news_documents(documents))
        # 이미 임베딩된 문서는 스킵(중복 재임베딩 방지). 미임베딩은 다음 실행에 다시 대상이 됨.
        all_ids = [i for i in (id_by_url.get(str(d.url)) for d in documents) if i]
        already = (ingestion.existing_passage_news_ids(all_ids)
                   if hasattr(ingestion, "existing_passage_news_ids") else set())
        targets = [d for d in documents
                   if id_by_url.get(str(d.url)) and id_by_url.get(str(d.url)) not in already]

        # 배치 임베딩: 문서 1건당 호출 1번(→레이트리밋) 대신 한 호출에 다건.
        if hasattr(provider, "embed_passages"):
            embeddings = provider.embed_passages(targets)
        else:   # 폴백(mock 등): 단건 재시도
            embeddings = [_embed_passage_with_retry(provider, d) for d in targets]

        rows: list[dict[str, Any]] = []
        failed = 0
        for document, embedding in zip(targets, embeddings):
            if embedding is None:
                failed += 1
                continue
            rows.append({
                "news_id": id_by_url[str(document.url)],
                "embedding": embedding,
                "embedding_model": EMBEDDING_PASSAGE_MODEL,
                "embedding_kind": "passage",
            })
        if rows:
            ingestion.upsert_news_embeddings(rows)
        result: dict[str, Any] = {}
        if failed:
            result["errors"] = [{"code": "EMBED_PARTIAL", "message": f"{failed} embeddings failed after retries",
                                 "node": "ingest_news", "topic": None}]
        return result
    except Exception as exc:
        return {"errors": [{"code": "INGEST_FAILED", "message": str(exc),
                            "node": "ingest_news", "topic": None}]}


def _collect_topic_indicator(topic: Topic, run_date: date) -> list[Any]:
    """토픽 source_mapping을 provider별로 분기해 최신 IndicatorValue[]를 수집."""
    return topic_ingestion.collect_topic_indicators(topic, run_date)


def collect_indicators(state: BriefState) -> dict[str, Any]:
    """전체 지표 수집. live_data에서는 source_mapping 실수집, 아니면 fixture."""
    repos: RepositoryBundle | None = state.get("repositories")
    if not state.get("live_data") or repos is None:
        indicators = [{"indicator_id": k, "source": "fixture", **v} for k, v in fx.FIXTURE_INDICATORS.items()]
        return {"indicators": indicators, "report_url": None}

    run_date = _parse_run_date(state["run_date"])
    indicators: list[dict[str, Any]] = []
    missing: list[str] = []
    for graph_topic in state.get("unique_topics", []):
        try:
            topic_model = repos.topics.get(graph_topic["topic_id"])
        except RepositoryNotFoundError:
            continue
        values = _collect_topic_indicator(topic_model, run_date)
        if not values:
            missing.append(graph_topic["topic_id"])
            continue
        latest = values[-1]
        indicators.append({
            "indicator_id": graph_topic["topic_id"],
            "name": topic_model.name,
            "source": latest.source,
            "value": latest.current_value,
            "prev": latest.previous_value,
            "change_pct": latest.change_percent,
            "unit": latest.unit,
        })

    result: dict[str, Any] = {"indicators": indicators, "report_url": None}
    if missing:
        result["missing_indicators"] = missing
    return result


def build_report_image(state: BriefState) -> dict[str, Any]:
    """전체 주요 지표 리포트 이미지를 한 번 생성하고 report_url에 기록한다.
    모든 사용자 공통 리포트이므로 live 모드에서는 구독과 무관하게 카탈로그 전체를 실수집한다."""
    try:
        run_date = _parse_run_date(state["run_date"])
        if state.get("live_data"):
            from .report_ingestion import collect_report_indicators
            indicators, missing = collect_report_indicators(run_date)
        else:
            indicators = state.get("indicators", [])
            missing = state.get("missing_indicators", [])
        report_url = render_market_report_image(
            indicators,
            run_date=run_date,
            missing_indicators=missing,
        )
        return {
            "report_url": report_url,
            "report_indicators": indicators,
            "report_missing_indicators": missing,
        }
    except Exception as exc:
        return {
            "errors": [
                {
                    "code": "report_image_render",
                    "message": str(exc),
                    "node": "build_report_image",
                    "topic": None,
                }
            ]
        }


def _topic_category(topic: Topic) -> str:
    if topic.type == "asset" and topic.normalized_name == "btc":
        return "CRYPTO"
    if topic.type == "indicator" and any(token in topic.normalized_name for token in ("usd", "krw", "fx")):
        return "FX"
    if topic.type == "indicator":
        return "GLOBAL"
    return "MARKET"


def _graph_topic(topic: Topic) -> dict[str, Any]:
    return {
        "topic_id": topic.topic_id,
        "source_key": topic.normalized_name,
        "name": topic.name,
        "category": _topic_category(topic),
    }


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _topic_source_key(topic: dict[str, Any]) -> str:
    topic_id = str(topic.get("topic_id", ""))
    return str(topic.get("source_key") or topic.get("normalized_name") or topic_id.removeprefix("topic_"))


def _parse_run_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def collect_topics(state: BriefState) -> dict[str, Any]:
    """[나] 구독 토픽 → 고유 집합(dedup).
    배치 트리거 옵션: only_external_user 로 특정 계정만, deliver_cards=False 면 카드 생성 스킵."""
    repos: RepositoryBundle | None = state.get("repositories")
    only_user = state.get("only_external_user")            # external_user_id, None=전체
    want_cards = state.get("deliver_cards", True)
    if repos is not None:
        subscriptions = repos.subscriptions.list_active()
        if only_user:
            # 특정 계정만 필터(테스트용). 존재하는 ID 면 그 user 로, 없으면 매칭 0건.
            uid = repos.users.get_or_create("discord", only_user).user_id
            subscriptions = [s for s in subscriptions if s.user_id == uid]
        seen: set[str] = set()
        topics: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []

        if want_cards:                                     # 카드 미발송이면 토픽 생성 자체를 스킵(비용 절감)
            for subscription in subscriptions:
                topic_id = subscription.topic_id
                if topic_id in seen:
                    continue
                try:
                    topics.append(_graph_topic(repos.topics.get(topic_id)))
                    seen.add(topic_id)
                except RepositoryNotFoundError as exc:
                    errors.append(
                        {
                            "code": exc.code,
                            "message": str(exc),
                            "node": "collect_topics",
                            "topic": topic_id,
                        }
                    )

        result: dict[str, Any] = {
            "subscriptions": [item.model_dump(mode="json") for item in subscriptions],
            "unique_topics": topics,
        }
        if errors:
            result["errors"] = errors
        return result

    seen, uniq = set(), []
    for sub in fx.FIXTURE_SUBSCRIPTIONS:
        tid = sub["topic_id"]
        if tid not in seen:
            seen.add(tid)
            uniq.append(next(t for t in fx.FIXTURE_TOPICS if t["topic_id"] == tid))
    return {"unique_topics": uniq}


def _indicators_index(indicators: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("indicator_id")): item for item in indicators if item.get("indicator_id")}


def retrieve_evidence(state: BriefState) -> dict[str, Any]:
    """[나] fan-out 이전, 캐시 미스 토픽에 지표+뉴스 근거(RAG)를 채운다.

    live_data 전용. 여기서 repos.news.match(match_news RPC)를 호출하고 §rag 후처리를
    적용해 topic payload에 실어 보내므로, build_card는 네트워크/repos 접근 없이
    payload만 소비한다. live가 아니면 no-op이며 build_card가 fixture로 fallback한다.
    """
    if not state.get("live_data"):
        return {}
    repos: RepositoryBundle | None = state.get("repositories")
    topics = state.get("topics_to_generate", [])
    if repos is None or not topics:
        return {}

    since = rag.since_for(_parse_run_date(state["run_date"]))
    indicator_index = _indicators_index(state.get("indicators", []))
    enriched: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    with observability.span(
        "finbrief.rag.retrieve_evidence",
        metadata={
            "run_id": state.get("run_id"),
            "trace_id": state.get("trace_id"),
            "topic_count": len(topics),
            "rag_candidates": rag.RAG_CANDIDATES,
            "rag_k": rag.RAG_K,
        },
    ) as span:
        for graph_topic in topics:
            item = dict(graph_topic)
            try:
                topic_model = repos.topics.get(graph_topic["topic_id"])
                # 후보는 넓게(RAG_CANDIDATES), 최종은 postprocess 가 RAG_K 로 컷(threshold·다양성·top-k).
                evidence = rag.postprocess_evidence(
                    repos.news.match(topic_model, since, rag.RAG_CANDIDATES),
                    k=rag.RAG_K,
                )
                item["evidence"] = [ev.model_dump(mode="json") for ev in evidence]
            except Exception as exc:
                item["evidence"] = []
                errors.append({"code": "RAG_FAILED", "message": str(exc),
                               "node": "retrieve_evidence", "topic": graph_topic.get("topic_id")})
            item["indicator"] = indicator_index.get(graph_topic["topic_id"], {})
            enriched.append(item)
        span.update(
            output={
                "enriched_topics": len(enriched),
                "evidence_count": sum(len(item.get("evidence", [])) for item in enriched),
                "error_count": len(errors),
            }
        )

    result: dict[str, Any] = {"topics_to_generate": enriched}
    if errors:
        result["errors"] = errors
    return result


def dispatch(state: BriefState) -> list[Send] | str:
    """[나] Send API로 토픽마다 build_card 병렬 실행 (FanOut)."""
    topics = state.get("topics_to_generate")
    if topics is None:
        topics = state.get("unique_topics", [])
    if not topics:
        return "aggregate_cards"
    return [Send("build_card", {"topic": t, "run_date": state.get("run_date"),
                                 "run_id": state.get("run_id"), "trace_id": state.get("trace_id")})
            for t in topics]


def _card_from_artifact(card: CardArtifact) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "topic_id": card.topic_id,
        "category": "MARKET",
        "index_no": "00",
        "subtitle": card.title,
        "headline": card.analysis.headline,
        "lead": card.analysis.summary,
        "body": " ".join(card.analysis.key_points),
        "source": "FinBrief",
        "evidence": [item.model_dump(mode="json") for item in card.analysis.evidence],
        "disclaimer": card.analysis.disclaimer,
        "image_url": card.image_url,
        "image_path": card.image_url,
        "image_prompt": None,
        "rendered": bool(card.image_url),
        "verified": True,
        "cached": True,
    }


def _artifact_from_card(card: dict[str, Any], run_date: date) -> CardArtifact:
    topic_id = str(card["topic_id"])
    headline = str(card.get("headline") or card.get("subtitle") or topic_id)
    summary = str(card.get("lead") or card.get("body") or headline)
    key_points = [
        str(item)
        for item in (card.get("lead"), card.get("body"))
        if item
    ] or [summary]
    evidence: list[NewsEvidence] = []
    for item in card.get("evidence", []):
        try:
            evidence.append(NewsEvidence.model_validate(item))
        except Exception:
            continue

    return CardArtifact(
        card_id=str(card.get("card_id") or f"card_{topic_id}_{run_date.strftime('%Y%m%d')}"),
        topic_id=topic_id,
        run_date=run_date,
        title=headline,
        image_url=card.get("image_url") or card.get("image_path"),
        analysis=TopicAnalysis(
            topic_id=topic_id,
            run_date=run_date,
            headline=headline,
            summary=summary,
            key_points=key_points,
            evidence=evidence,
            disclaimer=str(card.get("disclaimer") or DISCLAIMER),
        ),
        cached=bool(card.get("cached", False)),
    )


def load_cached_cards(state: BriefState) -> dict[str, Any]:
    repos: RepositoryBundle | None = state.get("repositories")
    topics = state.get("unique_topics", [])
    if repos is None:
        return {"topics_to_generate": topics, "cached_cards": [], "reused_count": 0}

    run_date = _parse_run_date(state["run_date"])
    cached_cards: list[dict[str, Any]] = []
    topics_to_generate: list[dict[str, Any]] = []
    # 이미지 발송 모드인데 캐시 카드의 이미지가 로컬 임시경로라 현재 컨테이너에 없으면
    # 텍스트로 폴백되므로, 그 경우 캐시를 버리고 재생성한다.
    want_image = image_gen.image_enabled()

    for topic in topics:
        cached = repos.cards.get(topic["topic_id"], run_date)
        if cached is None:
            topics_to_generate.append(topic)
            continue
        img = str(cached.image_url or "")
        img_ok = img.startswith("http") or (bool(img) and os.path.exists(img))
        if want_image and not img_ok:
            topics_to_generate.append(topic)   # 이미지 원하는데 캐시 이미지 유실 → 재생성
        else:
            cached_cards.append(_card_from_artifact(cached.model_copy(update={"cached": True})))

    return {
        "cards": cached_cards,
        "cached_cards": cached_cards,
        "topics_to_generate": topics_to_generate,
        "reused_count": len(cached_cards),
    }


def persist_cards(state: BriefState) -> dict[str, Any]:
    repos: RepositoryBundle | None = state.get("repositories")
    if repos is None:
        return {}

    run_date = _parse_run_date(state["run_date"])
    errors: list[dict[str, Any]] = []
    for card in state.get("cards", []):
        if card.get("cached"):
            continue
        try:
            repos.cards.upsert(_artifact_from_card(card, run_date))
        except Exception as exc:
            errors.append(
                {
                    "code": "card_cache_upsert",
                    "message": str(exc),
                    "node": "persist_cards",
                    "topic": card.get("topic_id"),
                }
            )
    return {"errors": errors} if errors else {}


# ---- 토픽별 카드 생성 서브그래프 (build_card 안에서 순차 호출) ----
def _fetch_data(topic: dict) -> dict:            # retrieve_evidence가 채운 지표 or fixture fallback
    if "indicator" in topic:
        return topic.get("indicator") or {}
    return fx.FIXTURE_INDICATORS.get(topic["topic_id"], fx.FIXTURE_INDICATORS.get(_topic_source_key(topic), {}))

def _retrieve_news(topic: dict) -> list[dict]:   # retrieve_evidence가 채운 RAG 근거 or fixture fallback
    if "evidence" in topic:
        return topic.get("evidence") or []
    return fx.FIXTURE_NEWS.get(topic["topic_id"], fx.FIXTURE_NEWS.get(_topic_source_key(topic), []))

def _clip(s, n: int) -> str:
    s = str(s).strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _clip_head(s, n: int) -> str:
    """제목은 한도 초과 시 단어(공백) 경계에서 끊어 숫자·단어 중간 잘림을 막는다."""
    s = str(s).strip()
    if len(s) <= n:
        return s
    cut = s[:n].rstrip()
    sp = cut.rfind(" ")
    return cut[:sp].rstrip() if sp >= n * 0.5 else cut


def _clip_body(s, n: int) -> str:
    """본문은 한도 내 마지막 문장 경계('다.', '. ' 등)에서 깔끔하게 끊는다."""
    s = str(s).strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    best = 0
    for m in ("다.", ". ", "! ", "? ", "요."):
        p = cut.rfind(m)
        if p >= 0:
            end = p + len(m)
            if end >= n * 0.6 and end > best:
                best = end
    if best:
        return cut[:best].rstrip()
    # 문장 경계가 없으면 마지막 공백(단어 경계)에서 끊어 단어 중간 잘림 방지.
    sp = cut.rfind(" ")
    if sp >= n * 0.5:
        return cut[:sp].rstrip() + "…"
    return cut[: n - 1].rstrip() + "…"


def _display_unit(topic: dict, data: dict) -> str:
    """지표 단위/통화. data.unit 우선, 없으면 카테고리로 추론(원↔달러 혼동 방지)."""
    u = str(data.get("unit") or "").strip()
    if u:
        return u
    cat = str(topic.get("category", "")).upper()
    name = str(topic.get("name", ""))
    if cat == "CRYPTO":
        return "USD"
    if cat == "FX" or "환율" in name:
        return "원"
    if "금리" in name or cat == "GLOBAL":
        return "%"
    return "pt"


def _fmt_num(value: Any, decimals: int) -> str:
    """반올림 후 불필요한 소수점 0을 제거해 문자열로. (예: 3.50->"3.5", 3.0->"3")"""
    try:
        v = round(float(value), decimals)
    except (TypeError, ValueError):
        return str(value)
    if decimals <= 0:
        return str(int(v))
    return f"{v:.{decimals}f}".rstrip("0").rstrip(".") or "0"


def _fmt_value(value: Any, unit: str) -> str:
    """지표 현재값 포맷: pt(지수)·원(한국 종목/환율)은 정수, 그 외(달러 등)는 소수 2자리."""
    if value is None:
        return ""
    decimals = 0 if str(unit or "").strip() in ("pt", "원") else 2
    return _fmt_num(value, decimals)


def _fmt_pct(value: Any) -> str:
    """변화율(%) 포맷: 소수 2자리."""
    if value is None:
        return "0"
    return _fmt_num(value, 2)


def _user_prompt(topic: dict, data: dict, news: list[dict]) -> str:
    unit = _display_unit(topic, data)
    lines = [f"topic: {topic['name']} ({topic['category']})",
             f"indicator: 현재값 {_fmt_value(data.get('value'), unit)}, "
             f"변화율 {_fmt_pct(data.get('change_pct'))}%",
             f"단위/통화: {unit} (이 단위를 그대로 사용할 것)",
             "news:"]
    lines += [f"- {n['title']}: {n['snippet']}" for n in news] or ["- (none)"]
    return "\n".join(lines)


def _local_analysis(topic: dict, data: dict, news: list[dict]) -> dict:
    unit = _display_unit(topic, data)
    chg = data.get("change_pct", 0.0) or 0.0
    arrow = "상승" if chg > 0 else ("하락" if chg < 0 else "보합")
    # 폴백 본문: 근거 뉴스 스니펫들을 합쳐 HTML 엔티티 제거 후 문장 경계로 정리.
    parts = [html.unescape(str(n.get("snippet") or n.get("title") or "")).strip()
             for n in (news or [])[:3]]
    body = _clip_body(" ".join(p for p in parts if p), 240)
    return {"headline": f"{topic['name']} {arrow}",
            "lead": f"{topic['name']} {_fmt_value(data.get('value'), unit)} ({_fmt_pct(chg)}%)",
            "body": body or f"{topic['name']} 최신 지표 기준 요약입니다.",
            "source": "FinBrief"}

def _topic_in_evidence(topic: dict, news: list[dict]) -> bool:
    """근거 뉴스가 이 토픽을 실제로 다루는지 판정: 토픽명/식별키가 근거 제목·본문에
    등장하면 관련. 'GPU' 같은 느슨한 부수 키워드가 아니라 토픽명 자체로 봐 과잉발동 방지."""
    terms = [str(topic.get("name") or "").strip(), str(topic.get("source_key") or "").strip()]
    terms = [t for t in terms if len(t) >= 2]
    if not terms:
        return True   # 판정 불가 시 통과(가드 미적용)
    text = " ".join(f"{n.get('title','')} {n.get('snippet','')}" for n in (news or [])).lower()
    return any(t.lower() in text for t in terms)


def _grounded_fallback(topic: dict, data: dict, news: list[dict]) -> tuple[str, str]:
    """관련성 가드 발동 시(근거가 토픽과 무관) 근거 없는 단정 대신 '지표 사실' 헤드라인/리드로 대체.
    지표값이 있으면 값·변화율 기반, 없으면 최상위 근거 뉴스 제목을 사용(실제 사실)."""
    name = str(topic.get("name") or "")
    unit = _display_unit(topic, data)
    val = _fmt_value(data.get("value"), unit)
    chg = data.get("change_pct")
    if val:
        arrow = "↑" if (chg or 0) > 0 else ("↓" if (chg or 0) < 0 else "")
        head = _clip_head(f"{name} {val}{unit}", 20)
        lead = _clip(f"{name} 현재 {val}{unit}, 전일 대비 {_fmt_pct(chg)}%{arrow}", 45)
        return head, lead
    top = (news or [{}])[0]
    head = _clip_head(str(top.get("title") or name), 20)
    lead = _clip(str(top.get("title") or name), 45)
    return head, lead


def _clean_source(s: str) -> str:
    """RSS 피드 제목을 언론사명으로 정리. '매일경제 : 증권'->'매일경제', '경제 | JTBC News'->'JTBC News'."""
    s = str(s).strip()
    if "|" in s:
        s = s.split("|")[-1].strip()
    if ":" in s:
        s = s.split(":")[0].strip()
    return s.replace(" 최신기사", "").strip()


def _evidence_source(news: list[dict]) -> str:
    """RAG 근거의 실제 뉴스 출처를 중복 없이 표시. 없으면 빈 문자열."""
    seen: set[str] = set()
    names: list[str] = []
    for n in news:
        name = _clean_source(n.get("source") or "")
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return "출처: " + ", ".join(names[:3]) if names else ""


def _analyze(
    topic: dict,
    data: dict,
    news: list[dict],
    *,
    run_id: str | None = None,
    trace_id: str | None = None,
) -> dict:
    metadata = observability.build_llm_metadata(
        trace_id=trace_id,
        run_id=run_id,
        topic_id=str(topic.get("topic_id")),
        node="analyze_card",
        tags=["finbrief", "card", "analysis"],
        extra={"evidence_count": len(news)},
    )
    if llm.use_llm():
        try:
            raw = llm.chat_json(
                llm.SYSTEM_ANALYZE,
                _user_prompt(topic, data, news),
                metadata=metadata,
                guardrail_profile="card",
            )
        except Exception:
            raw = _local_analysis(topic, data, news)
    else:
        raw = _local_analysis(topic, data, news)

    headline = _clip_head(raw.get("headline", topic["name"]), 20)
    lead = _clip(raw.get("lead", ""), 45)
    # 관련성 가드: 근거 뉴스에 토픽명이 전혀 없으면(무관한 근거) 토픽을 단정하는
    # 헤드라인/리드를 근거 기반 사실(지표값·실뉴스 제목)로 대체 → 근거 없는 주장 방지.
    if news and not _topic_in_evidence(topic, news):
        headline, lead = _grounded_fallback(topic, data, news)

    card = CardContent(
        category=topic["category"],
        index_no="00",
        subtitle=_clip(topic["name"], 20),
        headline=headline,
        lead=lead,
        body=_clip_body(raw.get("body", ""), 240),
        source=_evidence_source(news) or raw.get("source", "FinBrief"),
        evidence=news,
    )
    return card.model_dump()

def _fallback_prompt(content: dict) -> str:
    return (f"clean isometric illustration about {content.get('subtitle', '')}, "
            f"muted palette, no text, no letters, no numbers")


def _gen_image_prompt(
    content: dict,
    *,
    run_id: str | None = None,
    trace_id: str | None = None,
    topic_id: str | None = None,
    topic_relevant: bool = True,
) -> str:
    # 근거가 토픽과 무관하면(관련성 가드 발동) body 가 엉뚱한 소재를 담고 있으므로
    # 이미지도 body 를 배제하고 토픽만으로 앵커(_fallback_prompt = '토픽' 일러스트).
    if not topic_relevant:
        return _fallback_prompt(content)
    if llm.use_llm():
        try:
            user = f"topic: {content.get('subtitle')}\nheadline: {content.get('headline')}\nbody: {content.get('body')}"
            metadata = observability.build_llm_metadata(
                trace_id=trace_id,
                run_id=run_id,
                topic_id=topic_id,
                node="image_prompt",
                tags=["finbrief", "card", "image-prompt"],
            )
            raw = llm.chat_json(
                IMAGE_PROMPT_SYSTEM,
                user,
                metadata=metadata,
                guardrail_profile="image_prompt",
            )
            return raw.get("prompt") or _fallback_prompt(content)
        except Exception:
            return _fallback_prompt(content)
    return _fallback_prompt(content)


def _img_out() -> str:
    # 기본값을 쓰기가능 임시 디렉터리로. 설치본(site-packages)은 읽기전용이라 makedirs 실패함.
    return os.environ.get("FINBRIEF_IMG_OUT") or os.path.join(tempfile.gettempdir(), "finbrief_img")


def _generate_image(prompt: str, topic_id: str, run_date: str) -> str | None:
    asset = image_gen.generate_image(prompt, _img_out(), f"{run_date}_{topic_id}")
    return asset.path if asset else None


def _compose_card(content: dict, topic_id: str, run_date: str) -> str:
    # 기본값을 쓰기가능 임시 디렉터리로(설치본 site-packages 는 읽기전용 → PermissionError 방지).
    out = os.environ.get("FINBRIEF_OUT") or os.path.join(tempfile.gettempdir(), "finbrief_out")
    os.makedirs(out, exist_ok=True)
    path = os.path.join(out, f"{run_date}_{topic_id}.png")
    return render_card(content, path)


def _nums(s: str) -> list[str]:
    # 천단위 콤마(26,282)를 먼저 제거 — 안 하면 정규식이 26·282로 쪼개 지표 매칭 실패.
    s = re.sub(r"(?<=\d),(?=\d)", "", s or "")
    return re.findall(r"-?\d+\.?\d*", s)


def _verify(content: dict, data: dict) -> tuple[bool, list[str]]:
    issues: list[str] = []
    if not content.get("source"):
        issues.append("no-source")
    if not content.get("body"):
        issues.append("no-body")
    if len(content.get("headline", "")) > 20:   # 카드 headline max(card_schema)와 정합
        issues.append("headline-overflow")
    if len(content.get("lead", "")) > 45:
        issues.append("lead-overflow")
    # 관련성: 카테고리 유효
    if content.get("category") not in ("MARKET", "GLOBAL", "DOMESTIC", "CRYPTO", "FX"):
        issues.append("bad-category")
    # 정확성: lead/body 숫자가 지표값/변화율과 근사 일치
    text = f"{content.get('lead', '')} {content.get('body', '')}"
    found = [float(x) for x in _nums(text) if x not in ("", "-", ".")]
    targets = [t for t in (data.get("value"), data.get("change_pct")) if t is not None]

    def _close(f: float, t: float) -> bool:
        return abs(f - t) <= max(0.02 * abs(t), 0.01)

    if found and targets and not any(_close(f, t) for f in found for t in targets):
        issues.append("number-mismatch")
    return (len(issues) == 0, issues)


def build_card(state: BriefState) -> dict:
    topic = state["topic"]
    run_date = state.get("run_date", "")
    run_id = state.get("run_id")
    trace_id = state.get("trace_id")
    try:
        data = _fetch_data(topic)
        news = _retrieve_news(topic)
        content = _analyze(topic, data, news, run_id=run_id, trace_id=trace_id)
        # 텍스트 가드와 동일 신호: 근거가 토픽과 무관하면 이미지도 body 배제 후 토픽 앵커.
        topic_relevant = not news or _topic_in_evidence(topic, news)
        img_prompt = _gen_image_prompt(
            content,
            run_id=run_id,
            trace_id=trace_id,
            topic_id=str(topic.get("topic_id")),
            topic_relevant=topic_relevant,
        )
        content["image_url"] = _generate_image(img_prompt, topic["topic_id"], run_date)
        out_path = _compose_card(content, topic["topic_id"], run_date)
        ok, issues = _verify(content, data)
        card = {**content, "card_id": f"card_{topic['topic_id']}_{run_date.replace('-', '')}",
                "topic_id": topic["topic_id"], "image_path": out_path,
                "image_prompt": img_prompt, "rendered": True, "verified": ok, "cached": False}
        result = {"cards": [card]}
        if not ok:
            result["errors"] = [{"code": "verify", "message": ",".join(issues), "node": "verify", "topic": topic["topic_id"]}]
        return result
    except Exception as e:
        return {"errors": [{"code": "build_card", "message": str(e), "node": "build_card", "topic": topic.get("topic_id")}]}


# ---- 집계 · 발송 ----
def aggregate_cards(state: BriefState) -> dict[str, Any]:  # [나]
    cards = state.get("cards", [])
    n_cards, n_err = len(cards), len(state.get("errors", []))
    status = "completed" if n_err == 0 else ("partial_success" if n_cards else "failed")
    generated_count = len([card for card in cards if not card.get("cached")])
    reused_count = len([card for card in cards if card.get("cached")])
    return {
        "status": status,
        "generated_count": generated_count,
        "reused_count": reused_count,
        "trace_id": state.get("trace_id") or f"local_mock_trace_{state.get('run_id', 'run')}",
    }


def _send_to(channel: str, channel_id: str | None, text: str, image_path: str | None) -> dict[str, Any]:
    """발송: discord + channel_id 면 봇 직접 발송. 그 외(채널ID 없음/비discord)는 skip."""
    if channel == "discord" and channel_id:
        return notifier.send_via_bot(channel_id=channel_id, text=text, image_path=image_path)
    return {"status": "skipped"}


def deliver(state: BriefState) -> dict[str, Any]:
    """[나] 구독 기준 fan-out 발송. 아침마다 채널별로 전체시장 리포트 1회 + 구독 토픽 카드(최대 max_topics)."""
    by_topic = {c["topic_id"]: c for c in state.get("cards", [])}
    subscriptions = state["subscriptions"] if "subscriptions" in state else fx.FIXTURE_SUBSCRIPTIONS
    want_report = state.get("deliver_report", True)
    want_cards = state.get("deliver_cards", True)
    report_url = state.get("report_url") if want_report else None
    deliveries = []

    # 1) 전체시장 리포트를 구독이 있는 채널마다 1회 발송(모든 구독자 공통 브리핑).
    if report_url:
        seen_channels: set[tuple[Any, Any]] = set()
        for sub in subscriptions:
            channel = _value(sub, "channel")
            channel_id = _value(sub, "discord_channel_id") or _value(sub, "channel_id")
            key = (channel, channel_id)
            if key in seen_channels:
                continue
            seen_channels.add(key)
            res = _send_to(channel, channel_id, "📊 오늘의 증권 (전체시장)", report_url)
            deliveries.append({
                "delivery_id": f"report:{channel_id or _value(sub, 'user_id')}",
                "user_id": _value(sub, "user_id"),
                "channel": channel,
                "topic_id": None,
                "card_id": None,
                "status": res.get("status", "failed"),
                "attempts": 1,
                "error_code": res.get("error"),
            })

    # 2) 구독 토픽별 카드 발송 (deliver_cards=False 면 스킵).
    if want_cards:
        for sub in subscriptions:
            topic_id = _value(sub, "topic_id")
            user_id = _value(sub, "user_id")
            channel = _value(sub, "channel")
            channel_id = _value(sub, "discord_channel_id") or _value(sub, "channel_id")
            card = by_topic.get(topic_id)

            base = {
                "delivery_id": f"{user_id}:{topic_id}",
                "user_id": user_id,
                "channel": channel,
                "topic_id": topic_id,
                "card_id": card.get("card_id") if card else None,
            }

            if not card:
                deliveries.append({**base, "status": "skipped", "attempts": 0, "error_code": None})
                continue

            res = _send_to(channel, channel_id, notifier.format_card_text(card),
                           card.get("image_path") or card.get("image_url"))
            deliveries.append({
                **base,
                "status": res.get("status", "failed"),
                "attempts": 1,
                "error_code": res.get("error"),
            })

    with observability.span(
        "finbrief.delivery.dispatch",
        metadata={
            "run_id": state.get("run_id"),
            "trace_id": state.get("trace_id"),
            "subscription_count": len(subscriptions),
            "deliver_report": want_report,
            "deliver_cards": want_cards,
        },
    ) as span:
        status_counts: dict[str, int] = {}
        for item in deliveries:
            status = str(item.get("status", "unknown"))
            status_counts[status] = status_counts.get(status, 0) + 1
        span.update(output={"delivery_count": len(deliveries), "status_counts": status_counts})
    return {"deliveries": deliveries}

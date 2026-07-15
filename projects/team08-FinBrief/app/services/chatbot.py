"""관리 챗봇 핸들러 — 메시지 → 의도(LLM/규칙) → SubscriptionService → 응답.
   LLM은 '의도 파악'에만. 검증·저장은 서비스."""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from app.core import llm, observability
from app.core.config import get_settings
from app.services import chatbot_observability as chatobs, chatbot_responses as replies
from app.services.card_source_explanation_service import get_user_card_source_explanations
from app.services.chatbot_persona import is_investment_advice_request
from app.services.chatbot_suggestions import resolve_topic_id, suggest_topics, starter_topics
from app.services.report_explanation_service import get_or_build_report_explanation
from app.services.report_result_service import get_report_result
from app.services.subscription_service import SubscriptionService, TopicNotAllowed, MaxTopicsExceeded

INTENT_SYSTEM = (
    "너는 금융 카드뉴스 구독 관리 봇의 의도 분류기다. 사용자 메시지를 아래 JSON으로만 답한다. "
    '{"intent": "add_topic|list_topics|delete_topic|tier_status|help|recommend_topics|explain_report|explain_card_sources|unknown", '
    '"topic": "<카탈로그 토픽명 또는 null>"}'
    " topic은 반드시 주어진 카탈로그 중 하나로 매핑하고, 없으면 null."
)

RECOMMEND_SYSTEM = (
    "너는 금융 구독 봇의 토픽 추천기다. 사용자 관심사에 맞는 토픽을 카탈로그에서 "
    '최대 5개 골라 JSON {"topics": ["정확한 카탈로그명", ...]} 로만 답한다. 카탈로그 밖 이름 금지.'
)

UNKNOWN_REPLY_SYSTEM = (
    "너는 FinBrief 기능 안내 챗봇이다. 사용자의 말이 현재 구현된 기능 intent로 정확히 분류되지 않았을 때만 답한다. "
    "반드시 실제 구현 기능 안에서만 안내하고, 투자 판단/매수/매도 조언은 하지 않는다. "
    "지원 기능: 토픽 구독(add_topic), 목록 조회(list_topics), 구독 취소(delete_topic), 티어 확인(tier_status), 추천 토픽(recommend_topics), 당일 지표 리포트 설명(explain_report), 카드뉴스 출처 설명(explain_card_sources). "
    'JSON 키: {"reply": "사용자 질문에 대한 1~3문장 자연어 답변", '
    '"suggested_intent": "add_topic|list_topics|delete_topic|tier_status|recommend_topics|explain_report|explain_card_sources|unknown"}'
)

_TYPE_LABEL = {"indicator": "지표", "asset": "자산", "sector": "섹터", "keyword": "키워드"}
_TYPE_ORDER = ["indicator", "asset", "sector", "keyword"]


def _chat_json(system: str, message: str, *, metadata: dict[str, Any] | None = None) -> dict:
    """Call llm.chat_json with metadata while keeping older test doubles compatible."""

    try:
        return llm.chat_json(system, message, metadata=metadata)
    except TypeError:
        return llm.chat_json(system, message)


def _category_summary(catalog: list, per: int = 3) -> str:
    """카테고리(type)별 대표 per개씩 + 총 개수. 전량 나열(117개) 대신 요약."""
    from collections import defaultdict

    buckets: dict = defaultdict(list)
    for t in catalog:
        buckets[str(getattr(t, "type", "기타"))].append(t.name)
    keys = [k for k in _TYPE_ORDER if k in buckets] + [k for k in buckets if k not in _TYPE_ORDER]
    parts = [f"{_TYPE_LABEL.get(k, k)}: {', '.join(buckets[k][:per])}" for k in keys]
    return " / ".join(parts) + f" … (총 {len(catalog)}개)"


def _table_cell(value: object) -> str:
    return str(value).replace("|", "/").replace("\n", " ").strip()


def _type_label(topic_type: object) -> str:
    return _TYPE_LABEL.get(str(topic_type), str(topic_type or "-"))


def _subscription_table(current: list, catalog: list) -> str:
    topics_by_id = {t.topic_id: t for t in catalog}
    rows = ["| 번호 | 현재 구독 토픽 | 유형 |", "| ---: | --- | --- |"]
    if not current:
        rows.append("| - | 없음 | - |")
        return "\n".join(rows)

    for index, subscription in enumerate(current, start=1):
        topic = topics_by_id.get(subscription.topic_id)
        name = topic.name if topic else subscription.topic_id
        topic_type = topic.type if topic else "-"
        rows.append(f"| {index} | {_table_cell(name)} | {_table_cell(_type_label(topic_type))} |")
    return "\n".join(rows)


def _catalog_table(catalog: list) -> str:
    from collections import defaultdict

    buckets: dict = defaultdict(list)
    for topic in catalog:
        buckets[str(getattr(topic, "type", "기타"))].append(topic.name)
    keys = [key for key in _TYPE_ORDER if key in buckets] + [
        key for key in buckets if key not in _TYPE_ORDER
    ]

    rows = ["| 유형 | 구독 가능 토픽 |", "| --- | --- |"]
    for key in keys:
        names = ", ".join(_table_cell(name) for name in buckets[key])
        rows.append(f"| {_table_cell(_type_label(key))} | {names} |")
    return "\n\n".join(rows)


def _format_list_topics_reply(current: list, catalog: list, tier: dict) -> str:
    return (
        f"\n📋 **현재 구독** ({tier['used']}/{tier['max_topics']})\n"
        f"{_subscription_table(current, catalog)}\n"
        f"\n🗂️ **전체 구독 가능 토픽** (총 {len(catalog)}개)\n"
        f"{_catalog_table(catalog)}"
    )


def recommend_topics(
    message: str,
    catalog: list,
    k: int = 5,
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
) -> list[str]:
    """자연어 관심사 → 카탈로그 토픽 추천(정확명). LLM 결과는 카탈로그로 검증, 키 없으면 대표 토픽."""
    names = [t.name for t in catalog]
    if not llm.use_llm():
        return names[:k]                                      # 폴백: 대표 토픽 상위 N
    try:
        metadata = chatobs.build_chatbot_llm_metadata(
            trace_id=trace_id,
            turn_id=turn_id,
            node="chatbot.topic_recommend",
            message=message,
            extra={"catalog_count": len(catalog), "limit": k},
        )
        raw = _chat_json(RECOMMEND_SYSTEM + "\n카탈로그: " + ", ".join(names), message, metadata=metadata)
        return [n for n in raw.get("topics", []) if n in names][:k]   # ★ 카탈로그 검증
    except Exception:
        return names[:k]


def recommend_from_subs(
    cur: list,
    catalog: list,
    k: int = 3,
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
) -> list[str]:
    """현재 구독을 컨텍스트로 보완/유사 토픽 추천(카탈로그 검증). 구독 없으면 대표 토픽."""
    names = [t.name for t in catalog]
    names_by_id = {t.topic_id: t.name for t in catalog}
    cur_names = [names_by_id.get(s.topic_id, s.topic_id) for s in cur]
    rest = [n for n in names if n not in cur_names]
    if not llm.use_llm():
        return rest[:k]
    try:
        ctx = ("현재 구독: " + (", ".join(cur_names) or "없음")
               + "\n이 사용자에게 보완/유사한 토픽을 추천해줘.")
        metadata = chatobs.build_chatbot_llm_metadata(
            trace_id=trace_id,
            turn_id=turn_id,
            node="chatbot.subscription_recommend",
            message=ctx,
            extra={"catalog_count": len(catalog), "subscription_count": len(cur_names), "limit": k},
        )
        raw = _chat_json(RECOMMEND_SYSTEM + "\n카탈로그: " + ", ".join(names), ctx, metadata=metadata)
        picks = [n for n in raw.get("topics", []) if n in names and n not in cur_names]
        return picks[:k]
    except Exception:
        return rest[:k]


def _llm_unknown_reply(
    message: str,
    catalog: list,
    suggestions: list,
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
) -> dict[str, str] | None:
    if not llm.use_llm():
        return None
    try:
        feature_context = {
            "available_features": [
                "토픽 구독",
                "목록 조회",
                "구독 취소",
                "티어 확인",
                "추천 토픽",
                "리포트 설명",
                "카드뉴스 출처 설명",
            ],
            "candidate_topics": [item.name for item in suggestions],
            "catalog_examples": [topic.name for topic in catalog[:12]],
        }
        metadata = chatobs.build_chatbot_llm_metadata(
            trace_id=trace_id,
            turn_id=turn_id,
            node="chatbot.unknown_reply",
            message=message,
            extra={
                "catalog_count": len(catalog),
                "suggestion_count": len(suggestions),
            },
        )
        raw = _chat_json(
            UNKNOWN_REPLY_SYSTEM,
            json.dumps(
                {
                    "user_message": message,
                    "feature_context": feature_context,
                    "reply_policy": "질문 의도를 짧게 받아주고, 바로 사용할 수 있는 FinBrief 기능 문장으로 유도한다.",
                },
                ensure_ascii=False,
            ),
            metadata=metadata,
        )
        reply = str(raw.get("reply") or "").strip()
        if not reply:
            return None
        suggested_intent = str(raw.get("suggested_intent") or "unknown").strip()
        return {"reply": reply, "suggested_intent": suggested_intent}
    except Exception:
        return None


def welcome_text(service: "SubscriptionService") -> str:
    """봇 초대/도움말 온보딩 문구. 추천만 LLM, 본문은 비용·지연 안전하게 고정 텍스트."""
    cats = _category_summary(service.catalog())
    return ("👋 **브리핑 메이트 FinBrief**가 도착했어요!\n관심 금융 지표를 고르면 매일 아침 7시에 카드뉴스로 챙겨드릴게요 🚀\n\n"
            "• 구독:  `@finbrief 나스닥 구독해줘`  또는  `/finbrief 나스닥 추가`  (저를 멘션해도 좋아요!)\n\n"
            "• 조회:  `토픽 목록`   • 취소:  `나스닥 빼줘`   • 등급:  `내 등급`\n\n"
            f"• 구독 가능(예시): {cats}\n\n")


def _message_tokens(message: str) -> set[str]:
    return {token for token in re.split(r"[\s,./|:;!?()\[\]{}\"']+", message) if token}


def _topic_matches(message: str, lowered_message: str, topic_id: str, topic_name: str) -> bool:
    if topic_id and topic_id in lowered_message:
        return True

    name = str(topic_name).strip()
    if not name:
        return False
    if len(name) == 1:
        return name in _message_tokens(message)
    return name in message


def _should_clarify_selected_topic(
    message: str,
    names: dict,
    topic_id: str | None,
    suggestions: list,
    catalog: list | None = None,
) -> bool:
    if not topic_id or len(suggestions) <= 1:
        return False
    if catalog is not None and resolve_topic_id(message, catalog) == topic_id:
        return False
    topic_name = names.get(topic_id)
    if not topic_name:
        return False
    if _topic_matches(message, message.lower(), topic_id, topic_name):
        return False
    return True


def _rule_intent(message: str, catalog: list) -> tuple[str, str | None]:
    m = message.lower()
    compact = re.sub(r"\s+", "", message)
    names = {t.topic_id: t.name for t in catalog}
    topic = resolve_topic_id(message, catalog) or next(
        (tid for tid, nm in names.items() if _topic_matches(message, m, tid, nm)),
        None,
    )

    if (
        any(k in message for k in ("도움말", "사용법", "명령어", "가이드", "기능", "뭐 할 수", "뭘 할 수"))
        or "help" in m
        or ("처음" in message and any(k in message for k in ("어떻게", "사용", "시작", "써")))
    ):
        return "help", None

    if (
        any(k in message for k in ("출처", "근거", "참고", "기사", "어디서", "왜 이렇게"))
        and not any(k in message for k in ("삭제", "제거", "취소", "해지"))
    ):
        return "explain_card_sources", topic

    if (
        any(k in message for k in ("티어", "등급", "요금", "개수", "한도", "제한", "몇 개", "몇개", "남은"))
        or "limit" in m
    ):
        return "tier_status", None

    if (
        any(k in message for k in ("목록", "내 토픽", "내토픽", "조회", "리스트", "현황", "뭐 보고", "보고 있", "구독 중", "구독중"))
        or "list" in m
    ):
        return "list_topics", None

    if (
        any(k in message for k in ("삭제", "제거", "취소", "해지", "빼", "지워", "안 볼", "안볼", "그만", "꺼줘", "끄기", "해제"))
        or any(k in m for k in ("remove", "delete", "off"))
    ):
        return "delete_topic", topic

    if (
        any(k in message for k in ("추천", "뭐 받아", "뭐받아", "인기", "처음", "뭐 보면", "뭐보면", "뭘 보면", "골라줘"))
        or "recommend" in m
    ):
        return "recommend_topics", None

    if (
        any(k in message for k in ("리포트", "시장 설명", "지표 설명", "변동 큰", "집중해서", "시장 요약", "요약해", "중요", "핵심", "해설", "브리핑 설명"))
        or "report" in m
        or all(k in message for k in ("오늘", "뭐", "봐야"))
        or ("오늘" in message and any(k in message for k in ("시장", "요약", "중요", "핵심", "변동")))
    ):
        return "explain_report", None

    if (
        any(k in message for k in ("추가", "구독", "등록", "알림 켜", "켜줘", "받아볼", "받고 싶", "챙겨줘", "팔로우", "추적", "관심"))
        or any(k in m for k in ("add", "follow", "subscribe", "on"))
        or any(k in compact for k in ("알림켜", "받아볼래", "챙겨줘"))
    ):
        return "add_topic", topic
    return "unknown", topic


def parse_intent(
    message: str,
    catalog: list,
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
) -> tuple[str, str | None]:
    names = {t.topic_id: t.name for t in catalog}
    if llm.use_llm():
        try:
            sys = INTENT_SYSTEM + "\n카탈로그: " + json.dumps(names, ensure_ascii=False)
            metadata = chatobs.build_chatbot_llm_metadata(
                trace_id=trace_id,
                turn_id=turn_id,
                node="chatbot.intent_parse",
                message=message,
                extra={"catalog_count": len(catalog)},
            )
            raw = _chat_json(sys, message, metadata=metadata)
            intent = raw.get("intent", "unknown")
            topic = raw.get("topic")
            if topic and topic not in names:
                topic = resolve_topic_id(str(topic), catalog) or next((tid for tid, nm in names.items() if nm == topic), None)
            return intent, topic
        except Exception:
            pass
    return _rule_intent(message, catalog)


def _resp(intent, status, reply, topic=None, *, trace_metadata: dict[str, Any] | None = None):
    response = {"intent": intent, "status": status, "reply": reply, "topic": topic}
    if trace_metadata:
        response["_trace_metadata"] = trace_metadata
    return response


def _tool_span_name(intent: str) -> str:
    return {
        "add_topic": "chatbot.subscription.add",
        "delete_topic": "chatbot.subscription.delete",
        "list_topics": "chatbot.subscription.list",
        "tier_status": "chatbot.subscription.tier",
        "recommend_topics": "chatbot.topic.recommend",
        "clarify_topic": "chatbot.topic.clarify",
        "explain_report": "chatbot.report.explain",
        "explain_card_sources": "chatbot.card_sources.explain",
        "help": "chatbot.help",
    }.get(intent, "chatbot.unknown")


def _record_chatbot_result(
    response: dict,
    *,
    trace_id: str,
    turn_id: str,
    message: str,
    settings,
) -> None:
    reply = str(response.get("reply") or "")
    metadata = {
        "trace_id": trace_id,
        "turn_id": turn_id,
        "intent": response.get("intent"),
        "status": response.get("status"),
        "topic_id": response.get("topic"),
        "reply_length": len(reply),
        "message_hash": chatobs.hash_identifier(message, settings=settings, prefix="msg"),
    }
    trace_metadata = response.get("_trace_metadata")
    if isinstance(trace_metadata, dict):
        metadata.update(trace_metadata)
    with observability.span(_tool_span_name(str(response.get("intent"))), settings=settings, metadata=metadata) as span:
        span.update(output=observability.sanitize_metadata(metadata))
    with observability.span("chatbot.reply.format", settings=settings, metadata=metadata) as span:
        span.update(
            output={
                "intent": response.get("intent"),
                "status": response.get("status"),
                "reply_length": len(reply),
                "captured_reply": chatobs.capture_text(reply, settings),
            }
        )

    is_advice_blocked = is_investment_advice_request(message) and response.get("status") == "blocked"
    score_metadata = {k: v for k, v in metadata.items() if k not in {"trace_id"}}
    chatobs.score_chatbot_turn(
        "chatbot.intent_resolved",
        score=1.0 if response.get("intent") != "unknown" or is_advice_blocked else 0.0,
        passed=response.get("intent") != "unknown" or is_advice_blocked,
        trace_id=trace_id,
        turn_id=turn_id,
        metadata=score_metadata,
        settings=settings,
    )
    chatobs.score_chatbot_turn(
        "chatbot.tool_success",
        score=1.0 if response.get("status") == "completed" else 0.0,
        passed=response.get("status") == "completed",
        trace_id=trace_id,
        turn_id=turn_id,
        metadata=score_metadata,
        settings=settings,
    )
    chatobs.score_chatbot_turn(
        "chatbot.reply_format",
        score=1.0 if bool(reply.strip()) else 0.0,
        passed=bool(reply.strip()),
        trace_id=trace_id,
        turn_id=turn_id,
        metadata=score_metadata,
        settings=settings,
    )
    if is_advice_blocked:
        chatobs.score_chatbot_turn(
            "chatbot.safety.blocked_advice",
            score=1.0,
            passed=True,
            trace_id=trace_id,
            turn_id=turn_id,
            metadata=score_metadata,
            settings=settings,
        )


def _handle_core(
    service: SubscriptionService,
    channel: str,
    ext_user_id: str,
    message: str,
    channel_id: str | None = None,
    *,
    trace_id: str | None = None,
    turn_id: str | None = None,
) -> dict:
    catalog = service.catalog()
    names = {t.topic_id: t.name for t in catalog}
    with observability.span(
        "chatbot.intent.parse",
        metadata={"trace_id": trace_id, "turn_id": turn_id, "channel": channel, "catalog_count": len(catalog)},
        input=chatobs.capture_text(message),
    ) as span:
        intent, topic = parse_intent(message, catalog, trace_id=trace_id, turn_id=turn_id)
        span.update(output={"intent": intent, "topic_id": topic, "parser": "llm" if llm.use_llm() else "rule"})
    suggestions = suggest_topics(message, catalog, limit=5)
    cats = _category_summary(catalog)
    with observability.span(
        "chatbot.topic.match",
        metadata={"trace_id": trace_id, "turn_id": turn_id, "channel": channel},
    ) as span:
        span.update(
            output={
                "topic_id": topic,
                "suggestion_count": len(suggestions),
                "suggested_topic_ids": [item.topic_id for item in suggestions],
            }
        )

    if is_investment_advice_request(message):
        return _resp("unknown", "blocked", replies.format_investment_advice_reply(), topic)

    if intent == "help":
        return _resp(intent, "completed", replies.format_help_reply())
    if intent == "recommend_topics":
        return _resp(intent, "completed", replies.format_recommend_topics(starter_topics(catalog, limit=5)))
    if intent == "explain_report":
        result = get_report_result(service.repos)
        if result is None:
            return _resp(intent, "blocked", replies.format_report_not_generated_reply())
        try:
            payload = get_or_build_report_explanation(service.repos, result=result, max_focus=3)
            return _resp(
                intent,
                "completed",
                str(payload["reply"]),
                trace_metadata={
                    "linked_run_id": result.run_id,
                    "linked_trace_id": result.trace_id,
                    "report_explanation_cached": payload.get("cached"),
                },
            )
        except Exception:
            return _resp(intent, "blocked", replies.format_report_not_generated_reply())
    if intent == "explain_card_sources":
        try:
            payload = get_user_card_source_explanations(
                service.repos,
                user_id=ext_user_id,
                run_date=date.today(),
                topic_id=topic,
            )
            if not payload.get("cards"):
                return _resp(intent, "blocked", replies.format_card_sources_not_generated_reply(), topic)
            cards = list(payload.get("cards") or [])
            return _resp(
                intent,
                "completed",
                replies.format_card_sources_reply(payload),
                topic,
                trace_metadata={
                    "linked_card_ids": [item.get("card_id") for item in cards],
                    "linked_topic_ids": [item.get("topic_id") for item in cards],
                    "card_source_explanation_cached": all(bool(item.get("cached")) for item in cards),
                    "card_source_count": sum(len(item.get("sources") or []) for item in cards),
                },
            )
        except Exception:
            return _resp(intent, "blocked", replies.format_card_sources_not_generated_reply(), topic)

    if intent == "list_topics":
        cur = service.list(channel, ext_user_id)
        tier = service.tier(channel, ext_user_id)
        return _resp(intent, "completed", _format_list_topics_reply(cur, catalog, tier))
    if intent == "tier_status":
        t = service.tier(channel, ext_user_id)
        return _resp(intent, "completed", replies.format_tier_status(t["tier"], t["used"], t["max_topics"]))
    if intent == "add_topic":
        if _should_clarify_selected_topic(message, names, topic, suggestions, catalog):
            return _resp("clarify_topic", "blocked", replies.format_clarify_topic_reply(suggestions))
        if not topic:
            if suggestions:
                if len(suggestions) == 1:
                    topic = suggestions[0].topic_id
                else:
                    return _resp("clarify_topic", "blocked", replies.format_clarify_topic_reply(suggestions))
        if not topic:
            if suggestions:
                return _resp("clarify_topic", "blocked", replies.format_clarify_topic_reply(suggestions))
            reco = recommend_topics(message, catalog, trace_id=trace_id, turn_id=turn_id)
            hint = f" 혹시 이런 토픽 어때요? {', '.join(reco)} ✨" if reco else f" 가능 예시: {cats}"
            return _resp(intent, "blocked", f"🤔 어떤 토픽을 구독할까요?{hint}")
        try:
            cur = service.add(channel, ext_user_id, topic, channel_id)
            tier = service.tier(channel, ext_user_id)
            current_topics = [names.get(item.topic_id, item.topic_id) for item in cur]
            return _resp(
                intent,
                "completed",
                replies.format_add_success(
                    names.get(topic, topic),
                    len(cur),
                    tier["max_topics"],
                    current_topics,
                ),
                topic,
            )
        except TopicNotAllowed:
            reply = replies.format_topic_not_allowed(topic, suggestions)
            if not suggestions:
                reply += f"\n구독 가능 예시: {cats}"
            return _resp(intent, "blocked", reply)
        except MaxTopicsExceeded as e:
            return _resp(intent, "blocked", replies.format_topic_limit(int(e.args[0])))
    if intent == "delete_topic":
        # 삭제는 '구독 중인 토픽' 범위로 좁혀 매칭한다. 전체 카탈로그로 보면 "환율" 같은
        # 부분어가 여러 후보(EUR/USD·USD/KRW…)와 모호해지지만, 구독한 게 하나면 바로 제거.
        cur = service.list(channel, ext_user_id)
        sub_ids = {s.topic_id for s in cur}
        if topic not in sub_ids:
            sub_topics = [t for t in catalog if t.topic_id in sub_ids]
            sub_sugg = suggest_topics(message, sub_topics, limit=5)
            if len(sub_sugg) == 1:
                topic = sub_sugg[0].topic_id
            elif len(sub_sugg) > 1:
                return _resp("clarify_topic", "blocked", replies.format_clarify_topic_reply(sub_sugg))
        if topic and topic in sub_ids:
            service.remove(channel, ext_user_id, topic)
            return _resp(intent, "completed", replies.format_delete_success(names.get(topic, topic)), topic)
        if not topic:
            return _resp(intent, "blocked", replies.format_delete_needs_topic())
        subscribed = ", ".join(names.get(t, t) for t in sub_ids) or "없음"
        return _resp(intent, "blocked",
                     f"앗, '{names.get(topic, topic)}'는 현재 구독 목록에 없어요!\n현재 구독: {subscribed}")

    reco = recommend_topics(message, catalog, trace_id=trace_id, turn_id=turn_id)
    llm_reply = _llm_unknown_reply(
        message,
        catalog,
        suggestions,
        trace_id=trace_id,
        turn_id=turn_id,
    )
    reply = f"{replies.format_unknown_reply(llm_reply.get('reply') if llm_reply else None)}\n🗂️ 구독 가능 예시: {cats}"
    if reco:
        reply += f"\n💡 관심사에 맞춰 추천: {', '.join(reco)}"
    return _resp(
        "unknown",
        "blocked",
        reply,
        trace_metadata={
            "unknown_llm_answered": bool(llm_reply),
            "unknown_suggested_intent": llm_reply.get("suggested_intent") if llm_reply else None,
        },
    )


def handle(service: SubscriptionService, channel: str, ext_user_id: str, message: str,
           channel_id: str | None = None) -> dict:
    settings = get_settings()
    with chatobs.chatbot_turn_trace(
        channel=channel,
        ext_user_id=ext_user_id,
        message=message,
        channel_id=channel_id,
        settings=settings,
    ) as (trace_id, turn_id, observation):
        response = _handle_core(
            service,
            channel,
            ext_user_id,
            message,
            channel_id,
            trace_id=trace_id,
            turn_id=turn_id,
        )
        _record_chatbot_result(response, trace_id=trace_id, turn_id=turn_id, message=message, settings=settings)
        observation.update(
            output={
                "intent": response.get("intent"),
                "status": response.get("status"),
                "topic_id": response.get("topic"),
                "reply_length": len(str(response.get("reply") or "")),
                **(response.get("_trace_metadata") or {}),
            }
        )
        return {key: value for key, value in response.items() if not key.startswith("_")}

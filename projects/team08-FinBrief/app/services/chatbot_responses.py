"""Deterministic persona replies for the FinBrief chatbot."""

from __future__ import annotations

from app.services.chatbot_persona import BOT_NAME_KO, HELP_EXAMPLES
from app.services.chatbot_suggestions import TopicSuggestion


def format_help_reply() -> str:
    examples = "\n".join(f"• {example}" for example in HELP_EXAMPLES)
    return (
        f"\n✨ 안녕하세요! 저는 {BOT_NAME_KO}, 브리핑 메이트예요.\n\n"
        "관심 금융 토픽을 착착 정리해서 아침 브리핑으로 챙겨드릴게요! 🚀\n\n"
        "할 수 있는 일: `토픽 구독`, `토픽 조회`, `구독 취소`, `리포트 설명`, `출처 확인`, `티어 확인`, \n\n"
        f"예시:\n{examples}"
    )


def format_investment_advice_reply() -> str:
    return (
        "\n⚠️ 투자 판단은 제가 대신해드릴 수 없어요!\n\n"
        "대신 관심 토픽을 구독해두면 관련 지표와 뉴스 흐름을 아침마다 산뜻하게 정리해드릴게요.\n\n"
        '예: "비트코인 구독", "나스닥 추가"'
    )


def format_add_success(
    topic_name: str,
    used: int,
    max_topics: int,
    current_topics: list[str] | None = None,
) -> str:
    current_line = ""
    if current_topics:
        current_line = f"\n현재 구독 토픽: {', '.join(current_topics)}\n\n"
    return (
        f"🎉 좋아요! {topic_name}을 아침 브리핑에 쏙 넣어둘게요.\n\n"
        f"현재 {used}/{max_topics}개 토픽을 구독 중이에요!\n\n"
        f"{current_line}"
        '다른 관심사가 생기면 "비트코인 추가"처럼 편하게 말해 주세요.'
    )


def format_add_needs_topic(suggestions: list[TopicSuggestion]) -> str:
    if suggestions:
        return format_clarify_topic_reply(suggestions)
    return (
        "\n🤔 어떤 토픽을 원하시는지 조금만 더 알려주세요!\n\n"
        '예를 들면 "비트코인 구독", "달러 환율 추가", "반도체 뉴스 받아볼래"처럼 말할 수 있어요.'
    )


def format_topic_not_allowed(topic: str, suggestions: list[TopicSuggestion]) -> str:
    if suggestions:
        return format_clarify_topic_reply(suggestions)
    return (
        f"\n앗, 제가 바로 찾은 토픽에는 {topic}이 없어요!\n\n"
        '지원 토픽을 보려면 "추천해줘" 또는 "뭐 할 수 있어?"라고 말해 주세요.'
    )


def format_topic_limit(max_topics: int) -> str:
    return (
        f"\n📌 현재 티어에서는 토픽을 최대 {max_topics}개까지 구독할 수 있어요!\n\n"
        '새 토픽을 넣고 싶다면 먼저 "비트코인 취소"처럼 하나를 빼고 다시 추가해 주세요.'
    )


def format_list_topics(topic_names: list[str]) -> str:
    if not topic_names:
        return (
            "\n아직 구독 중인 토픽이 없어요!\n\n"
            '처음이라면 "나스닥 구독" 또는 "추천해줘"라고 말해 보세요. 제가 바로 도와드릴게요 🚀'
        )
    return (
        f"\n지금 받아보는 토픽은 {len(topic_names)}개예요!\n\n"
        f"{', '.join(topic_names)}.\n\n"
        '다른 관심사가 생기면 "반도체 추가"처럼 말해 주세요.'
    )


def format_tier_status(tier: str, used: int, max_topics: int) -> str:
    remaining = max(max_topics - used, 0)
    return (
        f"\n📊 현재 {tier} 티어예요!\n\n"
        f"{max_topics}개 중 {used}개 토픽을 사용 중이고, 아직 {remaining}개를 더 추가할 수 있어요."
    )


def format_delete_needs_topic() -> str:
    return (
        "\n어떤 토픽을 취소할까요?\n\n"
        '예: "비트코인 취소", "나스닥 빼줘"'
    )


def format_delete_success(topic_name: str) -> str:
    return (
        f"\n✅ {topic_name}은 구독 목록에서 빼두었어요!\n\n"
        "필요하면 언제든 다시 추가할 수 있어요."
    )


def format_unknown_reply(answer: str | None = None) -> str:
    fallback = (
        "\n제가 바로 도와드릴 수 있는 건 `토픽 구독`, `목록 조회`, `구독 취소`, `리포트 설명`, `출처 설명`, `티어 확인`이에요! ✨\n\n"
        '예: "나스닥 구독해줘", "내 토픽 보여줘", "비트코인 취소해줘", "리포트 설명해줘", "출처 설명해줘", "티어 확인해줘"'
    )
    if not answer:
        return fallback
    return f"\n💬 {answer.strip()}\n\n{fallback}"


def format_report_not_generated_reply() -> str:
    return (
        "\n📊 아직 설명할 지표 리포트가 생성되지 않았어요!\n\n"
        "먼저 오늘의 리포트가 생성된 뒤 다시 물어봐 주세요."
    )


def format_card_sources_not_generated_reply() -> str:
    return (
        "\n🧾 아직 설명할 카드뉴스 출처가 없어요!\n\n"
        "먼저 오늘의 카드뉴스가 생성된 뒤 다시 물어봐 주세요."
    )


def format_card_sources_reply(payload: dict) -> str:
    cards = list(payload.get("cards") or [])
    if not cards:
        return format_card_sources_not_generated_reply()

    chunks = ["\n🧾 오늘 카드뉴스 출처를 정리했어요!"]
    for card in cards:
        topic_name = card.get("topic_name") or card.get("topic_id")
        chunks.append(f"\n**{topic_name}**")
        chunks.append(str(card.get("source_summary") or "연결된 출처를 확인했어요."))
        sources = list(card.get("sources") or [])
        if sources:
            for idx, source in enumerate(sources[:3], start=1):
                chunks.append(
                    f"{idx}. {source.get('source')} - {source.get('title')}\n"
                    f"   {source.get('url')}"
                )
        else:
            chunks.append("아직 연결된 RSS/RAG 출처가 부족해요.")
    disclaimer = payload.get("disclaimer")
    if disclaimer:
        chunks.append(f"\n{disclaimer}")
    return "\n".join(chunks)


def format_recommend_topics(suggestions: list[TopicSuggestion]) -> str:
    lines = [f"{idx}. {item.name}" for idx, item in enumerate(suggestions, start=1)]
    return (
        "\n✨ 처음 시작하기 좋은 토픽을 골라봤어요!\n\n"
        + "\n".join(lines)
        + '\n마음에 드는 것이 있으면 "나스닥 구독"처럼 말해 주세요!'
    )


def format_clarify_topic_reply(suggestions: list[TopicSuggestion]) -> str:
    lines = [f"{idx}. {item.name}" for idx, item in enumerate(suggestions, start=1)]
    return (
        "\n🔎 말씀하신 내용과 가까운 후보를 찾았어요!\n\n"
        + "\n".join(lines)
        + '\n원하는 토픽 이름으로 다시 말해 주세요. 예: "미국 기준금리 구독"'
    )

"""Persona policy for the FinBrief Discord management chatbot."""

from __future__ import annotations

BOT_NAME = "FinBrief Mate"
BOT_NAME_KO = "FinBrief"

HELP_EXAMPLES = [
    "나스닥 구독해줘",
    "내 토픽 보여줘",
    "비트코인 취소해줘",
    "오늘 시장 요약해줘",
    "오늘 카드뉴스 출처 알려줘",
]

STARTER_TOPIC_IDS = [
    "topic_nasdaq",
    "topic_btc",
    "topic_usdkrw",
    "topic_us_rate",
    "topic_semi",
]

INVESTMENT_ADVICE_TERMS = [
    "사야",
    "팔아",
    "종목 추천",
    "추천 종목",
    "수익 보장",
    "확정 수익",
]


def is_investment_advice_request(message: str) -> bool:
    text = str(message).replace(" ", "")
    return any(term.replace(" ", "") in text for term in INVESTMENT_ADVICE_TERMS)

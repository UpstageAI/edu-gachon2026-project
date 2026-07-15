"""Guardrails applied around the shared LiteLLM/LangChain model path."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings


SAFE_BLOCKED_MESSAGE = (
    "요청에 보안 우회, 비밀키 추출, 카드·신용정보 같은 민감 정보가 포함되어 "
    "처리하지 않았습니다. 종목·뉴스·공시·재무 정보 질문으로 다시 입력해 주세요."
)

NO_INVESTMENT_RECOMMENDATION_MESSAGE = (
    "특정 종목의 매수·매도 여부는 추천할 수 없습니다. 대신 가격 흐름, 뉴스, 공시, "
    "재무지표 등 판단에 필요한 근거를 중립적으로 정리해 드릴 수 있습니다."
)

NO_PRICE_PREDICTION_MESSAGE = (
    "목표가·향후 주가 예측은 제공할 수 없습니다. 대신 현재 확인 가능한 시세, 뉴스, "
    "공시, 재무지표와 주요 리스크를 근거 중심으로 정리해 드릴 수 있습니다."
)

INVESTMENT_DISCLAIMER = "※ 투자 자문이 아닌 참고 정보입니다."

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(all\s+)?(previous|prior)\s+(instructions|prompts)",
        r"reveal\s+(the\s+)?(system|developer)\s+(prompt|message)",
        r"(system|developer)\s+prompt",
        r"jailbreak",
        r"bypass\s+(safety|guardrail|policy)",
        r"print\s+(your\s+)?(api|secret|env|environment)\s*(key|variables?)",
        r"(api|secret|private)\s*key",
        r"환경\s*변수",
        r"시스템\s*프롬프트",
        r"개발자\s*메시지",
        r"프롬프트\s*(무시|공개|출력)",
        r"보안\s*(우회|해제)",
        r"탈옥",
    )
)

_SENSITIVE_FINANCIAL_INPUT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # Credit/debit card number-like strings.
        r"\b(?:\d[ -]*?){13,19}\b",
        r"(?:cvc|cvv|카드\s*보안\s*코드|보안\s*코드)",
        r"\b(?:credit\s*card|debit\s*card|card\s*number)\b",
        r"(?:카드\s*번호|신용\s*카드|체크\s*카드)",
        r"(?:주민등록번호|주민\s*번호|resident\s*registration\s*number)",
        r"\b\d{6}-\d{7}\b",
        r"(?:신용\s*점수|신용\s*등급|credit\s*score)",
        r"(?:계좌\s*번호|bank\s*account)",
    )
)

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"sk-[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"up_[A-Za-z0-9_\-]{20,}"), "[REDACTED_API_KEY]"),
    (
        re.compile(
            r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----.*?-----END "
            r"(?:RSA |EC |OPENSSH |)PRIVATE KEY-----",
            re.DOTALL,
        ),
        "[REDACTED_PRIVATE_KEY]",
    ),
    (
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (re.compile(r"\b01[016789]-?\d{3,4}-?\d{4}\b"), "[REDACTED_PHONE]"),
)

_BUY_SELL_RECOMMENDATION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(매수|매도)\s*(추천|권장|하세요|하라|해야\s*합니다|하는\s*게\s*좋)",
        r"(사세요|팔세요|사는\s*게\s*좋|파는\s*게\s*좋)",
        r"(buy|sell)\s+(recommend|rating|signal|now)",
        r"(strong\s*)?(buy|sell)\s*recommendation",
        r"무조건\s*(매수|매도)",
        r"반드시\s*(매수|매도)",
        r"지금\s*(사야|팔아야)",
    )
)

_BUY_SELL_ADVICE_REQUEST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # Korean casual/first-person advice requests. Keep these narrower than
        # plain "매수/매도" so educational questions like "매수 뜻이 뭐야?" pass.
        r"(살까|사도\s*(돼|되나|될까|괜찮|좋을까)|사야\s*(돼|되나|하나|할까)|지금\s*사도|지금\s*살까)",
        r"(팔까|팔아도\s*(돼|되나|될까|괜찮|좋을까)|팔아야\s*(돼|되나|하나|할까)|지금\s*팔아|지금\s*팔까)",
        r"(매수|매입|추매|진입)\s*(할까|해도\s*(돼|되나|될까|괜찮)|해야\s*(돼|되나|하나)|타이밍|시점)",
        r"(매도|손절|익절|청산)\s*(할까|해도\s*(돼|되나|될까|괜찮)|해야\s*(해|돼|되나|되냐|하나|할까)|타이밍|시점)",
        r"(무조건|반드시).*(매수|매도|매입|추매|진입|손절|익절|청산|사|팔).*(추천|권장|해줘|하라|하세요)",
        r"(매수|매도|매입|추매|진입|손절|익절|청산)\s*(추천|권장)\s*(해줘|해|좀|부탁|해봐|줘)?",
        r"(사|팔)\s*(추천|권장)\s*(해줘|해|좀|부탁|해봐|줘)",
        r"(추천|권장).*(매수|매도|매입|추매|진입|손절|익절|청산)",
        # English equivalents for the same direct buy/sell advice request.
        r"should\s+i\s+(buy|sell)",
        r"(buy|sell)\s+(now|today|\?)",
        r"is\s+it\s+(a\s+)?(buy|sell)",
    )
)

_PRICE_PREDICTION_REQUEST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # Direct target-price requests. Educational questions like
        # "목표주가 뜻이 뭐야?" do not match these patterns.
        r"(목표\s*가|목표\s*주가)\s*(얼마|몇\s*원|알려|제시|잡아|예상|예측|산출|계산)",
        r"(적정\s*주가|적정\s*가치)\s*(얼마|몇\s*원|알려|제시|예상|예측|산출|계산)",
        r"(얼마까지|어디까지|몇\s*원까지)\s*(오를|올라|갈|내릴|떨어질)",
        # Direct future direction predictions.
        r"(내일|다음\s*주|이번\s*주|다음\s*달|이번\s*달|향후|앞으로)\s*.*(오를까|오르나|상승할까|떨어질까|내릴까|하락할까|갈까)",
        r"(주가|가격)\s*.*(예측|예상해|전망해|맞춰|맞혀)",
        r"(오를지|내릴지|떨어질지)\s*(맞춰|예측|예상)",
    )
)

_PRICE_PREDICTION_OUTPUT_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(목표\s*가|목표\s*주가|적정\s*주가)\s*(?:는|은|:)?\s*[\d,]+\s*원",
        r"(내일|다음\s*주|이번\s*주|향후|앞으로)\s*.*(오를|상승할|내릴|하락할)\s*(것|가능성)",
        r"주가\s*(예측|전망)\s*[:：]",
    )
)


@dataclass(frozen=True)
class GuardrailDecision:
    """Result of a guardrail check."""

    allowed: bool
    reason: str | None = None
    safe_message: str = SAFE_BLOCKED_MESSAGE


class GuardrailViolation(ValueError):
    """Raised when an input should not be sent to an LLM."""

    def __init__(self, decision: GuardrailDecision):
        self.decision = decision
        super().__init__(decision.reason or decision.safe_message)


def guardrails_enabled() -> bool:
    """Return whether runtime guardrails are enabled."""

    return settings.llm_guardrails_enabled


def check_user_input(text: str) -> GuardrailDecision:
    """Block unsafe or regulated requests before the model/tool graph runs."""

    if not guardrails_enabled():
        return GuardrailDecision(allowed=True)

    normalized = text.strip()
    for pattern in _PROMPT_INJECTION_PATTERNS:
        if pattern.search(normalized):
            return GuardrailDecision(
                allowed=False,
                reason=f"prompt_injection:{pattern.pattern}",
            )

    for pattern in _SENSITIVE_FINANCIAL_INPUT_PATTERNS:
        if pattern.search(normalized):
            return GuardrailDecision(
                allowed=False,
                reason=f"sensitive_financial_input:{pattern.pattern}",
            )

    for pattern in _BUY_SELL_ADVICE_REQUEST_PATTERNS:
        if pattern.search(normalized):
            return GuardrailDecision(
                allowed=False,
                reason=f"investment_recommendation_request:{pattern.pattern}",
                safe_message=NO_INVESTMENT_RECOMMENDATION_MESSAGE,
            )

    for pattern in _PRICE_PREDICTION_REQUEST_PATTERNS:
        if pattern.search(normalized):
            return GuardrailDecision(
                allowed=False,
                reason=f"price_prediction_request:{pattern.pattern}",
                safe_message=NO_PRICE_PREDICTION_MESSAGE,
            )

    return GuardrailDecision(allowed=True)


def ensure_safe_user_input(text: str) -> None:
    """Raise a GuardrailViolation when user input should be blocked."""

    decision = check_user_input(text)
    if not decision.allowed:
        raise GuardrailViolation(decision)


def mask_sensitive_text(text: str) -> str:
    """Redact obvious secrets/PII from model output."""

    if not text:
        return text
    masked = text
    for pattern, replacement in _SECRET_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked


def contains_buy_sell_recommendation(text: str) -> bool:
    """Detect direct buy/sell recommendation wording."""

    return any(pattern.search(text or "") for pattern in _BUY_SELL_RECOMMENDATION_PATTERNS)


def contains_price_prediction(text: str) -> bool:
    """Detect target-price or future price prediction wording."""

    return any(pattern.search(text or "") for pattern in _PRICE_PREDICTION_OUTPUT_PATTERNS)


def sanitize_llm_output(text: str) -> str:
    """Apply post-call guardrails to an LLM answer.

    StockPilot can explain evidence, risks, and context, but must never recommend
    whether the user should buy or sell a specific stock.
    """

    if not guardrails_enabled():
        return text

    safe = re.sub(r"</?\|[^|]+\|>", "", text.strip()).strip()
    safe = re.sub(
        r"가장\s*높은\s*상승\s*가능성을\s*보이고\s*있습니다",
        "상승 근거가 비교적 뚜렷하게 확인됩니다",
        safe,
    )
    safe = re.sub(r"(상승|하락)\s*가능성", r"\1 근거", safe)
    safe = mask_sensitive_text(safe)
    if contains_buy_sell_recommendation(safe):
        safe = NO_INVESTMENT_RECOMMENDATION_MESSAGE
    if contains_price_prediction(safe):
        safe = NO_PRICE_PREDICTION_MESSAGE

    if safe and INVESTMENT_DISCLAIMER not in safe:
        safe = f"{safe}\n\n{INVESTMENT_DISCLAIMER}"
    return safe

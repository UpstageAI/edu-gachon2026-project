"""그래프 노드 — router / rag / tool / response."""
import asyncio
from copy import deepcopy
import json
import re
from datetime import datetime, timedelta, timezone

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from app.core.guardrails import sanitize_llm_output
from app.core.llm import ainvoke_with_fallback
from app.core.market_time import tag_session
from app.repositories.price import resolve_ticker
from app.core.prompts import (
    DISCLOSURE_RISK_RESPONSE_PROMPT,
    RAG_GROUNDING,
    RAG_RESPONSE_PROMPT,
    RESPONSE_PROMPT,
    ROUTER_PROMPT,
    TOOL_GROUNDING,
)
from app.graph.state import StockPilotState
from app.repositories.glossary import extract_term_from_query, search_or_research_terms
from app.repositories.rag import search_documents
from app.tools.executor import ToolExecutor

_executor = ToolExecutor()

# 세션별 직전 분석 종목 (후속 질문 문맥 유지용)
_SESSION_TICKER: dict[str, str] = {}
_SESSION_PRICE_SNAPSHOT: dict[tuple[str, str], dict] = {}

OUT_OF_SCOPE_MESSAGE = (
    "저는 주식 리서치 전용 도우미라 주식·종목·뉴스·공시·재무·투자용어와 "
    "관련된 질문만 답변할 수 있어요. 예를 들어 “삼성전자 어때?”, "
    "“공시 리스크 알려줘”, “최근 급등한 종목 있어?”처럼 물어봐 주세요."
)

MISSING_TICKER_FOLLOWUP_MESSAGE = (
    "어떤 종목에 대한 질문인지 알려주세요. 예를 들어 “삼성전자 왜 올랐어?”, "
    "“한화오션 왜 떨어졌어?”처럼 종목명을 함께 입력하면 최근 시세·뉴스·공시를 "
    "근거로 설명해드릴게요."
)

# 용어·개념 질문 힌트 → rag로 분기
RAG_HINTS = (
    "뭐야", "뭔데", "무슨 뜻", "무슨 의미", "뭔 의미", "의미", "뜻", "뜻이", "설명", "단어", "per", "pbr",
    "유상증자", "공매도", "배당", "리스크",
    "용어", "목록", "리스트", "사업보고서", "분기보고서", "반기보고서", "정기보고서", "보고서",
    "상장", "ipo", "공모", "청약", "상폐", "관리종목", "거래정지", "보호예수", "락업",
    "매수", "매도", "순매수", "순매도", "손절", "익절", "추매", "진입",
)

DEFINITION_HINTS = (
    "뭐야", "뭔데", "무슨 뜻", "무슨 의미", "뭔 의미", "의미", "뜻", "뜻이", "설명", "용어", "단어",
)

DISCLOSURE_HINTS = (
    "공시", "dart",
)

INVESTMENT_DOMAIN_HINTS = (
    "주식", "종목", "주가", "시세", "등락", "가격",
    "상승", "하락", "급등", "급락", "강세", "약세",
    "뉴스", "공시", "사업보고서", "분기보고서", "반기보고서",
    "재무", "재무제표", "실적", "매출", "영업이익", "순이익",
    "per", "pbr", "eps", "bps", "roe", "roa",
    "배당", "공매도", "유상증자", "무상증자",
    "투자", "투자용어", "용어", "리스크", "호재", "악재", "코스피", "코스닥", "나스닥",
    "상장", "ipo", "공모", "청약", "상폐", "관리종목", "거래정지", "보호예수", "락업",
    "호가", "체결", "배당락", "권리락", "액면분할", "감자", "증자", "cb", "bw",
    "매수", "매도", "순매수", "순매도", "손절", "익절", "추매", "진입",
    "금리", "환율", "반도체", "온실가스", "esg",
)

# 급등·급락 스크리너 힌트 (특정 종목 없이 "요즘 뜨는 종목" 류)
SCREENER_HINTS = (
    "급등", "급락", "뜨는", "오르는", "상승한 종목", "하락한 종목",
    "많이 오른", "많이 내린", "핫한", "급등주", "급락주",
    "호재 있는", "호재가 있는", "호재 나온", "호재 종목",
    "좋은 뉴스", "긍정 뉴스", "긍정적인 뉴스", "뉴스 나온 종목", "좋은 소식",
)

SCREENER_TARGET_HINTS = (
    "종목", "주식", "기업", "회사", "어디", "뭐", "알려", "찾아", "보여",
)

POSITIVE_NEWS_HINTS = (
    "호재", "좋은 뉴스", "긍정 뉴스", "긍정적인 뉴스", "좋은 소식", "좋은 흐름", "수혜",
)

ROUTER_LLM_DOMAIN_HINTS = INVESTMENT_DOMAIN_HINTS + SCREENER_HINTS + POSITIVE_NEWS_HINTS

GENERIC_RECOMMENDATION_HINTS = (
    "추천", "권장",
)

TRADE_ACTION_HINTS = (
    "매수", "매도", "매입", "추매", "진입", "손절", "익절", "청산", "살까", "팔까",
)

_ROUTER_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# 후속 질문 힌트 (종목명 없이 직전 종목을 이어 묻는 경우)
FOLLOWUP_HINTS = (
    "왜", "그럼", "그래서", "이유", "더", "자세", "어떻게", "그건", "방금", "전망",
    "공시", "보고서", "원인", "배경", "무슨 일", "뭔 일",
)

FOLLOWUP_DOMAIN_HINTS = (
    "왜", "이유", "원인", "배경", "더", "자세", "전망", "어떻게", "그건", "방금",
    "떨어", "하락", "올라", "상승", "급락", "급등",
    "뉴스", "공시", "재무", "실적", "리스크", "보고서", "무슨 일", "뭔 일",
)

CAUSE_HINTS = (
    "왜", "이유", "원인", "배경", "무슨 일", "뭔 일", "무슨일", "뭔일",
)

# 종목명 사전(ticker 추출용). 실제 종목 매핑은 이후 확장.
KNOWN_STOCKS = [
    "삼성전자", "SK하이닉스", "LG에너지솔루션", "삼성바이오로직스", "현대차",
    "기아", "NAVER", "카카오", "POSCO홀딩스", "셀트리온",
]

# 자주 쓰는 별칭·다른 표기 → 정식 종목명 매핑 (공백/대소문자는 _norm 이 흡수)
STOCK_ALIASES = {
    "삼전": "삼성전자",
    "하이닉스": "SK하이닉스",
    "엘지에너지솔루션": "LG에너지솔루션",
    "LG엔솔": "LG에너지솔루션",
    "엘지엔솔": "LG에너지솔루션",
    "삼성바이오": "삼성바이오로직스",
    "네이버": "NAVER",
    "포스코": "POSCO홀딩스",
    "포스코홀딩스": "POSCO홀딩스",
    "현대자동차": "현대차",
}


def _last_user_text(state: StockPilotState) -> str:
    messages = state.get("messages") or []
    return messages[-1].content if messages else ""


# 종목명 뒤에 흔히 붙는 군더더기 (종목명만 남기려고 제거)
_TICKER_FILLERS = (
    "어때", "어떄", "어떄?", "알려줘", "분석", "분석해줘", "전망", "주가", "주식",
    "어떻게", "어떤가", "정보", "보여줘", "?", "!",
)


def _norm(x: str) -> str:
    """공백 제거 + 대문자화 → 표기 흔들림(대소문자·띄어쓰기)을 흡수한다."""
    return x.replace(" ", "").upper()


def _clean_ticker(text: str) -> str:
    """종목명으로 넘길 문자열에서 군더더기 표현을 떼어낸다."""
    cleaned = text
    for w in _TICKER_FILLERS:
        cleaned = cleaned.replace(w, "")
    cleaned = cleaned.strip()
    return cleaned or text.strip()


def _session_price_key(session_id: str, price_or_ticker: dict | str | None) -> tuple[str, str] | None:
    if not price_or_ticker:
        return None
    if isinstance(price_or_ticker, dict):
        ticker = price_or_ticker.get("ticker") or price_or_ticker.get("name")
    else:
        ticker = price_or_ticker
    ticker = str(ticker or "").strip()
    if not ticker:
        return None
    return session_id, ticker


def _remember_session_price(session_id: str, price_data: dict | None) -> None:
    key = _session_price_key(session_id, price_data)
    if key and price_data:
        _SESSION_PRICE_SNAPSHOT[key] = deepcopy(price_data)
        name = price_data.get("name")
        if name:
            _SESSION_PRICE_SNAPSHOT[(session_id, str(name))] = deepcopy(price_data)


def _get_session_price(session_id: str, ticker: str) -> dict | None:
    key = _session_price_key(session_id, ticker)
    if not key:
        return None
    cached = _SESSION_PRICE_SNAPSHOT.get(key)
    return deepcopy(cached) if cached else None


def _has_investment_domain(text: str) -> bool:
    lower = text.lower()
    return any(hint in lower for hint in INVESTMENT_DOMAIN_HINTS)


def _should_ask_llm_router(text: str) -> bool:
    """LLM 라우터 호출이 의미 있는 투자/뉴스/종목 후보 질문인지 판별한다."""

    lower = text.lower()
    return any(hint in lower for hint in ROUTER_LLM_DOMAIN_HINTS)


def _is_screener_query(text: str, *, wants_definition: bool) -> bool:
    """특정 종목 없이 '요즘 뜨는/호재 있는 종목'을 찾는 질문인지 판별한다."""

    if wants_definition:
        return False

    if any(hint in text for hint in SCREENER_HINTS):
        return True

    # "호재가 뭐야?" 같은 용어 질문은 위에서 걸렀고, 여기서는
    # "호재 있는 종목/기업 찾아줘"처럼 탐색 대상이 있는 경우만 스크리너로 보낸다.
    has_positive_news = any(hint in text for hint in POSITIVE_NEWS_HINTS)
    has_target = any(hint in text for hint in SCREENER_TARGET_HINTS)
    return has_positive_news and has_target


def _is_cause_question(text: str) -> bool:
    """등락 배경/원인을 묻는 질문인지 판별한다."""

    lower = (text or "").lower()
    return any(hint in lower for hint in CAUSE_HINTS)


def _is_generic_recommendation_query(text: str) -> bool:
    """Direct trade advice is blocked by guardrails; generic recommendation means market/stock summary."""

    lower = (text or "").lower()
    return any(hint in lower for hint in GENERIC_RECOMMENDATION_HINTS) and not any(
        hint in lower for hint in TRADE_ACTION_HINTS
    )


def _is_disclosure_risk_question(text: str) -> bool:
    """공시의 뜻이 아니라 공시에서 확인할 위험 신호를 묻는 질문인지 판별한다."""

    lower = (text or "").lower()
    return "공시" in lower and any(
        hint in lower
        for hint in (
            "리스크",
            "위험",
            "위험요인",
            "주의",
            "주의점",
            "악재",
            "문제",
            "이슈",
        )
    )


def _parse_router_json(content: str) -> dict | None:
    """Solar 라우터의 JSON 응답을 안전하게 파싱한다."""

    match = _ROUTER_JSON_RE.search(content or "")
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    intent = parsed.get("intent")
    if intent not in {"tool", "rag", "chat"}:
        return None

    tool_mode = parsed.get("tool_mode")
    if tool_mode not in {"market", "disclosure", None}:
        tool_mode = None
    answer_mode = parsed.get("answer_mode")
    if answer_mode not in {
        "market_overview",
        "cause_analysis",
        "disclosure_list",
        "disclosure_risk",
        "definition",
        None,
    }:
        answer_mode = None
    ticker = parsed.get("ticker")
    if ticker is not None:
        ticker = str(ticker).strip() or None

    return {
        "intent": intent,
        "screen": bool(parsed.get("screen")),
        "tool_mode": tool_mode,
        "ticker": ticker,
        "answer_mode": answer_mode,
    }


async def _llm_route_query(
    text: str,
    *,
    matched_stock: str | None = None,
    previous_ticker: str | None = None,
) -> dict | None:
    """Solar에게 질문 라우팅을 맡긴다. 실패하면 None으로 조용히 fallback."""

    context = (
        f"사용자 질문: {text}\n"
        f"룰 기반 종목 힌트: {matched_stock or '없음'}\n"
        f"직전 대화 종목 힌트: {previous_ticker or '없음'}\n\n"
        "위 힌트는 참고만 하되, 최종 분류는 질문 의도에 맞춰 JSON으로 반환하라."
    )

    try:
        result = await ainvoke_with_fallback(
            [
                SystemMessage(content=ROUTER_PROMPT),
                HumanMessage(content=context),
            ],
            model_id="solar",
            timeout_seconds=8,
        )
    except Exception as exc:
        logger.warning(f"LLM router failed; rule fallback used: {type(exc).__name__}: {exc}")
        return None

    route = _parse_router_json(result.message.content)
    if route:
        logger.info(
            "🔀 [Router:LLM] "
            f"intent={route['intent']}, screen={route['screen']}, "
            f"tool_mode={route['tool_mode']}, ticker={route.get('ticker')}, "
            f"answer_mode={route.get('answer_mode')}"
        )
    else:
        logger.warning("LLM router returned unparsable output; rule fallback used")
    return route


def _materialize_llm_route(
    route: dict,
    *,
    matched_stock: str | None,
    previous_ticker: str | None,
    is_followup: bool,
) -> dict | None:
    """Convert an LLM router JSON object into graph state fields."""

    intent = route.get("intent")
    screen = bool(route.get("screen"))
    tool_mode = route.get("tool_mode")
    response_mode = route.get("answer_mode")

    # 명확한 종목명이 룰 기반으로 잡혔는데 LLM이 chat으로 보내면
    # "삼성전자 어때" 같은 핵심 질문이 범위 밖 안내로 빠진다. 이 경우는
    # 단일 종목 시장 조회가 더 안전한 기본값이다.
    if intent == "chat" and matched_stock:
        return {
            "intent": "tool",
            "screen": False,
            "ticker": matched_stock,
            "tool_mode": "market",
            "response_mode": response_mode or "market_overview",
            "is_followup": False,
        }

    if intent == "chat":
        return {
            "intent": "chat",
            "screen": False,
            "ticker": None,
            "tool_mode": None,
            "response_mode": response_mode,
            "is_followup": False,
        }

    if intent == "rag":
        return {
            "intent": "rag",
            "screen": False,
            "ticker": route.get("ticker") or matched_stock,
            "tool_mode": None,
            "response_mode": response_mode,
            "is_followup": is_followup,
        }

    if intent != "tool":
        return None

    ticker = matched_stock or (previous_ticker if is_followup else None) or route.get("ticker")
    ticker = _clean_ticker(str(ticker)) if ticker else None

    # LLM 라우터가 가끔 "삼성전자 어때"처럼 명확한 종목 질문을
    # screen=true(급등 종목 스크리너)로 과잉 분류한다. 종목 힌트가 있거나
    # 직전 종목 후속 질문이면 스크리너보다 단일 종목 조회가 항상 우선이다.
    if screen and not ticker:
        return {
            "intent": "tool",
            "screen": True,
            "ticker": None,
            "tool_mode": tool_mode or "market",
            "response_mode": response_mode,
            "is_followup": False,
        }

    if screen:
        return {
            "intent": "tool",
            "screen": False,
            "ticker": ticker,
            "tool_mode": tool_mode or "market",
            "response_mode": response_mode or "market_overview",
            "is_followup": is_followup and not matched_stock,
        }

    if not ticker:
        return None

    return {
        "intent": "tool",
        "screen": False,
        "ticker": ticker,
        "tool_mode": tool_mode or "market",
        "response_mode": response_mode,
        "is_followup": is_followup and not matched_stock,
    }


async def router_node(state: StockPilotState) -> dict:
    """사용자 의도를 분류하고 대상 종목을 추출한다."""
    text = _last_user_text(state)
    lower = text.lower()
    session_id = state.get("session_id") or "default"
    # 공백/대소문자를 무시하고 매칭(별칭 포함) → "sk 하이닉스", "네이버", "삼전" 등도 인식
    norm_text = _norm(text)
    # (검사할 표기, 정식 종목명) 목록 — 긴 표기부터 검사해 부분 매칭 오인을 줄인다.
    _candidates = [(name, name) for name in KNOWN_STOCKS] + list(STOCK_ALIASES.items())
    _candidates.sort(key=lambda pair: len(pair[0]), reverse=True)
    matched_stock = next(
        (canonical for surface, canonical in _candidates if _norm(surface) in norm_text),
        None,
    )

    is_rag = any(hint in lower for hint in RAG_HINTS)
    wants_definition = any(hint in lower for hint in DEFINITION_HINTS)
    wants_disclosure = any(hint in lower for hint in DISCLOSURE_HINTS)
    wants_cause = _is_cause_question(text)
    is_domain_query = _has_investment_domain(text)
    is_followup = False
    prev = _SESSION_TICKER.get(session_id)
    if _is_generic_recommendation_query(text):
        if matched_stock:
            _SESSION_TICKER[session_id] = matched_stock
            logger.info("🔀 [Router] generic recommendation mapped to explicit stock overview")
            return {
                "intent": "tool",
                "screen": False,
                "ticker": matched_stock,
                "tool_mode": "market",
                "response_mode": "market_overview",
                "is_followup": False,
            }
        _SESSION_TICKER.pop(session_id, None)
        logger.info("🔀 [Router] generic recommendation mapped to screener overview")
        return {
            "intent": "tool",
            "screen": True,
            "ticker": None,
            "tool_mode": "market",
            "response_mode": "market_overview",
            "is_followup": False,
        }

    likely_followup = bool(
        prev
        and any(h in text for h in FOLLOWUP_HINTS)
        and any(h in text for h in FOLLOWUP_DOMAIN_HINTS)
    )
    missing_ticker_followup = bool(
        not matched_stock
        and not prev
        and not is_rag
        and not wants_definition
        and any(h in text for h in FOLLOWUP_HINTS)
        and any(h in text for h in FOLLOWUP_DOMAIN_HINTS)
    )
    if missing_ticker_followup:
        logger.info("🔀 [Router] missing ticker for follow-up question")
        return {
            "intent": "chat",
            "screen": False,
            "ticker": None,
            "tool_mode": None,
            "response_mode": "missing_ticker",
            "is_followup": False,
        }

    # 기본 안정 버전도 LLM 라우터를 우선 사용한다. 다만 Solar/JSON 실패 시에는
    # 아래의 기존 룰 기반 분기로 fallback해 서비스가 멈추지 않게 한다.
    should_use_llm_router = bool(
        matched_stock
        or likely_followup
        or is_domain_query
        or is_rag
        or wants_disclosure
        or _should_ask_llm_router(text)
    )
    if should_use_llm_router:
        logger.info("🔀 [Router] asking LLM router first")
        route = await _llm_route_query(
            text,
            matched_stock=matched_stock,
            previous_ticker=prev,
        )
        if route:
            routed = _materialize_llm_route(
                route,
                matched_stock=matched_stock,
                previous_ticker=prev,
                is_followup=likely_followup,
            )
            if routed:
                if routed.get("intent") == "tool" and routed.get("ticker"):
                    _SESSION_TICKER[session_id] = routed["ticker"]
                logger.info(
                    "🔀 [Router] LLM route selected "
                    f"intent={routed.get('intent')}, ticker={routed.get('ticker')}, "
                    f"tool_mode={routed.get('tool_mode')}, response_mode={routed.get('response_mode')}"
                )
                return routed

    if matched_stock:
        _SESSION_TICKER[session_id] = matched_stock  # 문맥 저장
        ticker = matched_stock
        if wants_disclosure and not wants_definition:
            intent = "tool"
            tool_mode = "disclosure"
            response_mode = "disclosure_risk" if _is_disclosure_risk_question(text) else "disclosure_list"
        else:
            intent = "tool" if wants_cause else ("rag" if is_rag else "tool")
            tool_mode = "market" if intent == "tool" else None
            response_mode = None
    elif is_rag and is_domain_query:
        ticker = None if wants_definition else _clean_ticker(text)
        intent = "rag"
        tool_mode = None
        response_mode = "definition"
    else:
        # 후속 질문(짧거나 왜/이유/전망 등)일 때만 세션의 직전 종목을 재사용
        is_followup = bool(
            prev
            and any(h in text for h in FOLLOWUP_HINTS)
            and any(h in text for h in FOLLOWUP_DOMAIN_HINTS)
        )
        if is_followup:
            ticker = prev
            if wants_disclosure and not wants_definition:
                intent = "tool"
                tool_mode = "disclosure"
                response_mode = "disclosure_risk" if _is_disclosure_risk_question(text) else "disclosure_list"
            else:
                intent = "tool" if wants_cause else ("rag" if is_rag else "tool")
                tool_mode = "market" if intent == "tool" else None
                response_mode = None
        else:
            # 명확한 스크리너 표현은 고신뢰 룰로 즉시 처리한다.
            # LLM 라우터는 애매한 투자/뉴스 질문에만 보조적으로 사용해 지연과 비용을 줄인다.
            if _is_screener_query(text, wants_definition=wants_definition):
                logger.info("🔀 [Router] intent=tool (rule screener)")
                return {
                    "intent": "tool",
                    "screen": True,
                    "ticker": None,
                    "is_followup": False,
                    "response_mode": "market_overview",
                }

            if _should_ask_llm_router(text):
                logger.info("🔀 [Router] asking LLM router")
                route = await _llm_route_query(
                    text,
                    matched_stock=matched_stock,
                    previous_ticker=prev,
                )
                if route:
                    if route["intent"] == "tool" and (
                        route["screen"] or _is_screener_query(text, wants_definition=wants_definition)
                    ):
                        logger.info("🔀 [Router] intent=tool (llm screener)")
                        return {"intent": "tool", "screen": True, "ticker": None, "is_followup": False}
                    if route["intent"] == "rag":
                        return {
                            "intent": "rag",
                            "screen": False,
                            "ticker": _clean_ticker(text),
                            "tool_mode": None,
                            "response_mode": route.get("answer_mode"),
                            "is_followup": False,
                        }
                    if route["intent"] == "chat" and not _is_screener_query(
                        text,
                        wants_definition=wants_definition,
                    ):
                        return {
                            "intent": "chat",
                            "screen": False,
                            "ticker": None,
                            "is_followup": False,
                        }

            # KNOWN_STOCKS 밖의 상장 종목도 인식: 이름이 코드로 해석되면 시세 분석(tool)으로 처리
            cand = _clean_ticker(text)
            if cand and not is_rag and not wants_definition:
                try:
                    code = await resolve_ticker(cand)
                except Exception:
                    code = None
                if code:
                    _SESSION_TICKER[session_id] = code
                    mode = "disclosure" if (wants_disclosure and not wants_definition) else "market"
                    response_mode = (
                        "disclosure_risk"
                        if mode == "disclosure" and _is_disclosure_risk_question(text)
                        else ("disclosure_list" if mode == "disclosure" else None)
                    )
                    logger.info(f"🔀 [Router] intent=tool (resolved listed stock: {cand})")
                    return {
                        "intent": "tool",
                        "screen": False,
                        "ticker": code,
                        "tool_mode": mode,
                        "response_mode": response_mode,
                        "is_followup": False,
                    }

            logger.info("🔀 [Router] intent=chat (out-of-scope)")
            return {"intent": "chat", "screen": False, "ticker": None, "is_followup": False}

    logger.info(f"🔀 [Router] intent={intent}, ticker={ticker}, tool_mode={tool_mode}")
    return {
        "intent": intent,
        "screen": False,
        "ticker": ticker,
        "tool_mode": tool_mode,
        "response_mode": response_mode,
        "is_followup": is_followup,
    }


async def rag_node(state: StockPilotState) -> dict:
    """용어 사전·공시 문서를 RAG로 검색한다."""
    query = _last_user_text(state)
    try:
        results = await search_documents(query, top_k=4)
        docs = [r.get("content", "") for r in results if r.get("content")]
    except Exception as exc:
        logger.warning(f"RAG 검색 실패: {type(exc).__name__}: {exc}")
        docs = []
    logger.info(f"📚 [RAG] 문서 {len(docs)}건")
    return {"retrieved_docs": docs}


async def tool_node(state: StockPilotState) -> dict:
    """도구를 실행해 종목 데이터를 수집한다."""
    # 급등·급락 스크리너 모드
    if state.get("screen"):
        result = await _executor.execute("find_positive_news_stocks", {})
        stocks = (result.get("data") or {}).get("stocks", [])
        logger.info(f"🔧 [Tool] 스크리너 완료 | 종목 {len(stocks)}개")
        # 스크리너 질문의 핵심은 "최근 호재/상승 이슈가 있는 종목 목록"이다.
        # 여기서 종목별 시세·공시 패널까지 선조회하면 pykrx/DART 지연 때문에
        # 전체 응답이 20초 이상 늘 수 있어 생략한다. 사용자가 특정 종목을
        # 다시 물으면 market/disclosure 전용 흐름에서 상세 데이터를 조회한다.
        panels: list[dict] = []
        return {
            "screener_results": stocks,
            "screener_panels": panels,
            "tool_result": {"stocks": stocks},
            "tool_name": "find_positive_news_stocks",
        }

    ticker = state.get("ticker") or ""
    if state.get("tool_mode") == "disclosure":
        disclosures: list[dict] = []
        disclosure_error = None
        if ticker:
            try:
                disc = await _executor.execute("get_disclosure", {"ticker": ticker})
                if disc.get("success"):
                    disclosures = (disc.get("data") or {}).get("disclosures", []) or []
                else:
                    disclosure_error = disc.get("error") or "공시 조회에 실패했습니다."
            except Exception as exc:
                disclosure_error = str(exc)
                logger.warning("공시 수집 실패 — 공시 없이 진행")
        logger.info(f"🔧 [Tool] 공시 전용 수집 완료 | 공시 {len(disclosures)}건")
        return {
            "ticker": ticker,
            "disclosures": disclosures,
            "disclosure_error": disclosure_error,
            "tool_result": {
                "disclosures": disclosures,
                "disclosure_error": disclosure_error,
            },
            "tool_name": "get_disclosure",
            "tool_mode": "disclosure",
        }

    session_id = state.get("session_id") or "default"
    is_followup = bool(state.get("is_followup"))
    cached_price = _get_session_price(session_id, ticker) if is_followup else None
    if cached_price:
        logger.info(f"🔧 [Tool] 세션 고정 시세 재사용: session={session_id}, ticker={ticker}")
        price = {"success": True, "data": cached_price}
    else:
        price = await _executor.execute("get_stock_price", {"ticker": ticker})
        _remember_session_price(session_id, price.get("data"))
    user_text = _last_user_text(state)
    change_pct = (price.get("data") or {}).get("change_pct")
    requested_direction = _requested_direction_from_text(user_text)
    actual_direction = _actual_direction_from_change(change_pct)
    direction_notice = None
    if (
        requested_direction in {"up", "down"}
        and actual_direction in {"up", "down"}
        and requested_direction != actual_direction
    ):
        direction = actual_direction
        name = (price.get("data") or {}).get("name") or ticker or "해당 종목"
        direction_notice = (
            f"아닙니다. 현재 {_topic_subject(name)} {_direction_word(actual_direction)} 중입니다. "
            f"아래는 최근 {_direction_word(actual_direction)}과 관련 있어 보이는 주요 이유입니다."
        )
        logger.info(
            "🔁 [Tool] 질문 방향과 실제 등락 방향 불일치: "
            f"requested={requested_direction}, actual={actual_direction}"
        )
    else:
        direction = requested_direction if requested_direction in {"up", "down"} else actual_direction
    price_data = price.get("data") or {}
    company_query = price_data.get("name") or ticker
    disclosure_query = price_data.get("ticker") or ticker
    news_task = asyncio.create_task(
        _executor.execute("get_news", {"company": company_query, "direction": direction})
    )
    disclosure_task = asyncio.create_task(
        _executor.execute("get_disclosure", {"ticker": disclosure_query})
    )
    news, disc = await asyncio.gather(news_task, disclosure_task)
    news_items = news.get("data", {}).get("news", [])
    news_items = [tag_session(item) for item in news_items]

    # 4번째 도구: 공시(DART). 자격 증명이 없거나 실패해도 분석은 계속 진행한다.
    disclosures: list[dict] = []
    disclosure_error = None
    if disc.get("success"):
        disclosures = (disc.get("data") or {}).get("disclosures", []) or []
    else:
        disclosure_error = disc.get("error") or "공시 조회에 실패했습니다."
        logger.warning(f"공시 수집 실패 — 공시 없이 진행: {disclosure_error}")

    logger.info(
        f"🔧 [Tool] 수집 완료 | 뉴스 {len(news_items)}건 | 공시 {len(disclosures)}건"
    )
    return {
        "price_data": price.get("data"),
        "news_items": news_items,
        "disclosures": disclosures,
        "disclosure_error": disclosure_error,
        "direction_notice": direction_notice,
        "is_followup": is_followup,
        "panel_update": not is_followup,
        "tool_result": {
            "price": price.get("data"),
            "news": news_items,
            "disclosures": disclosures,
            "disclosure_error": disclosure_error,
            "direction_notice": direction_notice,
            "is_followup": is_followup,
            "panel_update": not is_followup,
        },
        "tool_name": "get_stock_price,get_news,get_disclosure",
        "tool_mode": "market",
    }


def _format_change(change_pct: float | None) -> tuple[str, str]:
    """등락률 → (화살표, 방향 단어)."""
    if change_pct is None:
        return "", ""
    if change_pct > 0:
        return "▲", "상승"
    if change_pct < 0:
        return "▼", "하락"
    return "―", "보합"


def _requested_direction_from_text(text: str) -> str:
    """사용자가 질문에서 명시한 상승/하락 방향을 추출한다."""

    focus = text.rsplit("왜", 1)[-1] if "왜" in text else text
    return _last_direction_mention(focus) or _last_direction_mention(text) or "neutral"


def _last_direction_mention(text: str) -> str | None:
    """문장 안에서 마지막으로 언급된 상승/하락 방향을 반환한다."""

    direction_keywords = {
        "down": (
            "떨어", "떨어졌", "떨어지", "내려", "내려가", "내렸", "내림",
            "빠졌", "빠지", "빠져", "밀렸", "밀리", "하락", "급락", "약세",
            "악재", "나쁜 뉴스", "부정 뉴스",
        ),
        "up": (
            "올라", "올랐", "오르", "오른", "오름", "뛰었", "뛰어",
            "상승", "급등", "강세", "호재", "좋은 뉴스", "긍정 뉴스",
        ),
    }
    matches: list[tuple[int, str]] = []
    for direction, keywords in direction_keywords.items():
        for keyword in keywords:
            index = text.find(keyword)
            while index != -1:
                matches.append((index, direction))
                index = text.find(keyword, index + len(keyword))

    if not matches:
        return None
    return max(matches, key=lambda item: item[0])[1]


def _actual_direction_from_change(change_pct: float | None) -> str:
    """실제 등락률에서 상승/하락/중립 방향을 계산한다."""

    if change_pct is not None and change_pct < 0:
        return "down"
    if change_pct is not None and change_pct > 0:
        return "up"
    return "neutral"


def _direction_word(direction: str) -> str:
    if direction == "up":
        return "상승"
    if direction == "down":
        return "하락"
    return "보합"


def _is_market_overview_question(text: str) -> bool:
    """종목 현황 질문인지 판별한다.

    종목이 이미 tool 라우트로 들어온 뒤에는 overview를 기본값으로 둔다.
    사용자가 명시적으로 왜/원인/이유/배경을 물을 때만 원인 분석으로 넘긴다.
    """

    lower = (text or "").lower()
    reason_hints = ("왜", "이유", "원인", "배경", "때문", "뭐 때문에", "뭔 일", "무슨 일")
    action_hints = ("살까", "팔까", "매수", "매도", "추천")
    return not any(hint in lower for hint in reason_hints + action_hints)


def _format_date_kr(value: str | None) -> str:
    if not value:
        return "확인 불가"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.strftime("%Y.%m.%d")
    except ValueError:
        return value


def _format_datetime_kst(value: str | None) -> str:
    if not value:
        return "확인 불가"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone(timedelta(hours=9))).strftime("%Y.%m.%d %H:%M")
    except ValueError:
        return value


def _period_label(period: str | None, ohlcv_len: int) -> str:
    if ohlcv_len > 0:
        return f"최근 {ohlcv_len}거래일"
    labels = {
        "1w": "최근 1주",
        "1m": "최근 1개월",
        "3m": "최근 3개월",
        "6m": "최근 6개월",
        "1y": "최근 1년",
    }
    return labels.get(period or "", "최근 기간")


def _recent_trend_from_ohlcv(ohlcv: list[dict]) -> tuple[str, float | None]:
    closes = [
        float(row["close"])
        for row in (ohlcv or [])
        if isinstance(row.get("close"), (int, float)) and row.get("close") not in (None, 0)
    ]
    if len(closes) < 2:
        return "흐름을 판단할 만큼 차트 데이터가 충분하지 않습니다", None
    lookback = min(20, len(closes) - 1)
    base = closes[-lookback - 1]
    latest = closes[-1]
    if base == 0:
        return "흐름을 판단할 만큼 차트 데이터가 충분하지 않습니다", None
    delta = round((latest - base) / base * 100, 2)
    if delta >= 3:
        return "최근에는 올라가는 추세입니다", delta
    if delta <= -3:
        return "최근에는 내려가는 추세입니다", delta
    return "최근에는 큰 방향성 없이 오르내리는 흐름입니다", delta


def _direction_from_delta(delta: float | None) -> str:
    if delta is None:
        return "unknown"
    if delta >= 3:
        return "up"
    if delta <= -3:
        return "down"
    return "neutral"


def _overview_lead_sentence(name: str, period: str, trend_text: str, trend_pct: float | None, change_pct: float | None) -> str:
    trend_direction = _direction_from_delta(trend_pct)
    daily_direction = _actual_direction_from_change(change_pct)
    subject = _topic_subject(name)

    if trend_direction in {"up", "down"} and daily_direction in {"up", "down"}:
        trend_word = "상승" if trend_direction == "up" else "하락"
        daily_word = "상승" if daily_direction == "up" else "하락"
        if trend_direction != daily_direction:
            return (
                f"{subject} 일봉 기준으로 보면 {period} 흐름은 {trend_word} 추세지만, "
                f"기준일 하루 움직임은 전 거래일 대비 {daily_word}입니다."
            )
        return (
            f"{subject} 일봉 기준으로 보면 {period} 흐름과 기준일 하루 움직임 모두 "
            f"{daily_word} 쪽입니다."
        )

    if daily_direction in {"up", "down"}:
        daily_word = "상승" if daily_direction == "up" else "하락"
        return (
            f"{subject} 일봉 기준 {period} 차트에서는 {trend_text}. "
            f"기준일 하루 움직임은 전 거래일 대비 {daily_word}입니다."
        )

    return f"{subject} 일봉 기준, {period} 차트로 보면 {trend_text}."


def _market_overview_answer(price: dict) -> str:
    """단순 현황 질문에는 원인 분석 대신 기준이 분명한 요약을 반환한다."""

    name = price.get("name") or "해당 종목"
    change_pct = price.get("change_pct")
    current_price = price.get("current_price")
    ohlcv = price.get("ohlcv") or []
    trend_text, trend_pct = _recent_trend_from_ohlcv(ohlcv)
    period = _period_label(price.get("period"), len(ohlcv))
    as_of = _format_date_kr(price.get("as_of"))
    snapshot_at = _format_datetime_kst(price.get("snapshot_at"))

    lines = [
        _overview_lead_sentence(name, period, trend_text, trend_pct, change_pct),
        "",
        f"기준일: {as_of} · 조회시각: {snapshot_at}",
    ]
    if current_price is not None:
        lines.append(f"현재가: {int(current_price):,}원")
    if change_pct is not None:
        arrow, direction = _format_change(change_pct)
        lines.append(f"전 거래일 대비: {arrow} {abs(change_pct):.2f}% {direction}")
    if trend_pct is not None:
        lines.append(f"최근 흐름 변화폭: {trend_pct:+.2f}%")

    if change_pct is not None and change_pct > 0:
        followup = (
            "이 움직임의 배경이 궁금하시다면 “왜 올랐어?”라고 물어보시면 "
            "뉴스와 공시 근거로 더 자세히 설명해드릴게요."
        )
    elif change_pct is not None and change_pct < 0:
        followup = (
            "이 움직임의 배경이 궁금하시다면 “왜 떨어졌어?”라고 물어보시면 "
            "뉴스와 공시 근거로 더 자세히 설명해드릴게요."
        )
    else:
        followup = (
            "이 움직임의 배경이 궁금하시다면 “왜 움직임이 크지 않아?”처럼 물어보시면 "
            "뉴스와 공시 근거로 더 자세히 설명해드릴게요."
        )

    lines += [
        "",
        followup,
        "",
        "※ 투자 자문이 아닌 참고 정보입니다.",
    ]
    return "\n".join(lines)


def _topic_subject(name: str) -> str:
    """회사명에 자연스러운 주제 조사(은/는)를 붙인다."""

    if not name:
        return "해당 종목은"
    last = name[-1]
    code = ord(last)
    if 0xAC00 <= code <= 0xD7A3:
        has_jong = (code - 0xAC00) % 28 != 0
        return f"{name}{'은' if has_jong else '는'}"
    return f"{name}은"


def _tool_context(
    price: dict,
    news_items: list[dict],
    disclosures: list[dict] | None = None,
    direction_notice: str | None = None,
) -> str:
    """Solar에 넘길 근거 데이터(시세·뉴스·공시)를 텍스트로 정리한다."""
    lines: list[str] = []
    if direction_notice:
        lines.append(f"방향 보정 안내: {direction_notice}")
    name = price.get("name") or "해당 종목"
    change_pct = price.get("change_pct")
    current_price = price.get("current_price")
    if change_pct is not None:
        arrow, direction = _format_change(change_pct)
        lines.append(f"종목: {name}")
        lines.append(f"등락률: {arrow} {abs(change_pct):.2f}% {direction}")
    if current_price is not None:
        lines.append(f"현재가: {int(current_price):,}원")
    strong_news = [item for item in news_items if not item.get("filter_fallback")]
    fallback_news = [item for item in news_items if item.get("filter_fallback")]
    if strong_news:
        lines.append("관련 뉴스:")
        for item in strong_news[:5]:
            title = item.get("title", "")
            source = item.get("source_domain", "")
            session = item.get("market_session", "")
            evidence = ", ".join(item.get("direction_keywords") or [])
            meta = " · ".join(x for x in (source, session) if x)
            suffix = f" ({meta})" if meta else ""
            evidence_text = f" / 방향 근거: {evidence}" if evidence else ""
            lines.append(f"- {title}{suffix}{evidence_text}")
    elif fallback_news:
        lines.append(
            "관련 뉴스: 질문한 방향을 직접 뒷받침하는 뉴스는 충분하지 않습니다. "
            "아래 뉴스는 종목 관련 참고 뉴스이며 원인으로 단정하지 마세요."
        )
        for item in fallback_news[:3]:
            title = item.get("title", "")
            source = item.get("source_domain", "")
            session = item.get("market_session", "")
            meta = " · ".join(x for x in (source, session) if x)
            lines.append(f"- {title}" + (f" ({meta})" if meta else ""))
    else:
        lines.append("관련 뉴스: 질문한 방향을 직접 뒷받침하는 최근 뉴스를 찾지 못했습니다.")
    if disclosures:
        lines.append("관련 공시:")
        for item in disclosures[:5]:
            title = item.get("report_name") or item.get("title") or "공시"
            date = item.get("received_date") or item.get("date") or ""
            lines.append(f"- {title}" + (f" ({date})" if date else ""))
    return "\n".join(lines)


async def fetch_screener_panel(stock: dict) -> dict | None:
    """스크리너 종목 1개의 시세·뉴스·공시를 순차로 조회한다(실패 시 None).

    라우트에서 종목을 하나씩 호출해 완성되는 대로 프론트에 스트리밍한다.
    tool_node에서 한꺼번에 선조회하면 지연이 커서(팀원 최적화) 라우트에서 순차 처리한다.
    """
    name = (stock or {}).get("ticker") or ""
    if not name:
        return None
    try:
        price = await _executor.execute("get_stock_price", {"ticker": name})
    except Exception:
        logger.warning(f"스크리너 패널 시세 실패: {name}")
        return None
    price_data = price.get("data")
    if not price_data:
        return None
    try:
        news = await _executor.execute("get_news", {"company": name, "direction": "up"})
        news_items = [tag_session(item) for item in news.get("data", {}).get("news", [])]
    except Exception:
        news_items = []
    disclosures: list[dict] = []
    try:
        query = (price_data or {}).get("ticker") or name
        disc = await _executor.execute("get_disclosure", {"ticker": query})
        disclosures = (disc.get("data") or {}).get("disclosures", []) or []
    except Exception:
        disclosures = []
    return {"price": price_data, "news": news_items, "disclosures": disclosures}


def _format_screener(stocks: list[dict]) -> str:
    """스크리너 결과를 목록 형태 답변으로 만든다."""
    if not stocks:
        return (
            "지금 상승 중인 종목을 찾지 못했어요.\n\n"
            "※ 투자 자문이 아닌 참고용 정보입니다."
        )
    lines = ["### 📈 최근 상승률 상위 종목", ""]
    for s in stocks[:6]:
        name = s.get("ticker", "")
        top = s.get("top_news") or "관련 이슈"
        chg = s.get("change_pct")
        badge = f" (▲{chg:.2f}%)" if isinstance(chg, (int, float)) and chg > 0 else ""
        lines.append(f"- **{name}**{badge} — {top}")
    lines.append("")
    lines.append("※ 상승 근거 뉴스 기준이며, 투자 자문이 아닌 참고용 정보입니다.")
    return "\n".join(lines)


def _format_disclosure_answer(ticker: str | None, disclosures: list[dict]) -> str:
    """최근 공시 목록을 주가 분석 없이 그대로 보여준다."""
    name = ticker or "해당 종목"
    if not ticker:
        return (
            "어느 회사의 공시를 볼지 종목명이나 회사명을 함께 알려주세요.\n"
            "예: “삼성전자 공시 알려줘”\n\n"
            "※ 투자 자문이 아닌 참고 정보입니다."
        )
    if not disclosures:
        return (
            f"{name}의 최근 공시를 찾지 못했어요.\n"
            "DART 자격 증명이나 조회 가능한 최근 공시 여부를 확인해 주세요.\n\n"
            "※ 투자 자문이 아닌 참고 정보입니다."
        )

    lines = [f"### {name} 최근 공시", ""]
    for item in disclosures[:8]:
        title = item.get("report_name") or item.get("title") or "공시"
        date = item.get("received_date") or item.get("date") or ""
        url = item.get("source_url") or item.get("url") or ""
        corp = item.get("corp_name") or name
        meta = " · ".join(part for part in (corp, date) if part)
        line = f"- **{title}**"
        if meta:
            line += f" ({meta})"
        if url:
            line += f"  \n  {url}"
        lines.append(line)
    lines += ["", "※ 투자 자문이 아닌 참고 정보입니다."]
    return "\n".join(lines)


def _disclosure_context(ticker: str | None, disclosures: list[dict]) -> str:
    """LLM이 공시 리스크를 판단할 수 있도록 최근 공시 목록을 텍스트로 정리한다."""

    name = ticker or "해당 종목"
    if not disclosures:
        return f"{name}: 최근 조회된 공시 없음"

    lines = [f"종목: {name}", "최근 공시:"]
    for item in disclosures[:10]:
        title = item.get("report_name") or item.get("title") or "공시"
        date = item.get("received_date") or item.get("date") or ""
        corp = item.get("corp_name") or name
        url = item.get("source_url") or item.get("url") or ""
        lines.append(
            "- "
            + " · ".join(part for part in (title, corp, date, url) if part)
        )
    return "\n".join(lines)


def _format_disclosure_risk_fallback(ticker: str | None, disclosures: list[dict]) -> str:
    """LLM 실패 시에도 목록 나열 대신 리스크 관점의 최소 답변을 제공한다."""

    name = ticker or "해당 종목"
    if not disclosures:
        return (
            f"{name}의 최근 공시를 찾지 못해 공시 리스크를 판단할 근거가 부족해요.\n"
            "DART 조회 가능 여부나 종목명을 다시 확인해 주세요.\n\n"
            "※ 투자 자문이 아닌 참고 정보입니다."
        )

    risk_keywords = (
        "자기주식",
        "대량보유",
        "소송",
        "채무",
        "보증",
        "유상증자",
        "감자",
        "거래정지",
        "불성실",
        "감사의견",
        "정정",
        "해지",
        "처분",
    )
    risk_like = [
        item
        for item in disclosures
        if any(
            keyword in (item.get("report_name") or item.get("title") or "")
            for keyword in risk_keywords
        )
    ]

    lines = [f"### {name} 공시 리스크 요약", ""]
    if risk_like:
        lines.append("최근 공시 중 추가 확인이 필요한 후보는 아래 항목이에요.")
        for item in risk_like[:5]:
            title = item.get("report_name") or item.get("title") or "공시"
            date = item.get("received_date") or item.get("date") or ""
            lines.append(f"- **{title}**" + (f" ({date})" if date else ""))
        lines.append("")
        lines.append("다만 공시 제목만으로 악재라고 단정하면 안 되고, 원문에서 규모·사유·반복 여부를 확인해야 해요.")
    else:
        lines.append("제목 기준으로 즉시 큰 리스크라고 단정할 만한 공시는 뚜렷하지 않아요.")
        lines.append("반복 공시나 행정성 공시는 원문에서 지분 변동 규모와 제출 사유를 확인하는 정도가 좋습니다.")
    lines += ["", "※ 투자 자문이 아닌 참고 정보입니다."]
    return "\n".join(lines)


def _fallback_answer(
    price: dict,
    news_items: list[dict],
    docs: list[str],
    direction_notice: str | None = None,
) -> str:
    """Solar 호출 실패 시 사용하는 템플릿 응답."""
    change_pct = price.get("change_pct")
    if change_pct is not None:
        name = price.get("name") or "해당 종목"
        current_price = price.get("current_price")
        arrow, direction = _format_change(change_pct)
        lines = []
        if direction_notice:
            lines.append(direction_notice)
            lines.append("")
        lines.append(f"{name} {arrow} {abs(change_pct):.2f}% {direction}")
        if current_price is not None:
            lines.append(f"현재가 {int(current_price):,}원")
        lines.append("")
        lines.append("📌 원인 분석")
        if news_items:
            subject = "움직임" if direction == "보합" else direction
            lines.append(f"최근 {subject}은 다음 이슈와 관련 있어 보입니다:")
            for item in news_items[:5]:
                title = item.get("title", "")
                source = item.get("source_domain", "")
                session = item.get("market_session", "")
                meta = " · ".join(x for x in (source, session) if x)
                suffix = f" ({meta})" if meta else ""
                lines.append(f" • {title}{suffix}")
        else:
            lines.append("관련 뉴스를 찾지 못했어요.")
        lines.append("")
        lines.append("※ 투자 자문이 아닌 참고 정보입니다.")
        return "\n".join(lines)
    if docs:
        prefix = f"{direction_notice}\n\n" if direction_notice else ""
        return prefix + "\n".join(docs) + "\n\n※ 투자 자문이 아닌 참고 정보입니다."
    return "관련 정보를 찾지 못했어요. 질문을 조금 더 구체적으로 알려주세요."


def _norm_kv(x: str) -> str:
    return (x or "").replace(" ", "").upper()


async def _direct_glossary_answer(query: str) -> str | None:
    """사전에 등록된 용어면 LLM 없이 DB 정의를 그대로 반환한다(토큰 절약).

    표제어나 별칭이 질문에 실제로 등장할 때만 '확실한 매칭'으로 보고 직접 응답한다.
    애매하면 None → 이후 LLM(RAG) 경로로 넘어간다.
    """
    if not query.strip():
        return None
    if _is_disclosure_risk_question(query):
        return None
    try:
        matches = await search_or_research_terms(query, limit=1)
    except Exception as exc:
        logger.warning(f"사전 직접 조회 실패: {type(exc).__name__}: {exc}")
        return None
    if not matches:
        if extract_term_from_query(query):
            return (
                "투자 용어 사전과 외부 검색에서 확인 가능한 정의를 찾지 못했어요. "
                "용어를 조금 더 정확히 입력해 주세요.\n\n"
                "※ 투자 자문이 아닌 참고용 정보입니다."
            )
        return None
    top = matches[0]
    surfaces = [top.get("term", "")] + list(top.get("aliases") or [])
    nq = _norm_kv(query)
    if not any(surf and _norm_kv(surf) in nq for surf in surfaces):
        return None  # 약한 매칭은 LLM에 맡긴다

    logger.info(f"📖 [Glossary] 직접 응답(LLM 생략): {top.get('term')}")
    lines = [f"**{top.get('term')}**", "", top.get("definition", "")]
    if top.get("example"):
        lines += ["", f"예) {top['example']}"]
    lines += ["", "※ 투자 자문이 아닌 참고용 정보입니다."]
    return "\n".join(lines)


def _glossary_list_answer() -> str | None:
    """data/glossary.json의 용어 목록을 마크다운 리스트로 반환(LLM 호출 없음)."""
    import json
    from pathlib import Path
    try:
        path = Path(__file__).resolve().parents[2] / "data" / "glossary.json"
        entries = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not entries:
        return None
    lines = ["아래는 사전에 등록된 주요 투자 용어예요:", ""]
    for e in entries:
        term = (e.get("term") or "").strip()
        if not term:
            continue
        d = (e.get("definition") or "").strip()
        lines.append(f"- **{term}**: {d[:50]}" + ("…" if len(d) > 50 else ""))
    lines += ["", "각 용어가 궁금하면 \u201c(용어) 뭐야?\u201d처럼 물어보세요.", "", "※ 투자 자문이 아닌 참고용 정보입니다."]
    return "\n".join(lines)


async def response_node(state: StockPilotState) -> dict:
    """수집한 근거를 바탕으로 Solar가 등락률·원인 분석 응답을 생성한다."""
    user_text = _last_user_text(state)
    if state.get("intent") == "chat":
        logger.info("💬 [Response] 범위 밖 질문 안내")
        if state.get("response_mode") == "missing_ticker":
            return {"messages": [AIMessage(content=MISSING_TICKER_FOLLOWUP_MESSAGE)]}
        return {"messages": [AIMessage(content=OUT_OF_SCOPE_MESSAGE)]}

    # 스크리너 결과는 목록 템플릿으로 바로 응답
    screener = state.get("screener_results")
    if screener is not None:
        logger.info("💬 [Response] 스크리너 응답 생성 완료")
        return {"messages": [AIMessage(content=_format_screener(screener))]}

    if state.get("tool_mode") == "disclosure" and (
        state.get("response_mode") == "disclosure_risk"
        or _is_disclosure_risk_question(user_text)
    ):
        logger.info("💬 [Response] 공시 리스크 LLM 응답 생성")
        requested_model = state.get("model")
        used_model = requested_model or "solar"
        disclosures = state.get("disclosures") or []
        try:
            result = await ainvoke_with_fallback(
                [
                    SystemMessage(
                        content=DISCLOSURE_RISK_RESPONSE_PROMPT
                        + TOOL_GROUNDING.format(
                            tool_result=_disclosure_context(
                                state.get("ticker"),
                                disclosures,
                            )
                        )
                    ),
                    HumanMessage(content=user_text or "공시 리스크를 요약해줘"),
                ],
                model_id=requested_model,
                timeout_seconds=45,
            )
            answer = (result.message.content or "").strip()
            used_model = result.model_name or result.model_id
            if not answer:
                answer = _format_disclosure_risk_fallback(state.get("ticker"), disclosures)
        except Exception as exc:
            logger.warning(
                f"공시 리스크 LLM 응답 실패, 템플릿으로 폴백: {type(exc).__name__}: {exc}"
            )
            answer = _format_disclosure_risk_fallback(state.get("ticker"), disclosures)
            used_model = "template-disclosure-risk"
        answer = sanitize_llm_output(answer)
        return {
            "messages": [AIMessage(content=answer)],
            "used_model": used_model,
        }

    if state.get("tool_mode") == "disclosure":
        logger.info("💬 [Response] 공시 목록 응답 생성 완료")
        return {
            "messages": [
                AIMessage(
                    content=_format_disclosure_answer(
                        state.get("ticker"),
                        state.get("disclosures") or [],
                    )
                )
            ],
        }

    price = state.get("price_data") or {}
    news_items = state.get("news_items") or []
    disclosures = state.get("disclosures") or []
    docs = state.get("retrieved_docs") or []
    direction_notice = state.get("direction_notice")
    intent = state.get("intent")

    if direction_notice and price:
        logger.info("💬 [Response] 방향 보정 템플릿 응답 생성 완료")
        answer = _fallback_answer(price, news_items, docs, direction_notice)
        answer = sanitize_llm_output(answer)
        return {
            "messages": [AIMessage(content=answer)],
            "used_model": "template-direction-correction",
        }

    if intent == "tool" and price and (
        state.get("response_mode") == "market_overview"
        or _is_market_overview_question(user_text)
    ):
        logger.info("💬 [Response] 시장 현황 요약 템플릿 응답 생성 완료")
        answer = sanitize_llm_output(_market_overview_answer(price))
        return {
            "messages": [AIMessage(content=answer)],
            "used_model": "template-market-overview",
        }

    # 용어/개념 질문(rag): 사전에 있는 용어면 LLM 없이 바로 정의를 돌려준다(토큰 절약).
    if intent == "rag":
        if any(k in user_text for k in ("목록", "리스트", "용어들", "어떤 용어", "무슨 용어")):
            listed = _glossary_list_answer()
            if listed:
                logger.info("💬 [Response] 용어 목록 응답")
                return {"messages": [AIMessage(content=listed)], "used_model": "glossary-list"}
        direct = await _direct_glossary_answer(user_text)
        if direct:
            logger.info("💬 [Response] 사전 직접 응답 생성 완료")
            return {"messages": [AIMessage(content=direct)]}
        system = RAG_RESPONSE_PROMPT
        if _is_disclosure_risk_question(user_text):
            system += (
                "\n\n중요: 사용자는 '공시'라는 단어의 단순 정의가 아니라 '공시 리스크'의 의미를 물었다. "
                "공시가 무엇인지 한 줄로만 짚고, 공시에서 확인해야 할 위험 신호(소송, 증자, 채무보증, "
                "감사의견, 거래정지, 대량보유 변동, 자기주식 처분 등)를 초보자 관점으로 설명하라."
            )
        if docs:
            system += RAG_GROUNDING.format(context="\n\n".join(docs))
    else:
        system = RESPONSE_PROMPT
        if docs:
            system += RAG_GROUNDING.format(context="\n\n".join(docs))
        if price or news_items:
            system += TOOL_GROUNDING.format(
                tool_result=_tool_context(price, news_items, disclosures, direction_notice)
            )
            system += (
                "\n\n중요: 상승/하락 방향은 반드시 위 '등락률'의 부호를 그대로 따르라. "
                "뉴스 내용이 반대로 보여도 실제 등락률 부호(+ 상승 / - 하락)를 기준으로 설명하라."
                "\n중요: '관련 뉴스'에 방향 근거가 부족하다고 적혀 있으면 뉴스를 억지로 원인으로 해석하지 말고, "
                "공시나 확인 가능한 사실 중심으로 '직접 원인은 제한적'이라고 말하라."
            )
            if direction_notice:
                system += (
                    "\n질문에 포함된 상승/하락 방향과 실제 등락률이 충돌했다. "
                    "답변 첫 문장에 반드시 실제 등락 방향을 정정하는 문장을 자연스럽게 먼저 말한 뒤, "
                    "실제 등락률 방향에 맞는 원인을 설명하라."
                )

    requested_model = state.get("model")
    used_model = requested_model or "solar"
    try:
        result = await ainvoke_with_fallback(
            [
                SystemMessage(content=system),
                HumanMessage(content=user_text or "이 종목에 대해 설명해줘"),
            ],
            model_id=requested_model,
            timeout_seconds=45,
        )
        response = result.message
        used_model = result.model_name or result.model_id
        if result.fallback_used:
            logger.info(
                f"LLM fallback applied: requested={requested_model}, "
                f"used={result.model_id}, attempts={result.attempted_models}"
            )
        answer = (response.content or "").strip()
        if not answer:
            answer = _fallback_answer(price, news_items, docs, direction_notice)
    except Exception as exc:
        logger.warning(f"LLM 응답 실패, 템플릿으로 폴백: {type(exc).__name__}: {exc}")
        answer = _fallback_answer(price, news_items, docs, direction_notice)
        used_model = "template-fallback"

    if direction_notice:
        answer = _force_direction_notice_first(answer, direction_notice)

    answer = sanitize_llm_output(answer)

    logger.info(f"💬 [Response] 응답 생성 완료 (model={used_model})")
    return {"messages": [AIMessage(content=answer)], "used_model": used_model}


def _force_direction_notice_first(answer: str, direction_notice: str) -> str:
    """방향 보정이 필요한 답변은 보정 안내가 반드시 첫 문장이 되도록 정리한다."""

    prefix = direction_notice
    cleaned = (answer or "").strip()
    if not cleaned:
        return prefix

    notice_index = cleaned.find(direction_notice)
    if notice_index >= 0:
        cleaned = cleaned[notice_index + len(direction_notice) :].lstrip()
        cleaned = re.sub(r"^[\s:：\\-–—|]+", "", cleaned).lstrip()
        if cleaned:
            return f"{prefix}\n\n{cleaned}"
        return prefix

    return f"{prefix}\n\n{cleaned}"

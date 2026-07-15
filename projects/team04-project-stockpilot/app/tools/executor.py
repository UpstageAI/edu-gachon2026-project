"""LangGraph가 호출하는 실제 데이터 도구 실행 계층."""

from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from datetime import datetime
from time import monotonic
from typing import Any, Literal

from loguru import logger

from app.repositories import disclosure, glossary, news, price, watchlist
from app.schemas.tool_results import TOOL_RESULT_SCHEMAS, ToolErrorResult
from app.schemas.tools import TOOL_ARG_SCHEMAS

DEFAULT_UNIVERSE = [
    "삼성전자",
    "SK하이닉스",
    "LG에너지솔루션",
    "삼성바이오로직스",
    "현대차",
    "기아",
    "NAVER",
    "카카오",
    "POSCO홀딩스",
    "셀트리온",
    "LG화학",
    "삼성SDI",
    "현대모비스",
    "KB금융",
    "신한지주",
    "삼성물산",
    "LG전자",
    "SK이노베이션",
    "한화오션",
    "HD현대중공업",
    "삼성생명",
    "카카오뱅크",
]

TOOL_TIMEOUT_SECONDS = {
    "get_stock_price": 20,
    "get_news": 25,
    # 매핑되지 않은 종목은 최초 1회 OpenDART corpCode.xml 전체 목록을 받아야 한다.
    # GCE/IAP 배포 환경에서는 15초를 넘길 수 있어, 공시 도구만 넉넉하게 둔다.
    "get_disclosure": 60,
    "find_positive_news_stocks": 35,
    "add_watchlist": 15,
    "lookup_glossary_term": 10,
}

_SCREENER_CACHE_TTL_SECONDS = 300
_SCREENER_CACHE_LOCK = threading.Lock()
_SCREENER_CACHE: dict[
    tuple[tuple[str, ...], int, int],
    tuple[float, dict[str, Any]],
] = {}


# 도구별 최대 시도 횟수(타임아웃·일시적 네트워크 오류 시 재시도). 무거운 스크리너는 재시도 안 함.
TOOL_MAX_ATTEMPTS = {
    "get_stock_price": 2,
    "get_news": 2,
    "get_disclosure": 2,
    "find_positive_news_stocks": 1,
}
RETRY_BACKOFF_SECONDS = 0.6
RETRYABLE_ERRORS = (asyncio.TimeoutError, ConnectionError, OSError, TimeoutError)


class ToolExecutor:
    """시세·뉴스·공시·관심 종목 도구를 단일 인터페이스로 실행합니다."""

    def _build_coroutine(
        self, tool_name: str, validated_args: dict[str, Any], session_id: str
    ):
        """도구 이름에 맞는 코루틴을 새로 만든다(재시도마다 새 코루틴 필요)."""
        match tool_name:
            case "get_stock_price":
                return self.get_stock_price(**validated_args)
            case "get_news":
                return self.get_news(**validated_args)
            case "get_disclosure":
                return self.get_disclosure(**validated_args)
            case "find_positive_news_stocks":
                return self.find_positive_news_stocks(**validated_args)
            case "add_watchlist":
                return self.add_watchlist(session_id=session_id, **validated_args)
            case "lookup_glossary_term":
                return self.lookup_glossary_term(**validated_args)
        raise ValueError(f"알 수 없는 도구: {tool_name}")

    async def execute(
        self,
        tool_name: str,
        tool_args: dict[str, Any] | None = None,
        session_id: str = "default",
    ) -> dict[str, Any]:
        """실패를 구조화된 결과로 바꿔 그래프 전체 중단을 방지합니다."""
        args = dict(tool_args or {})
        logger.info(f"🔧 [Tool] 실행: {tool_name} | args={args}")
        try:
            if tool_name not in TOOL_ARG_SCHEMAS:
                logger.warning(f"⚠️ [Tool] 알 수 없는 도구: {tool_name}")
                return ToolErrorResult(
                    error=f"알 수 없는 도구: {tool_name}",
                ).model_dump(exclude_none=True)
            schema = TOOL_ARG_SCHEMAS[tool_name]
            validated_args = schema.model_validate(args).model_dump(
                exclude_none=True,
            )

            timeout = TOOL_TIMEOUT_SECONDS.get(tool_name, 15)
            attempts = TOOL_MAX_ATTEMPTS.get(tool_name, 2)
            last_error: Exception | None = None
            result = None
            for attempt in range(1, attempts + 1):
                try:
                    coroutine = self._build_coroutine(
                        tool_name, validated_args, session_id
                    )
                    raw = await asyncio.wait_for(coroutine, timeout=timeout)
                    result = (
                        TOOL_RESULT_SCHEMAS[tool_name]
                        .model_validate(raw)
                        .model_dump(mode="json")
                    )
                    if attempt > 1:
                        logger.info(
                            f"🔁 [Tool] 재시도 성공: {tool_name} (시도 {attempt}/{attempts})"
                        )
                    break
                except RETRYABLE_ERRORS as exc:
                    last_error = exc
                    logger.warning(
                        f"⏳ [Tool] {tool_name} 일시적 실패 "
                        f"(시도 {attempt}/{attempts}): {type(exc).__name__}"
                    )
                    if attempt < attempts:
                        await asyncio.sleep(RETRY_BACKOFF_SECONDS * attempt)
            if result is None:
                raise last_error or RuntimeError(f"{tool_name} 실행 실패")
        except Exception as exc:
            logger.exception(f"도구 실행 실패: tool={tool_name}")
            return ToolErrorResult(
                error=str(exc),
                error_type=type(exc).__name__,
            ).model_dump(exclude_none=True)

        logger.info(f"✅ [Tool] 완료: {tool_name} | success={result.get('success')}")
        return result

    async def get_stock_price(
        self,
        ticker: str,
        period: str = "3m",
    ) -> dict[str, Any]:
        """실제 일봉을 바탕으로 현재가·등락률·재무지표를 조회합니다."""
        logger.debug(f"[get_stock_price] ticker={ticker}, period={period}")
        data = await price.get_stock_snapshot(ticker, period=period)
        return {"success": True, "data": data}

    async def get_news(
        self,
        company: str,
        days: int = 7,
        direction: Literal["down", "up", "neutral"] = "neutral",
        limit: int = 15,
    ) -> dict[str, Any]:
        """종목 관련 최신 뉴스와 주가 방향 근거 후보를 조회합니다."""
        logger.debug(
            f"[get_news] company={company}, days={days}, direction={direction}"
        )
        if direction == "neutral":
            items = await news.get_company_news(
                company,
                days=days,
                limit=limit,
            )
        else:
            items = await news.get_stock_issue_news(
                company,
                days=days,
                direction=direction,
                limit=limit,
            )
        normalized = [_normalize_news_item(item, direction) for item in items]
        return {
            "success": True,
            "data": {
                "company": company,
                "direction": direction,
                "news": normalized,
            },
        }

    async def get_disclosure(
        self,
        ticker: str,
        limit: int = 10,
    ) -> dict[str, Any]:
        """회사명 또는 종목코드로 최근 OpenDART 공시를 조회합니다."""
        logger.debug(f"[get_disclosure] ticker={ticker}, limit={limit}")
        rows = await disclosure.get_recent_disclosures(ticker, limit=limit)
        normalized = [
            {
                **row,
                "title": row["report_name"],
                "date": row["received_date"],
                "url": row["source_url"],
            }
            for row in rows
        ]
        return {
            "success": True,
            "data": {
                "ticker": ticker,
                "disclosures": normalized,
            },
        }

    async def find_positive_news_stocks(
        self,
        universe: list[str] | None = None,
        *,
        days: int = 3,
        limit: int = 5,
    ) -> dict[str, Any]:
        """유니버스에서 실제 상승률이 높은 종목을 순서대로 선별합니다."""
        companies = universe or DEFAULT_UNIVERSE
        cache_key = (tuple(companies), days, limit)
        cached = _get_cached_screener(cache_key)
        if cached is not None:
            logger.debug("[find_positive_news_stocks] cache hit")
            return cached

        logger.debug(f"[find_positive_news_stocks] universe_size={len(companies)}")
        price_sema = asyncio.Semaphore(4)

        async def _price_of(company: str) -> dict[str, Any] | None:
            """종목의 최근 등락률만 경량 조회한다(상승 중인 것만)."""
            async with price_sema:
                try:
                    change_pct = await asyncio.wait_for(
                        price.get_change_pct(company), timeout=12
                    )
                except Exception:
                    logger.warning(f"상승률 스크리너 시세 실패: {company}")
                    return None
            if change_pct is None or change_pct <= 0:
                return None
            return {"ticker": company, "change_pct": round(float(change_pct), 2)}

        priced = [
            p for p in await asyncio.gather(*(_price_of(c) for c in companies)) if p
        ]
        # 상승률 높은 순으로 정렬 → 상위 N개
        priced.sort(key=lambda x: x["change_pct"], reverse=True)
        top = priced[:limit]

        news_sema = asyncio.Semaphore(4)

        async def _attach(item: dict[str, Any]) -> dict[str, Any]:
            """상위 종목에 상승 근거 헤드라인을 best-effort로 붙인다(없어도 통과)."""
            company = item["ticker"]
            async with news_sema:
                try:
                    items = await news.get_stock_issue_news(
                        company,
                        direction="up",
                        days=days,
                        limit=5,
                        display=30,
                        max_queries=1,
                    )
                except Exception:
                    items = []
            evidence = [n for n in items if n.get("has_direction_evidence")] or items
            headline = evidence[0].get("title") if evidence else None
            link = (
                (evidence[0].get("original_link") or evidence[0].get("link"))
                if evidence
                else None
            )
            return {
                "ticker": company,
                "positive_score": item["change_pct"],
                "evidence_count": len(evidence),
                "change_pct": item["change_pct"],
                "top_news": headline or f"{company} 상승",
                "url": link or "",
                "news": [_normalize_news_item(n, "up") for n in evidence[:3]],
            }

        ranked = list(await asyncio.gather(*(_attach(i) for i in top)))
        result = {
            "success": True,
            "data": {"stocks": ranked},
        }
        # 빈 결과(일시적 조회 실패 등)는 캐시하지 않아 다음 시도에서 다시 조회한다.
        if ranked:
            _set_cached_screener(cache_key, result)
        return result

    async def add_watchlist(
        self,
        ticker: str,
        session_id: str,
    ) -> dict[str, Any]:
        """관심 종목을 Supabase에 중복 없이 저장합니다."""
        logger.debug(f"[add_watchlist] ticker={ticker}, session_id={session_id}")
        code = await price.resolve_ticker(ticker)
        saved = await watchlist.add_watchlist(
            ticker=code,
            name=ticker,
            session_id=session_id,
        )
        return {"success": True, "data": saved}

    async def lookup_glossary_term(
        self,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        """Look up investment terms from the structured glossary table."""
        logger.debug(f"[lookup_glossary_term] query={query}, limit={limit}")
        terms = await glossary.search_or_research_terms(query, limit=limit)
        return {
            "success": True,
            "data": {
                "query": query,
                "terms": terms,
            },
        }


def _normalize_news_item(
    item: dict[str, Any],
    direction: Literal["down", "up", "neutral"],
) -> dict[str, Any]:
    result = dict(item)
    published_at = result.get("published_at")
    if isinstance(published_at, datetime):
        result["published_at"] = published_at.isoformat()

    direction_evidence = bool(result.get("has_direction_evidence"))
    sentiment = "중립"
    if direction_evidence and direction == "down":
        sentiment = "악재"
    elif direction_evidence and direction == "up":
        sentiment = "호재"

    reason_keywords = (
        result.get("direction_keywords") or result.get("matched_keywords") or []
    )
    result.setdefault("relevance_score", 0)
    result.setdefault("matched_keywords", [])
    result.setdefault("direct_company_match", False)
    result.setdefault("company_mentioned", False)
    result.setdefault("market_context_match", False)
    result.setdefault("direction", direction)
    result.setdefault("direction_keywords", [])
    result.setdefault("opposite_direction_keywords", [])
    result.setdefault("has_direction_evidence", False)
    result.setdefault("issue_score", result["relevance_score"])
    result.setdefault("ranking_tier", 0)
    result.update(
        {
            "source": result.get("source_domain", ""),
            "url": result.get("original_link") or result.get("link", ""),
            "sentiment": sentiment,
            "reason": ", ".join(reason_keywords) or "최신 관련 기사",
        }
    )
    return result


def _get_cached_screener(
    cache_key: tuple[tuple[str, ...], int, int],
) -> dict[str, Any] | None:
    now = monotonic()
    with _SCREENER_CACHE_LOCK:
        cached = _SCREENER_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, result = cached
        if now - created_at > _SCREENER_CACHE_TTL_SECONDS:
            _SCREENER_CACHE.pop(cache_key, None)
            return None
        return deepcopy(result)


def _set_cached_screener(
    cache_key: tuple[tuple[str, ...], int, int],
    result: dict[str, Any],
) -> None:
    with _SCREENER_CACHE_LOCK:
        _SCREENER_CACHE[cache_key] = (monotonic(), deepcopy(result))

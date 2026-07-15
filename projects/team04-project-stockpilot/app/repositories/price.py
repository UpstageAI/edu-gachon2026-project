"""pykrx 기반 국내 주식 시세·일봉·재무지표 조회."""

from __future__ import annotations

import asyncio
import contextlib
from copy import deepcopy
import io
import math
import threading
import os
import re
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from typing import Any

from loguru import logger

from app.core.config import settings

_PERIOD_DAYS = {
    "1w": 7,
    "1m": 31,
    "3m": 93,
    "6m": 186,
    "1y": 366,
}

# 기본 유니버스는 KRX 로그인 없이도 종목명을 코드로 바꿀 수 있다.
# 코드로 시세를 조회하는 경로(get_market_ohlcv_by_date)는 KRX 로그인이 필요 없으므로,
# 자주 묻는 종목의 코드를 넉넉히 하드코딩해 로그인 없이도 차트가 뜨게 한다.
_KNOWN_TICKERS = {
    # 대형주
    "삼성전자": "005930",
    "SK하이닉스": "000660",
    "LG에너지솔루션": "373220",
    "삼성바이오로직스": "207940",
    "현대차": "005380",
    "기아": "000270",
    "NAVER": "035420",
    "카카오": "035720",
    "POSCO홀딩스": "005490",
    "셀트리온": "068270",
    "LG화학": "051910",
    "삼성SDI": "006400",
    "삼성전기": "009150",
    "삼성물산": "028260",
    "LG전자": "066570",
    "현대모비스": "012330",
    "SK이노베이션": "096770",
    "SK텔레콤": "017670",
    "KT": "030200",
    "LG유플러스": "032640",
    "한국전력": "015760",
    "삼성생명": "032830",
    "삼성화재": "000810",
    "KB금융": "105560",
    "신한지주": "055550",
    "하나금융지주": "086790",
    "우리금융지주": "316140",
    "메리츠금융지주": "138040",
    "카카오뱅크": "323410",
    "아모레퍼시픽": "090430",
    "에이피알": "278470",
    "실리콘투": "257720",
    "브이티": "018290",
    "한국콜마": "161890",
    "코스맥스": "192820",
    "현대글로비스": "086280",
    "삼성SDS": "018260",
    "삼성에스디에스": "018260",
    "현대오토에버": "307950",
    "현대위아": "011210",
    "HL만도": "204320",
    "LG": "003550",
    "SK": "034730",
    "SKC": "011790",
    "현대제철": "004020",
    "고려아연": "010130",
    "삼성E&A": "028050",
    "삼성엔지니어링": "028050",
    "현대건설": "000720",
    "GS건설": "006360",
    # 방산·조선·중공업
    "한화오션": "042660",
    "한화에어로스페이스": "012450",
    "한국항공우주": "047810",
    "LIG넥스원": "079550",
    "현대로템": "064350",
    "삼성중공업": "010140",
    "HD현대중공업": "329180",
    "HD한국조선해양": "009540",
    "HD현대미포": "010620",
    "HD현대마린솔루션": "443060",
    "HD현대": "267250",
    "두산에너빌리티": "034020",
    "두산로보틱스": "454910",
    "두산": "000150",
    "두산밥캣": "241560",
    "두산퓨얼셀": "336260",
    "한화": "000880",
    "한화시스템": "272210",
    "HMM": "011200",
    "대한항공": "003490",
    # 2차전지·소재
    "에코프로": "086520",
    "에코프로비엠": "247540",
    "포스코퓨처엠": "003670",
    "포스코인터내셔널": "047050",
    "한화솔루션": "009830",
    "LG디스플레이": "034220",
    "엘앤에프": "066970",
    "천보": "278280",
    "더블유씨피": "393890",
    "에코프로머티": "450080",
    "금양": "001570",
    "엔켐": "348370",
    "나노신소재": "121600",
    "피엔티": "137400",
    "POSCO퓨처엠": "003670",
    # 반도체·PCB·AI 인프라
    "심텍": "222800",
    "대덕전자": "353200",
    "코리아써키트": "007810",
    "이수페타시스": "007660",
    "한미반도체": "042700",
    "DB하이텍": "000990",
    "HPSP": "403870",
    "리노공업": "058470",
    "이오테크닉스": "039030",
    "주성엔지니어링": "036930",
    "원익IPS": "240810",
    "솔브레인": "357780",
    "동진쎄미켐": "005290",
    "ISC": "095340",
    "티씨케이": "064760",
    "하나마이크론": "067310",
    "네패스": "033640",
    "제주반도체": "080220",
    "가온칩스": "399720",
    "두산테스나": "131970",
    "피에스케이": "319660",
    "유진테크": "084370",
    "테크윙": "089030",
    "에스앤에스텍": "101490",
    "파크시스템스": "140860",
    "칩스앤미디어": "094360",
    "오픈엣지테크놀로지": "394280",
    "아나패스": "123860",
    "덕산네오룩스": "213420",
    "덕산테코피아": "317330",
    "기가비스": "420770",
    "인텍플러스": "064290",
    "엑시콘": "092870",
    "와이씨": "232140",
    "넥스틴": "348210",
    "에프에스티": "036810",
    "원익QnC": "074600",
    "코미코": "183300",
    "SFA반도체": "036540",
    # 게임·엔터·인터넷
    "크래프톤": "259960",
    "엔씨소프트": "036570",
    "넷마블": "251270",
    "카카오게임즈": "293490",
    "하이브": "352820",
    "SK스퀘어": "402340",
    "펄어비스": "263750",
    "위메이드": "112040",
    "JYP Ent.": "035900",
    "에스엠": "041510",
    "와이지엔터테인먼트": "122870",
    "YG PLUS": "037270",
    "CJ ENM": "035760",
    "카페24": "042000",
    "더존비즈온": "012510",
    "안랩": "053800",
    "솔트룩스": "304100",
    "마음AI": "377480",
    "루닛": "328130",
    "뷰노": "338220",
    "셀바스AI": "108860",
    "코난테크놀로지": "402030",
    # 바이오·헬스케어
    "HLB": "028300",
    "알테오젠": "196170",
    "유한양행": "000100",
    "한미약품": "128940",
    "녹십자": "006280",
    "종근당": "185750",
    "리가켐바이오": "141080",
    "보로노이": "310210",
    "에이비엘바이오": "298380",
    "SK바이오팜": "326030",
    "SK바이오사이언스": "302440",
    "레고켐바이오": "141080",
    "파마리서치": "214450",
    "휴젤": "145020",
    "메디톡스": "086900",
    "대웅제약": "069620",
    "삼천당제약": "000250",
    # 로봇·기계·소비재·금융 보강
    "레인보우로보틱스": "277810",
    "로보티즈": "108490",
    "삼양식품": "003230",
    "농심": "004370",
    "오리온": "271560",
    "CJ제일제당": "097950",
    "빙그레": "005180",
    "풀무원": "017810",
    "호텔신라": "008770",
    "강원랜드": "035250",
    "파라다이스": "034230",
    "F&F": "383220",
    "영원무역": "111770",
    "S-Oil": "010950",
    "롯데케미칼": "011170",
    "금호석유": "011780",
    "씨에스윈드": "112610",
    "LS": "006260",
    "LS ELECTRIC": "010120",
    "대한전선": "001440",
    "효성중공업": "298040",
    "일진전기": "103590",
    "제룡전기": "033100",
    "미래에셋증권": "006800",
    "키움증권": "039490",
    "삼성증권": "016360",
    "한국금융지주": "071050",
    # 흔한 별칭 (표시는 정식명으로)
    "네이버": "035420",
    "포스코홀딩스": "005490",
    "엘지에너지솔루션": "373220",
    "엘지화학": "051910",
    "엘지전자": "066570",
    "삼성전자우": "005935",
    "삼전우": "005935",
    "삼성전자 우": "005935",
    "하닉": "000660",
    "SK하닉": "000660",
    "JYP엔터": "035900",
    "제왑": "035900",
}
KNOWN_TICKER_NAMES = tuple(_KNOWN_TICKERS.keys())
# 별칭 표기는 code→표시이름 매핑에서 제외해 정식명이 보이게 한다.
_ALIAS_NAMES = {
    "네이버", "포스코홀딩스", "엘지에너지솔루션", "엘지화학", "엘지전자",
    "삼전우", "삼성전자 우", "하닉", "SK하닉", "제왑",
    "POSCO퓨처엠", "삼성엔지니어링", "레고켐바이오",
}
_TICKER_NAMES = {}
for _name, _ticker in _KNOWN_TICKERS.items():
    if _name in _ALIAS_NAMES:
        continue
    _TICKER_NAMES.setdefault(_ticker, _name)

# 전체 상장 종목 이름↔코드 인덱스 (pykrx 공개 데이터, KRX 로그인 불필요). 최초 1회만 구축 후 캐시.
_NAME_INDEX: list[tuple[str, str]] | None = None   # (정규화된_이름, 코드), 긴 이름 우선 정렬
_CODE_NAME: dict[str, str] = {}
_INDEX_LOCK = threading.Lock()
_SENSITIVE_STDIO_LOCK = threading.Lock()
_SNAPSHOT_CACHE_LOCK = threading.Lock()
_SNAPSHOT_CACHE_TTL_SECONDS = 1800
_SNAPSHOT_CACHE: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}


class PriceDataError(RuntimeError):
    """시세 또는 재무지표를 조회하지 못했을 때 발생합니다."""


async def resolve_ticker(query: str) -> str:
    """6자리 종목코드 또는 회사명을 KRX 종목코드로 변환합니다.

    pykrx의 종목 목록/이름 조회는 로그인 없이 되는 공개 데이터이므로,
    기본 종목이 아니어도 전체 상장 종목에서 이름으로 코드를 찾는다.
    """
    normalized = _normalize_name(query)
    if re.fullmatch(r"\d{6}", normalized):
        return normalized

    # 1) 기본 유니버스 정확 일치 (pykrx 없이 즉시)
    known = {_normalize_name(name): ticker for name, ticker in _KNOWN_TICKERS.items()}
    if normalized in known:
        return known[normalized]

    # 2) 기본 유니버스 부분 일치 (질문에 군더더기가 섞여 있어도 인식)
    for name, ticker in sorted(_KNOWN_TICKERS.items(), key=lambda kv: len(kv[0]), reverse=True):
        if _normalize_name(name) in normalized:
            return ticker

    # 3) 전체 상장 종목 인덱스에서 해석 (로그인 불필요)
    return await asyncio.to_thread(_resolve_ticker_from_index, normalized)


async def get_ohlcv(ticker: str, start: str, end: str) -> list[dict[str, Any]]:
    """기간 내 수정주가 일봉을 JSON 직렬화 가능한 형태로 반환합니다."""
    code = await resolve_ticker(ticker)
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if start_date > end_date:
        raise ValueError("start는 end보다 늦을 수 없습니다.")

    stock = _get_stock_api()
    try:
        frame = await asyncio.to_thread(
            _call_public_krx,
            stock.get_market_ohlcv_by_date,
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            code,
        )
    except Exception as exc:
        raise PriceDataError(f"{code} 일봉 조회에 실패했습니다: {exc}") from exc

    if frame.empty:
        raise PriceDataError(f"{code}의 조회 기간 내 일봉 데이터가 없습니다.")

    column_names = {
        "시가": "open",
        "고가": "high",
        "저가": "low",
        "종가": "close",
        "거래량": "volume",
        "등락률": "change_pct",
    }
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        item = {"date": _format_index_date(index)}
        for column, value in row.items():
            key = column_names.get(str(column), str(column).lower())
            item[key] = _python_number(value)
        rows.append(item)
    return rows


async def get_fundamentals(
    ticker: str,
    *,
    as_of: str | None = None,
) -> dict[str, Any] | None:
    """가장 최근 BPS·PER·PBR·EPS·배당지표를 반환합니다.

    pykrx 1.2.x의 재무지표 경로는 KRX 로그인이 필요하므로 자격 증명이
    없으면 시세 조회를 막지 않고 ``None``을 반환합니다.
    """
    if not settings.krx_id or not settings.krx_pw:
        logger.info("KRX_ID/KRX_PW 미설정: 재무지표 조회 생략")
        return None

    code = await resolve_ticker(ticker)
    end_date = _parse_date(as_of) if as_of else date.today()
    start_date = end_date - timedelta(days=31)
    stock = _get_stock_api()
    try:
        frame = await asyncio.to_thread(
            _call_with_suppressed_stdio,
            stock.get_market_fundamental_by_date,
            start_date.strftime("%Y%m%d"),
            end_date.strftime("%Y%m%d"),
            code,
        )
    except Exception as exc:
        raise PriceDataError(f"{code} 재무지표 조회에 실패했습니다: {exc}") from exc

    if frame.empty:
        return None

    index = frame.index[-1]
    row = frame.iloc[-1]
    result: dict[str, Any] = {"date": _format_index_date(index)}
    for column, value in row.items():
        result[str(column).lower()] = _python_number(value)
    return result


async def get_change_pct(ticker: str) -> float | None:
    """랭킹용 경량 등락률 조회 — 재무지표·장기 일봉 없이 최근 등락률만 반환.

    스크리너에서 다수 종목을 빠르게 정렬하려고 쓴다. 무거운 get_stock_snapshot
    (3개월 일봉 + 재무지표)을 유니버스 전체에 돌리면 타임아웃이 나서 분리했다.
    """
    try:
        code = await resolve_ticker(ticker)
    except Exception:
        return None
    end_date = date.today()
    start_date = end_date - timedelta(days=10)
    try:
        ohlcv = await get_ohlcv(code, start_date.isoformat(), end_date.isoformat())
    except Exception:
        return None
    if not ohlcv:
        return None
    latest = ohlcv[-1]
    change_pct = _coerce_pct(latest.get("change_pct"))
    if change_pct is None:
        previous = ohlcv[-2] if len(ohlcv) > 1 else None
        current_close = latest.get("close")
        previous_close = previous.get("close") if previous else None
        if current_close is not None and previous_close not in (None, 0):
            change_pct = round((current_close - previous_close) / previous_close * 100, 2)
    return change_pct


async def get_stock_snapshot(
    ticker: str,
    *,
    period: str = "3m",
    end: str | None = None,
    include_fundamentals: bool = False,
) -> dict[str, Any]:
    """현재가·등락률·일봉·재무지표를 한 번에 반환합니다."""
    if period not in _PERIOD_DAYS:
        allowed = ", ".join(_PERIOD_DAYS)
        raise ValueError(f"period는 {allowed} 중 하나여야 합니다.")

    code = await resolve_ticker(ticker)
    end_date = _parse_date(end) if end else date.today()
    cache_key = (code, period, end_date.isoformat())
    use_live_cache = end is None
    if use_live_cache:
        cached = _get_cached_snapshot(cache_key)
        if cached is not None:
            logger.debug(f"[Price] cached snapshot hit: ticker={code}, period={period}")
            return cached

    start_date = end_date - timedelta(days=_PERIOD_DAYS[period])
    ohlcv = await get_ohlcv(code, start_date.isoformat(), end_date.isoformat())
    latest = ohlcv[-1]
    previous = ohlcv[-2] if len(ohlcv) > 1 else None

    current_price = latest.get("close")
    previous_close = previous.get("close") if previous else None
    change = None
    if current_price is not None and previous_close not in (None, 0):
        change = current_price - previous_close

    # pykrx가 내려준 일봉의 "등락률" 컬럼을 단일 기준값으로 사용한다.
    # 값이 누락된 경우에만 종가와 전일 종가로 보수적으로 재계산한다.
    change_pct = _coerce_pct(latest.get("change_pct"))
    if change_pct is None and change is not None and previous_close not in (None, 0):
        change_pct = round(change / previous_close * 100, 2)

    fundamentals = (
        await get_fundamentals(code, as_of=end_date.isoformat())
        if include_fundamentals
        else None
    )
    snapshot = {
        "ticker": code,
        "name": _TICKER_NAMES.get(code) or _CODE_NAME.get(code) or ticker,
        "as_of": latest["date"],
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "current_price": current_price,
        "previous_close": previous_close,
        "change": change,
        "change_pct": change_pct,
        "period": period,
        "ohlcv": ohlcv,
        "fundamentals": fundamentals,
        "fundamentals_available": fundamentals is not None,
    }
    if use_live_cache:
        _set_cached_snapshot(cache_key, snapshot)
    return snapshot


def _get_cached_snapshot(cache_key: tuple[str, str, str]) -> dict[str, Any] | None:
    now = monotonic()
    with _SNAPSHOT_CACHE_LOCK:
        cached = _SNAPSHOT_CACHE.get(cache_key)
        if cached is None:
            return None
        created_at, snapshot = cached
        if now - created_at > _SNAPSHOT_CACHE_TTL_SECONDS:
            _SNAPSHOT_CACHE.pop(cache_key, None)
            return None
        return deepcopy(snapshot)


def _set_cached_snapshot(cache_key: tuple[str, str, str], snapshot: dict[str, Any]) -> None:
    with _SNAPSHOT_CACHE_LOCK:
        _SNAPSHOT_CACHE[cache_key] = (monotonic(), deepcopy(snapshot))


def _coerce_pct(value: Any) -> float | None:
    value = _python_number(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def _get_stock_api() -> Any:
    # Public price reads do not need a KRX login. If KRX_ID/KRX_PW are present,
    # pykrx may try to authenticate at import time and block for 10+ seconds.
    # Hide credentials during import so the market-data path stays fast.
    return _call_with_suppressed_stdio(_import_public_stock_api)


def _import_public_stock_api() -> Any:
    saved_id = os.environ.pop("KRX_ID", None)
    saved_pw = os.environ.pop("KRX_PW", None)
    try:
        return _import_stock_api()
    finally:
        if saved_id is not None:
            os.environ["KRX_ID"] = saved_id
        if saved_pw is not None:
            os.environ["KRX_PW"] = saved_pw


def _import_stock_api() -> Any:
    from pykrx import stock

    return stock


def _call_public_krx(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Call public KRX data APIs without triggering credential-based login."""

    saved_id = os.environ.pop("KRX_ID", None)
    saved_pw = os.environ.pop("KRX_PW", None)
    try:
        return _call_with_suppressed_stdio(func, *args, **kwargs)
    finally:
        if saved_id is not None:
            os.environ["KRX_ID"] = saved_id
        if saved_pw is not None:
            os.environ["KRX_PW"] = saved_pw


def _call_with_suppressed_stdio(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Call a noisy third-party function without leaking credentials to logs."""
    with _SENSITIVE_STDIO_LOCK:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return func(*args, **kwargs)


def _build_name_index() -> None:
    """전체 상장 종목의 (정규화 이름 → 코드) 인덱스를 1회 구축해 캐시한다."""
    global _NAME_INDEX
    stock = _get_stock_api()
    codes: list[str] = []
    for back in range(0, 8):  # 주말·휴장 대비 최근 영업일까지 후퇴
        lookup_date = (date.today() - timedelta(days=back)).strftime("%Y%m%d")
        try:
            codes = _call_public_krx(
                stock.get_market_ticker_list,
                lookup_date,
                market="ALL",
            )
        except Exception:
            codes = []
        if codes:
            break

    pairs: list[tuple[str, str]] = []
    for code in codes:
        try:
            name = _call_public_krx(stock.get_market_ticker_name, code)
        except Exception:
            continue
        if not name:
            continue
        _CODE_NAME[code] = name
        pairs.append((_normalize_name(name), code))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)  # 긴 이름 우선
    _NAME_INDEX = pairs
    logger.info(f"📇 [Price] 종목 인덱스 구축 완료: {len(pairs)}개")


def _ensure_index() -> list[tuple[str, str]]:
    global _NAME_INDEX
    if _NAME_INDEX is None:
        with _INDEX_LOCK:
            if _NAME_INDEX is None:
                _build_name_index()
    return _NAME_INDEX or []


def _resolve_ticker_from_index(normalized_query: str) -> str:
    try:
        index = _ensure_index()
    except Exception as exc:
        raise PriceDataError(f"KRX 종목 목록 조회에 실패했습니다: {exc}") from exc

    # 정확 일치 우선
    for name, code in index:
        if name == normalized_query:
            return code
    # 부분 문자열(긴 이름 우선): "한화오션가", "한화오션주가어때" 등에서 "한화오션" 인식
    for name, code in index:
        if len(name) >= 2 and name in normalized_query:
            return code
    raise PriceDataError(f"종목을 찾지 못했습니다: {normalized_query}")


def _parse_date(value: str | None) -> date:
    if not value:
        raise ValueError("날짜 값이 필요합니다.")
    compact = value.replace("-", "")
    try:
        return datetime.strptime(compact, "%Y%m%d").date()
    except ValueError as exc:
        raise ValueError(
            f"날짜는 YYYY-MM-DD 또는 YYYYMMDD 형식이어야 합니다: {value}"
        ) from exc


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def _format_index_date(value: Any) -> str:
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value)
    try:
        return _parse_date(text).isoformat()
    except ValueError:
        return text


def _python_number(value: Any) -> int | float | None:
    if hasattr(value, "item"):
        value = value.item()
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4)
    return value

"""Market report indicator slots for the full report image."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReportIndicatorSlot:
    position: int
    indicator_id: str
    display_name: str
    icon_key: str
    source: str
    unit: str | None = None
    value_decimals: int = 2
    change_decimals: int = 2
    aliases: tuple[str, ...] = field(default_factory=tuple)


MARKET_REPORT_SLOTS: tuple[ReportIndicatorSlot, ...] = (
    ReportIndicatorSlot(1, "kospi", "코스피", "kr", "yfinance", "pt", aliases=("^KS11", "topic_kospi")),
    ReportIndicatorSlot(2, "kosdaq", "코스닥", "kr", "yfinance", "pt", aliases=("^KQ11", "topic_kosdaq")),
    ReportIndicatorSlot(3, "nikkei", "니케이", "jp", "yfinance", "pt", aliases=("^N225", "topic_nikkei")),
    ReportIndicatorSlot(4, "dow", "다우", "us", "yfinance", "pt", aliases=("^DJI", "topic_dow")),
    ReportIndicatorSlot(5, "nasdaq", "나스닥", "us", "yfinance", "pt", aliases=("^IXIC", "topic_nasdaq")),
    ReportIndicatorSlot(6, "sp500", "S&P500", "us", "yfinance", "pt", aliases=("^GSPC", "topic_sp500")),
    ReportIndicatorSlot(7, "shanghai", "상해종합", "cn", "yfinance", "pt", aliases=("000001.SS", "topic_shanghai")),
    ReportIndicatorSlot(8, "hangseng", "항셍(홍콩)", "hk", "yfinance", "pt", aliases=("^HSI", "topic_hangseng")),
    ReportIndicatorSlot(9, "btc", "비트코인", "btc", "yfinance", "USD", aliases=("bitcoin", "BTC-USD", "topic_btc")),
    ReportIndicatorSlot(10, "gold", "국제 금", "gold", "yfinance", "USD", aliases=("GC=F", "topic_gold")),
    ReportIndicatorSlot(11, "silver", "은", "silver", "yfinance", "USD", aliases=("SI=F", "topic_silver")),
    ReportIndicatorSlot(12, "wti", "WTI", "oil", "yfinance", "USD", aliases=("CL=F", "topic_wti")),
    ReportIndicatorSlot(13, "usdkrw", "달러화", "usd", "yfinance", "KRW", aliases=("KRW=X", "topic_usdkrw")),
    ReportIndicatorSlot(14, "eurkrw", "유로화", "eur", "yfinance", "KRW", aliases=("EURKRW=X", "topic_eurkrw")),
    ReportIndicatorSlot(15, "jpykrw", "엔화", "jpy", "yfinance", "KRW", aliases=("JPYKRW=X", "topic_jpykrw")),
    ReportIndicatorSlot(16, "kr10y", "한국채(10년)", "kr_bond", "ecos", "%", 4, 4, ("topic_kr10y",)),
    ReportIndicatorSlot(17, "us10y", "미국채(10년)", "us_bond", "fred", "%", 4, 4, ("DGS10", "topic_us10y")),
    ReportIndicatorSlot(18, "jp10y", "일국채(10년)", "jp_bond", "fred", "%", 4, 4, ("topic_jp10y",)),
    ReportIndicatorSlot(19, "kr_policy_rate", "한국 기준금리", "kr", "ecos", "%", 2, 2, ("topic_kr_policy_rate",)),
    ReportIndicatorSlot(
        20,
        "us_policy_rate",
        "미국 기준금리",
        "us",
        "fred",
        "%",
        2,
        2,
        ("FEDFUNDS", "fed_funds", "topic_fed_funds"),
    ),
    ReportIndicatorSlot(21, "eu_policy_rate", "유럽 기준금리", "eu", "fred", "%", 2, 2, ("topic_eu_policy_rate",)),
)


def indicator_aliases() -> dict[str, ReportIndicatorSlot]:
    aliases: dict[str, ReportIndicatorSlot] = {}
    for slot in MARKET_REPORT_SLOTS:
        aliases[slot.indicator_id] = slot
        aliases[slot.display_name] = slot
        for alias in slot.aliases:
            aliases[alias] = slot
    return aliases

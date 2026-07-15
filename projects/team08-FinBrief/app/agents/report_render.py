"""Render the full market indicator report as a square PNG image."""

from __future__ import annotations

import math
import os
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

from PIL import Image, ImageDraw, ImageFont

from .report_catalog import MARKET_REPORT_SLOTS, ReportIndicatorSlot, indicator_aliases


CANVAS = 1080
BG = (244, 246, 245)
INK = (24, 24, 24)
MUTED = (82, 88, 98)
LINE = (210, 214, 218)
UP = (190, 40, 45)
DOWN = (45, 45, 170)
FLAT = (95, 95, 95)

_FONT_CANDIDATES = [
    os.environ.get("FINBRIEF_FONT"),
    "C:/Windows/Fonts/malgun.ttf",
    "C:/Windows/Fonts/malgunbd.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
]

_ICON_COLORS = {
    "kr": ((255, 255, 255), (238, 55, 70), (44, 80, 185)),
    "us": ((245, 245, 245), (35, 70, 160), (210, 35, 50)),
    "jp": ((255, 255, 255), (210, 40, 60), (245, 245, 245)),
    "cn": ((225, 35, 35), (255, 210, 45), (225, 35, 35)),
    "hk": ((225, 35, 35), (255, 255, 255), (225, 35, 35)),
    "btc": ((246, 150, 35), (255, 255, 255), (246, 150, 35)),
    "gold": ((255, 215, 55), (235, 174, 30), (255, 245, 170)),
    "silver": ((224, 226, 228), (165, 170, 174), (245, 245, 245)),
    "oil": ((35, 145, 210), (255, 255, 255), (20, 105, 170)),
    "usd": ((70, 175, 70), (25, 130, 45), (130, 220, 120)),
    "eur": ((35, 150, 150), (50, 90, 180), (85, 205, 185)),
    "jpy": ((40, 150, 70), (245, 245, 245), (40, 150, 70)),
    "kr_bond": ((255, 255, 255), (145, 110, 190), (70, 80, 160)),
    "us_bond": ((255, 255, 255), (40, 150, 90), (70, 80, 180)),
    "jp_bond": ((255, 255, 255), (205, 70, 175), (245, 210, 245)),
    "eu": ((35, 80, 175), (255, 220, 45), (35, 80, 175)),
}


@lru_cache(maxsize=128)
def _font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if candidate and os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _pick(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item and item[key] is not None:
            return item[key]
    return None


def _index_indicators(indicators: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    aliases = indicator_aliases()
    indexed: dict[str, Mapping[str, Any]] = {}
    for item in indicators:
        raw_id = str(_pick(item, "indicator_id", "topic_id", "id") or "")
        raw_name = str(_pick(item, "name", "display_name") or "")
        candidates = [raw_id, raw_name, raw_id.removeprefix("topic_")]
        for candidate in candidates:
            if candidate in aliases:
                indexed[aliases[candidate].indicator_id] = item
                break
    return indexed


def _direction(change_value: float | None, change_percent: float | None) -> str:
    basis = change_percent if change_percent is not None else change_value
    if basis is None or abs(basis) < 1e-12:
        return "flat"
    return "up" if basis > 0 else "down"


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _format_number(value: float | None, decimals: int) -> str:
    if value is None:
        return "N/A"
    return f"{value:,.{decimals}f}"


def _format_value_with_unit(value: float | None, decimals: int, unit: str | None) -> str:
    number = _format_number(value, decimals)
    if number == "N/A":
        return number
    cleaned_unit = str(unit or "").strip()
    return f"{number} {cleaned_unit}" if cleaned_unit else number


def build_indicator_views(
    indicators: Iterable[Mapping[str, Any]],
    missing_indicators: Iterable[str] = (),
) -> list[dict[str, Any]]:
    indexed = _index_indicators(indicators)
    missing = set(missing_indicators)
    views: list[dict[str, Any]] = []

    for slot in MARKET_REPORT_SLOTS:
        item = indexed.get(slot.indicator_id)
        current = _as_float(_pick(item or {}, "current_value", "value"))
        previous = _as_float(_pick(item or {}, "previous_value", "prev"))
        change_value = _as_float(_pick(item or {}, "change_value", "change"))
        change_percent = _as_float(_pick(item or {}, "change_percent", "change_pct"))
        unit = _pick(item or {}, "unit") or slot.unit

        if change_value is None and current is not None and previous is not None:
            change_value = current - previous
        if change_percent is None and change_value is not None and previous not in (None, 0):
            change_percent = change_value / previous * 100

        is_missing = (
            slot.indicator_id in missing
            or f"topic_{slot.indicator_id}" in missing
            or current is None
            or bool(_pick(item or {}, "missing"))
        )
        if is_missing:
            current = None
            change_value = None
            change_percent = None
        rounded_current = _round(current, slot.value_decimals)

        views.append(
            {
                "position": slot.position,
                "indicator_id": slot.indicator_id,
                "display_name": slot.display_name,
                "icon_key": slot.icon_key,
                "source": _pick(item or {}, "source") or slot.source,
                "unit": unit,
                "value_decimals": slot.value_decimals,
                "change_decimals": slot.change_decimals,
                "current_value": rounded_current,
                "value_text": _format_value_with_unit(rounded_current, slot.value_decimals, unit),
                "previous_value": _round(previous, slot.value_decimals),
                "change_value": _round(change_value, slot.change_decimals),
                "change_percent": _round(change_percent, 2),
                "direction": "flat" if is_missing else _direction(change_value, change_percent),
                "missing": is_missing,
            }
        )
    return views


def report_output_path(run_date: date) -> str:
    root = Path(os.environ.get("FINBRIEF_REPORT_OUT") or Path(__file__).resolve().parent / "out_reports")
    return str(root / run_date.strftime("%Y%m%d") / f"market_report_{run_date:%Y%m%d}.png")


def _weekday_ko(value: date) -> str:
    return ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][value.weekday()]


def _fit_font(draw: ImageDraw.ImageDraw, text: str, max_width: int, start: int, minimum: int) -> ImageFont.ImageFont:
    for size in range(start, minimum - 1, -2):
        font = _font(size)
        if draw.textlength(text, font=font) <= max_width:
            return font
    return _font(minimum)


def _format_change(view: Mapping[str, Any]) -> tuple[str, tuple[int, int, int]]:
    if view["missing"]:
        return "■ N/A", FLAT
    direction = view["direction"]
    if direction == "flat":
        return "■ 0.00  0.00%", FLAT

    change_value = view.get("change_value")
    change_percent = view.get("change_percent")
    if change_value is None and change_percent is None:
        return "■ -", FLAT

    arrow = "▲" if direction == "up" else "▼"
    color = UP if direction == "up" else DOWN
    amount = "-" if change_value is None else f"{abs(float(change_value)):,.{view['change_decimals']}f}"
    pct = "" if change_percent is None else f" {float(change_percent):+.2f}%"
    return f"{arrow}{amount}{pct}", color


def _draw_background(draw: ImageDraw.ImageDraw) -> None:
    for y in range(22, CANVAS - 22, 10):
        shade = 232 + (y % 30)
        draw.line([(24, y), (CANVAS - 24, y - 8)], fill=(shade, shade, shade), width=1)
    draw.rectangle([20, 20, CANVAS - 20, CANVAS - 20], outline=(55, 55, 55), width=2)


def _draw_header(draw: ImageDraw.ImageDraw, run_date: date, source_label: str) -> None:
    x, y = 42, 40
    draw.rectangle([x, y, x + 50, y + 58], outline=LINE, width=1)
    draw.line([x + 5, y + 47, x + 17, y + 28, x + 28, y + 37, x + 48, y + 3], fill=UP, width=3)
    draw.line([x + 5, y + 33, x + 17, y + 40, x + 28, y + 30, x + 48, y + 20], fill=(70, 130, 180), width=2)
    draw.text((104, 61), "오늘의 증권", font=_font(46), fill=INK, anchor="lm")
    draw.text((CANVAS - 44, 52), f"{run_date:%y.%m.%d} {_weekday_ko(run_date)}", font=_font(24), fill=(20, 20, 90), anchor="ra")
    draw.text((CANVAS - 44, 82), f"출처: {source_label}", font=_font(18), fill=INK, anchor="ra")
    draw.line([42, 104, CANVAS - 42, 104], fill=INK, width=2)


def _draw_icon(draw: ImageDraw.ImageDraw, x: int, y: int, key: str) -> None:
    colors = _ICON_COLORS.get(key, ((230, 230, 230), (120, 130, 140), (245, 245, 245)))
    box = [x, y, x + 20, y + 58]
    draw.rounded_rectangle(box, radius=5, fill=colors[0], outline=INK, width=1)
    draw.rounded_rectangle([x + 2, y + 18, x + 18, y + 40], radius=3, fill=colors[1])
    draw.line([x + 4, y + 10, x + 16, y + 48], fill=colors[2], width=2)


def _draw_view(draw: ImageDraw.ImageDraw, view: Mapping[str, Any], col: int, row: int) -> None:
    left_margin = 40
    top = 120
    cell_w = 340
    row_h = 126
    x = left_margin + col * cell_w
    y = top + row * row_h

    _draw_icon(draw, x, y + 12, str(view["icon_key"]))
    # 제목은 좌측 정렬, 값은 우측 정렬 → 이름이 길어도 값과 겹치지 않음.
    title = str(view["display_name"])
    title_font = _fit_font(draw, title, 128, 32, 17)
    draw.text((x + 40, y + 30), title, font=title_font, fill=INK, anchor="lm")

    value = str(
        view.get("value_text")
        or _format_number(view.get("current_value"), int(view["value_decimals"]))
    )
    value_font = _fit_font(draw, value, 148, 32, 17)
    draw.text((x + cell_w - 22, y + 30), value, font=value_font, fill=INK, anchor="rm")

    change_text, color = _format_change(view)
    change_font = _fit_font(draw, change_text, 250, 26, 16)
    draw.text((x + 40, y + 76), change_text, font=change_font, fill=color, anchor="lm")


def render_market_report_image(
    indicators: Iterable[Mapping[str, Any]],
    *,
    run_date: date,
    out_path: str | os.PathLike[str] | None = None,
    missing_indicators: Iterable[str] = (),
    source_label: str = "FRED, yfinance, ECOS",
) -> str:
    path = Path(out_path or report_output_path(run_date))
    path.parent.mkdir(parents=True, exist_ok=True)

    image = Image.new("RGB", (CANVAS, CANVAS), BG)
    draw = ImageDraw.Draw(image)
    _draw_background(draw)
    _draw_header(draw, run_date, source_label)

    views = build_indicator_views(indicators, missing_indicators)
    for index, view in enumerate(views):
        row, col = divmod(index, 3)
        _draw_view(draw, view, col, row)
        if col == 2:
            y = 120 + row * 126 + 112
            draw.line([40, y, CANVAS - 40, y], fill=LINE, width=1)

    draw.text(
        (CANVAS / 2, CANVAS - 34),
        "본 브리핑은 투자 조언이 아닌 참고용 정보입니다.",
        font=_font(16),
        fill=MUTED,
        anchor="mm",
    )
    image.save(path, "PNG")
    return str(path)

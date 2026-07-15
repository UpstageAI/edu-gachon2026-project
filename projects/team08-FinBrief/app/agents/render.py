"""compose_card 렌더러 (Pillow, dict 입력). 프로덕션은 HTML/CSS+Playwright 로 교체 예정.
   폰트: FINBRIEF_FONT 우선, 없으면 OS별 한글 폰트 자동탐색, 최후엔 기본폰트."""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

CANVAS = 1080
BG, INK, GRAY, MUTED, EDGE = (238, 241, 245), (26, 26, 26), (70, 78, 90), (150, 158, 168), (200, 205, 212)
THEMES = {"MARKET": (31, 111, 235), "GLOBAL": (74, 109, 167), "DOMESTIC": (31, 157, 85),
          "CRYPTO": (217, 138, 0), "FX": (14, 155, 142)}
DEFAULT_ACCENT = (74, 109, 167)
_FONT_CANDIDATES = [
    os.environ.get("FINBRIEF_FONT"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
]
_fc: dict[int, ImageFont.FreeTypeFont] = {}


def _f(sz: int):
    if sz in _fc:
        return _fc[sz]
    for c in _FONT_CANDIDATES:
        if c and os.path.exists(c):
            try:
                _fc[sz] = ImageFont.truetype(c, sz)
                return _fc[sz]
            except Exception:
                continue
    _fc[sz] = ImageFont.load_default()
    return _fc[sz]


def _fit_font(d, text, max_width, start, minimum):
    """텍스트가 max_width 안에 들어가는 가장 큰 폰트를 start→minimum 로 탐색."""
    for size in range(start, minimum - 1, -2):
        if d.textlength(str(text), font=_f(size)) <= max_width:
            return _f(size)
    return _f(minimum)


def _wrap(d, text, font, maxw):
    lines, cur = [], ""
    for w in str(text).split(" "):
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def render_card(content: dict, out_path: str) -> str:
    accent = THEMES.get(str(content.get("category", "")).upper(), DEFAULT_ACCENT)
    img = Image.new("RGB", (CANVAS, CANVAS), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([16, 16, CANVAS - 16, CANVAS - 16], radius=10, outline=accent, width=3)
    padx = 60
    bx, by, bs = padx, 52, 96
    # 공유·캐시 카드라 사용자별 순번을 이미지에 구울 수 없음 → 번호 대신 카테고리 뱃지.
    d.rounded_rectangle([bx, by, bx + bs, by + bs], radius=6, outline=accent, width=3)
    cat = str(content.get("category", "")).upper()
    d.text((bx + bs / 2, by + bs / 2), cat, font=_fit_font(d, cat, bs - 20, 30, 15), fill=accent, anchor="mm")
    tx = bx + bs + 26
    d.text((tx, by + 8), content.get("subtitle", ""), font=_f(30), fill=GRAY, anchor="lm")
    # 제목: 오른쪽 여백까지 폭에 맞춰 폰트 자동 축소(60→38). 잘림(…) 없이 전체 표시.
    head = str(content.get("headline", ""))
    head_maxw = (CANVAS - padx) - tx - 8
    d.text((tx, by + 66), head, font=_fit_font(d, head, head_maxw, 60, 38),
           fill=INK, anchor="lm", stroke_width=2, stroke_fill=INK)
    ix0, iy0, ix1, iy1 = padx, 200, CANVAS - padx, 600
    ip = content.get("image_url")
    if ip and os.path.exists(ip):
        ill = Image.open(ip).convert("RGB")
        s = max((ix1 - ix0) / ill.width, (iy1 - iy0) / ill.height)
        ill = ill.resize((int(ill.width * s), int(ill.height * s)))
        l, t = (ill.width - (ix1 - ix0)) // 2, (ill.height - (iy1 - iy0)) // 2
        img.paste(ill.crop((l, t, l + ix1 - ix0, t + iy1 - iy0)), (ix0, iy0))
    else:
        panel = Image.new("RGB", (ix1 - ix0, iy1 - iy0))
        pd = ImageDraw.Draw(panel)
        for y in range(iy1 - iy0):
            k = y / (iy1 - iy0)
            pd.line([(0, y), (ix1 - ix0, y)], fill=(int(216 - 38 * k), int(228 - 30 * k), int(244 - 12 * k)))
        img.paste(panel, (ix0, iy0))
        d.text(((ix0 + ix1) / 2, (iy0 + iy1) / 2), "AI 일러스트 자리 (Nano Banana)", font=_f(20), fill=(120, 130, 145), anchor="mm")
    d.rounded_rectangle([ix0, iy0, ix1, iy1], radius=8, outline=EDGE, width=2)
    maxw = CANVAS - 2 * padx
    y = 648
    for ln in _wrap(d, content.get("lead", ""), _f(33), maxw):
        d.text((CANVAS / 2, y), ln, font=_f(33), fill=INK, anchor="mm", stroke_width=1, stroke_fill=INK)
        y += 46
    y += 12
    # 본문: 제목/출처와 동일한 원칙으로 '잘림 없이 전체 표시'. 출처 영역(y=944) 전까지
    # 모든 줄이 들어가는 최대 폰트(28→18)를 고른다. 종전엔 28 고정이라 세로공간을
    # 넘는 뒷줄을 통째로 버려(…없이) 본문이 '5.'·'…설명.' 처럼 중간에 끊겨 보였다.
    body = str(content.get("body", ""))
    body_bottom = 944
    bsize, step, lines = 28, 40, _wrap(d, body, _f(28), maxw)
    for sz in range(28, 17, -2):
        st = sz + 12
        ls = _wrap(d, body, _f(sz), maxw)
        bsize, step, lines = sz, st, ls
        if y + st * (len(ls) - 1) <= body_bottom:
            break
    # 18pt 로도 안 들어가는 비정상적으로 긴 본문은 들어가는 줄까지만 + …(대롱대롱 남는
    # 번호 '5.' 등은 제거) 로 마무리해 어색한 중간 잘림을 방지.
    fit_lines = max(1, (body_bottom - y) // step + 1)
    if len(lines) > fit_lines:
        lines = lines[:fit_lines]
        lines[-1] = lines[-1].rstrip("0123456789.· ").rstrip() + "…"
    for ln in lines:
        d.text((CANVAS / 2, y), ln, font=_f(bsize), fill=GRAY, anchor="mm")
        y += step
    # 출처: 카드 폭에 맞춰 폰트 자동 축소(23→14) → … 잘림 방지.
    src = str(content.get("source", ""))
    d.text((CANVAS / 2, CANVAS - 92), src, font=_fit_font(d, src, CANVAS - 2 * padx, 23, 14), fill=GRAY, anchor="mm")
    d.text((CANVAS / 2, CANVAS - 54), content.get("disclaimer", ""), font=_f(18), fill=MUTED, anchor="mm")
    img.save(out_path)
    return out_path

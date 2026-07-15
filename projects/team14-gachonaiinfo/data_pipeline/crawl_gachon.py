"""
가천대학교 공식 홈페이지 크롤러 (category 태깅 + 마크다운 출력)

- 대상: www.gachon.ac.kr 의 정적 서버렌더링 페이지(subview.do)
- 출력: output/parsed/<name>.md  → 기존 app.ingest 가 자동 청킹·임베딩
        output/parsed/_crawl_manifest.json → source→category 매핑(향후 ingest 카테고리 반영용)

주의(환각 방지):
- SOURCES 의 URL 은 전부 실제 확인된 페이지만 등록한다. 임의 ID 추정 금지.
- 값이 바뀌면 반드시 원본 페이지에서 재확인.

사용법:
    python -m data_pipeline.crawl_gachon           # 전체 크롤
    python -m data_pipeline.crawl_gachon --dry     # 저장 없이 미리보기(제목/길이만)
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

import requests
from bs4 import BeautifulSoup, NavigableString, Tag
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "output" / "parsed"
MANIFEST = OUT_DIR / "_crawl_manifest.json"

# 수집 대상 수집일(요청 시점에 실측). 재실행 시 갱신됨.
# --- 크롤 대상: 전부 실제 확인된 정적 페이지 (category_l1/l2 는 카테고리_확정안 기준) ---
SOURCES = [
    {
        "name": "가천대 휴학 안내",
        "url": "https://www.gachon.ac.kr/kor/4021/subview.do",
        "category_l1": "leave_return",
        "category_l2": "leave",
    },
    {
        "name": "가천대 복학 안내",
        "url": "https://www.gachon.ac.kr/kor/4022/subview.do",
        "category_l1": "leave_return",
        "category_l2": "return",
    },
    {
        "name": "가천대 졸업 안내",
        "url": "https://www.gachon.ac.kr/kor/3219/subview.do",
        "category_l1": "graduation",
        "category_l2": "credit_requirement",
    },
    {
        "name": "가천대 사회봉사교과목 안내",
        "url": "https://www.gachon.ac.kr/ESG/9032/subview.do",
        "category_l1": "social_service",
        "category_l2": "requirement",
    },
    # --- 팀원 데이터 공백 보완분 ---
    # ※ 아래 두 건은 board 게시글(artclView)이라 1회 크롤 후 수동 큐레이션하여 고정했다.
    #   재크롤이 큐레이션본을 덮어쓰지 않도록 SOURCES 에서 제외한다. (유래 URL 보존)
    #   - 가천대 외국어졸업인증 기준점수  ← languagecenter/342/76109/artclView.do
    #       (팀원 PDF엔 이미지로만 있던 학과별 기준점수 표. AI/SW=그 외 학과 700~720 주석 추가)
    #   - 가천대 사회봉사 이수기준        ← ESG/9017 (2024-2 게시글)
    #       (30시간/VMS·1365/나이테 제출. 학기성 '제출기간'은 제거하고 기본 이수기준만 유지)
]

# 학사일정 등 월별 AJAX/이미지 페이지는 HTML 크롤 대신 PDF 파싱(parse_pdf.py) 경로 권장.
# 아래는 실제 확인된 학사일정 PDF 다운로드 링크. --pdf 옵션으로 내려받는다.
PDFS = [
    {
        "name": "2026-1학기 학사일정",
        "url": "https://www.gachon.ac.kr/bbs/mana/499/142047/download.do",
        "category_l1": "academic_calendar",
        "category_l2": "semester",
    },
]

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class TLSAdapter(HTTPAdapter):
    """가천대 서버가 요구하는 레거시 cipher 허용 (기본 requests 로는 SSL 핸드셰이크 실패)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def make_session() -> requests.Session:
    s = requests.Session()
    s.mount("https://", TLSAdapter())
    s.headers.update({"User-Agent": UA})
    return s


# ---------------- HTML → Markdown ----------------

_BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}


def _clean(text: str) -> str:
    t = text.replace("\xa0", " ")
    t = re.sub(r"/\S*\.do\b", "", t)  # 링크 경로 토큰 제거(/kor/3135/subview.do 등)
    return re.sub(r"[ \t]+", " ", t).strip()


def _table_to_md(table: Tag) -> str:
    rows = []
    for tr in table.find_all("tr"):
        cells = [_clean(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _node_to_md(node, lines: list[str]):
    """DOM 을 순회하며 마크다운 라인으로 변환."""
    if isinstance(node, NavigableString):
        txt = _clean(str(node))
        if txt:
            lines.append(txt)
        return
    if not isinstance(node, Tag):
        return

    name = node.name.lower()
    if name in ("script", "style"):
        return
    if name == "table":
        md = _table_to_md(node)
        if md:
            lines.append("")
            lines.append(md)
            lines.append("")
        return
    if re.fullmatch(r"h[1-6]", name):
        level = int(name[1])
        lines.append("")
        lines.append("#" * min(level + 1, 6) + " " + _clean(node.get_text(" ", strip=True)))
        lines.append("")
        return
    if name == "li":
        lines.append("- " + _clean(node.get_text(" ", strip=True)))
        return
    if name == "br":
        lines.append("")
        return

    # 컨테이너: 자식 순회 (단, 리스트/표는 위에서 통째로 처리)
    if name in ("ul", "ol"):
        for li in node.find_all("li", recursive=False):
            _node_to_md(li, lines)
        lines.append("")
        return

    if name in ("p", "div"):
        # 내부에 블록 자식이 있으면 재귀, 없으면 텍스트 한 줄
        if node.find(["p", "div", "ul", "ol", "table", "li"], recursive=False):
            for child in node.children:
                _node_to_md(child, lines)
        else:
            txt = _clean(node.get_text(" ", strip=True))
            if txt:
                lines.append(txt)
                lines.append("")
        return

    # 기타 인라인 태그
    for child in node.children:
        _node_to_md(child, lines)


def extract_markdown(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#contentsEditHtml")
    if container is None:
        # 폴백: CMS 콘텐츠 블록(_obj)들을 모음
        objs = soup.select("div._obj")
        if objs:
            container = soup.new_tag("div")
            for o in objs:
                container.append(o)
    if container is None:
        container = soup.body or soup

    lines: list[str] = []
    _node_to_md(container, lines)

    # CMS 내부 템플릿 찌꺼기 라인 제거 (예: /WEB-INF/.../layout.jsp, 템플릿 ID 토큰)
    def _is_junk(ln: str) -> bool:
        s = ln.strip()
        if not s:
            return False
        if ".jsp" in s or "WEB-INF" in s:
            return True
        # 단독 템플릿 ID 토큰(kor_JW_MS_K2WT001_S, ESG_left 등)
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,}(\s+[A-Za-z][A-Za-z0-9_]{2,})?", s):
            return True
        # 게시글(artclView) 잡동사니
        if "SITE_MENU_FNCT" in s or s.startswith("fnctId="):
            return True
        if s.startswith(("글번호 ", "첨부파일 ", "이전글 ", "다음글 ")):
            return True
        if s.startswith("수정일 ") and ("작성자" in s or "조회수" in s):
            return True
        return False

    lines = [ln for ln in lines if not _is_junk(ln)]

    # 빈 줄 정리
    md = "\n".join(lines)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


# ---------------- 실행 ----------------


def crawl(dry: bool = False):
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    session = make_session()
    manifest = []

    for src in SOURCES:
        try:
            r = session.get(src["url"], timeout=30)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            md = extract_markdown(r.text)
        except Exception as e:
            print(f"[실패] {src['name']}: {e}")
            continue

        kor = len(re.findall(r"[가-힣]", md))
        title = f"# {src['name']}\n\n> 출처: {src['url']}\n> 카테고리: {src['category_l1']}/{src['category_l2']}\n"
        body = title + "\n" + md + "\n"

        print(f"[OK] {src['name']:22} {len(md):5}자(한글 {kor}) ← {src['url']}")
        if dry:
            print("     " + md[:180].replace("\n", " ") + " ...\n")
            continue

        (OUT_DIR / f"{src['name']}.md").write_text(body, encoding="utf-8")
        manifest.append(
            {
                "source": src["name"],
                "url": src["url"],
                "category_l1": src["category_l1"],
                "category_l2": src["category_l2"],
                "chars": len(md),
            }
        )
        time.sleep(0.7)  # 예의상 지연

    if not dry and manifest:
        existing = {}
        if MANIFEST.exists():
            for m in json.loads(MANIFEST.read_text(encoding="utf-8")):
                existing[m["source"]] = m
        for m in manifest:
            existing[m["source"]] = m
        MANIFEST.write_text(
            json.dumps(list(existing.values()), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"\n✅ {len(manifest)}건 저장 → output/parsed/, manifest 갱신")


def download_pdfs():
    session = make_session()
    pdf_dir = ROOT / "data_pipeline" / "downloads"
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for p in PDFS:
        try:
            r = session.get(p["url"], timeout=60)
            r.raise_for_status()
            path = pdf_dir / f"{p['name']}.pdf"
            path.write_bytes(r.content)
            print(f"[PDF] {p['name']} ({len(r.content):,} bytes) → {path}")
            print(f'      다음: python data_pipeline/parse_pdf.py "{path}"')
        except Exception as e:
            print(f"[PDF 실패] {p['name']}: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="저장 없이 미리보기")
    ap.add_argument("--pdf", action="store_true", help="학사일정 등 PDF 다운로드")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    if args.pdf:
        download_pdfs()
    else:
        crawl(dry=args.dry)

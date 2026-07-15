"""
Stage 1: Upstage Document Parse
이미지 기반 PDF(ibook 렌더링)를 OCR 파싱하여 마크다운/HTML/요소 단위 JSON으로 저장한다.

사용법:
    python parse_pdf.py "2026년 전공교육과정.pdf"

출력:
    output/parsed/<name>.raw.json       # Document Parse 원본 응답
    output/parsed/<name>.md             # 전체 마크다운 (RAG 청킹용)
    output/parsed/<name>.elements.json  # 요소 단위(페이지/카테고리 포함) 정형화 소스
"""

import json
import os
import pathlib
import sys

import requests
from dotenv import load_dotenv

# 프로젝트 루트의 .env 로드
ROOT = pathlib.Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

API_KEY = os.getenv("UPSTAGE_API_KEY")
# 현행 통합 엔드포인트. 구버전(document-ai/document-parse) 실패 시 fallback.
ENDPOINTS = [
    "https://api.upstage.ai/v1/document-digitization",
    "https://api.upstage.ai/v1/document-ai/document-parse",
]

OUT_DIR = ROOT / "output" / "parsed"


def parse(pdf_path: pathlib.Path) -> dict:
    if not API_KEY:
        sys.exit("UPSTAGE_API_KEY 가 .env 에 없습니다.")

    headers = {"Authorization": f"Bearer {API_KEY}"}
    data = {
        "model": "document-parse",
        "ocr": "force",  # 이미지 기반이므로 OCR 강제
        "coordinates": "true",
        "output_formats": "['markdown', 'html', 'text']",
        "base64_encoding": "['table']",  # 표는 base64 이미지도 함께 받아 검수에 활용
    }

    last_err = None
    for url in ENDPOINTS:
        with open(pdf_path, "rb") as f:
            files = {"document": (pdf_path.name, f, "application/pdf")}
            print(f"[요청] {url}")
            resp = requests.post(url, headers=headers, data=data, files=files, timeout=300)
        if resp.status_code == 200:
            print(f"[성공] {url}")
            return resp.json()
        last_err = f"{resp.status_code} {resp.text[:300]}"
        print(f"[실패] {url} -> {last_err}")
    sys.exit(f"모든 엔드포인트 실패. 마지막 오류: {last_err}")


def save(result: dict, name: str):
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # 1) 원본 응답
    (OUT_DIR / f"{name}.raw.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 2) 전체 마크다운 (RAG용)
    content = result.get("content", {})
    md = content.get("markdown") or content.get("text") or ""
    (OUT_DIR / f"{name}.md").write_text(md, encoding="utf-8")

    # 3) 요소 단위 (페이지/카테고리) - 정형화 및 페이지 분기용
    elements = result.get("elements", [])
    slim = [
        {
            "id": e.get("id"),
            "page": e.get("page"),
            "category": e.get("category"),
            "text": (e.get("content") or {}).get("text", ""),
            "markdown": (e.get("content") or {}).get("markdown", ""),
            "html": (e.get("content") or {}).get("html", ""),
        }
        for e in elements
    ]
    (OUT_DIR / f"{name}.elements.json").write_text(
        json.dumps(slim, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 요약 출력
    from collections import Counter

    by_page = Counter(e["page"] for e in slim)
    by_cat = Counter(e["category"] for e in slim)
    print(f"\n[저장 완료] output/parsed/{name}.*")
    print(f"  요소 수: {len(slim)}")
    print(f"  페이지별: {dict(sorted(by_page.items()))}")
    print(f"  카테고리별: {dict(by_cat)}")
    print(f"  마크다운 길이: {len(md):,} chars")


if __name__ == "__main__":
    pdf = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "2026년 전공교육과정.pdf"
    if not pdf.is_absolute():
        pdf = ROOT / pdf
    if not pdf.exists():
        sys.exit(f"파일 없음: {pdf}")
    print(f"[파싱 대상] {pdf.name}")
    result = parse(pdf)
    save(result, pdf.stem)

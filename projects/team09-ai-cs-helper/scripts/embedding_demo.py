"""임베딩 검증용 콘솔 데모.

supabase에 문장을 저장하거나, 검색어와 유사한 문서를 찾는다.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv

from app.clients.embedding import embed
from app.clients.http import post_json
from app.clients.supabase import (
    documents_table,
    supabase_headers,
    supabase_url,
    vector_literal,
)
from app.rag.search import search


def add_document() -> None:
    text = input("저장할 문장> ").strip()
    if not text:
        print("입력된 문장이 없습니다.")
        return

    row = {
        "content": text,
        "metadata": {"source": "console"},
        "embedding": vector_literal(embed(text, "passage")),
    }
    post_json(
        supabase_url(documents_table()),
        supabase_headers({"Prefer": "return=minimal"}),
        row,
    )
    print("저장 완료")


def search_documents() -> None:
    text = input("검색할 문장> ").strip()
    if not text:
        print("입력된 문장이 없습니다.")
        return

    results = search(text, top_k=3)
    for rank, (score, doc) in enumerate(results, start=1):
        print(f"\n#{rank} score={score:.4f} id={doc['id']}")
        print(doc["content"])

    if not results:
        print("검색할 문서가 없습니다.")


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description="Console embedding demo")
    parser.add_argument("command", choices=["add", "search"], help="add or search")
    args = parser.parse_args()

    try:
        if args.command == "add":
            add_document()
        else:
            search_documents()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

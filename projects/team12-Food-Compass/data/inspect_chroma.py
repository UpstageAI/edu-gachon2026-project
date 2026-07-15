"""ChromaDB에 저장된 문서를 직접 눈으로 확인하는 조회 스크립트.

사용 예:
  # 전체 요약 + food_knowledge 전체 문서
  .venv/bin/python data/inspect_chroma.py

  # 특정 품목만 보기(부분일치)
  .venv/bin/python data/inspect_chroma.py 상추
  .venv/bin/python data/inspect_chroma.py 고등어

  # 대체품/가공식품 매칭용 컬렉션(all_food_products)까지 함께 보기
  .venv/bin/python data/inspect_chroma.py --all

서버(컨테이너)에서도 동일하게:
  docker compose -f docker-compose.prod.yml exec api .venv/bin/python data/inspect_chroma.py 상추
"""
from __future__ import annotations

import sys
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

_HERE = Path(__file__).resolve().parent
CHROMA_DB_PATH = str(_HERE / "chroma_db")
KNOWLEDGE_COLLECTION = "food_knowledge"
MAIN_COLLECTION = "all_food_products"

EMBEDDING_MODEL_NAME = "jhgan/ko-sroberta-multitask"
_embed = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL_NAME)


def _print_knowledge(client: chromadb.ClientAPI, keyword: str | None) -> None:
    try:
        coll = client.get_collection(KNOWLEDGE_COLLECTION, embedding_function=_embed)
    except Exception as e:
        print(f"[{KNOWLEDGE_COLLECTION}] 컬렉션을 찾을 수 없음: {e!r}")
        print("  → data/insertion_knowledge_rag.py를 먼저 실행해 적재하세요.")
        return

    got = coll.get(include=["documents", "metadatas"])
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []

    # 품목별로 묶어서 보기 좋게 출력
    by_item: dict[str, list[tuple[str, str]]] = {}
    for doc, meta in zip(docs, metas, strict=True):
        item = meta.get("item_name", "(품목명 없음)")
        by_item.setdefault(item, []).append((meta.get("content_type", "?"), doc))

    items = sorted(by_item)
    if keyword:
        items = [it for it in items if keyword in it]

    print(f"\n===== [{KNOWLEDGE_COLLECTION}] 총 {coll.count()}개 문서 / 품목 {len(by_item)}종 =====")
    if keyword:
        print(f"(필터: '{keyword}' 포함 품목 {len(items)}종)\n")
    for item in items:
        print(f"■ {item}")
        for content_type, doc in by_item[item]:
            print(f"   [{content_type}] {doc}")
        print()


def _print_main_summary(client: chromadb.ClientAPI, keyword: str | None) -> None:
    try:
        coll = client.get_collection(MAIN_COLLECTION, embedding_function=_embed)
    except Exception as e:
        print(f"[{MAIN_COLLECTION}] 컬렉션을 찾을 수 없음: {e!r}")
        return

    got = coll.get(include=["documents", "metadatas"])
    docs = got.get("documents") or []
    metas = got.get("metadatas") or []
    print(f"\n===== [{MAIN_COLLECTION}] 총 {coll.count()}개 문서(대체품/가공식품 매칭용) =====")
    shown = 0
    for doc, meta in zip(docs, metas, strict=True):
        name = (meta or {}).get("name", "")
        source = (meta or {}).get("source", "")
        category = (meta or {}).get("category", "")
        line = f"  - {doc}" + (f"  (name={name}, source={source}, category={category})" if meta else "  (metadata 없음)")
        if keyword and keyword not in doc and keyword not in name:
            continue
        print(line)
        shown += 1
        if not keyword and shown >= 20:
            print(f"  ... (상위 20개만 표시, 전체 {coll.count()}개)")
            break


def main() -> None:
    args = [a for a in sys.argv[1:]]
    show_all = "--all" in args
    keyword = next((a for a in args if not a.startswith("--")), None)

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
    print(f"ChromaDB 경로: {CHROMA_DB_PATH}")
    print("컬렉션 목록:", [c.name for c in client.list_collections()])

    _print_knowledge(client, keyword)
    if show_all:
        _print_main_summary(client, keyword)


if __name__ == "__main__":
    main()

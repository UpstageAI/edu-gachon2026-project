"""제철·보관법 등 지식 RAG 문서를 ChromaDB의 food_knowledge 컬렉션에 적재하는 스크립트.

data/rag_docs/seasonal_knowledge.json(직접 작성한 원본 문서)을 읽어, 품목 x 문서유형
(제철정보/보관법)마다 한 문서씩 임베딩해 저장한다. search_knowledge_node가 이 컬렉션을
검색해 "LLM 자체 지식"이 아니라 "여기 저장된 문서 내용"만 근거로 답변하도록 하는 게 목적.

- 임베딩 대상(document): 각 문서의 실제 지식 문장(질문과 의미적으로 매칭돼야 하므로).
- 메타데이터: item_name / category / season_months / content_type / source
  (CLAUDE.md §10 RAG 메타데이터 스키마).
- all_food_products(품목명·설명 임베딩, 대체품/가공식품 매칭용)는 건드리지 않고
  food_knowledge만 생성/교체하므로 반복 실행해도 안전.

실행: `.venv/bin/python data/insertion_knowledge_rag.py`
"""
from __future__ import annotations

import json
from pathlib import Path

import chromadb
from chromadb.utils import embedding_functions

_HERE = Path(__file__).resolve().parent
CHROMA_DB_PATH = str(_HERE / "chroma_db")
KNOWLEDGE_COLLECTION_NAME = "food_knowledge"
SOURCE_JSON = _HERE / "rag_docs" / "seasonal_knowledge.json"

# app/tools/vector_store.py와 동일한 임베딩 모델을 써야 검색 결과가 일치함
EMBEDDING_MODEL_NAME = "jhgan/ko-sroberta-multitask"
korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME
)


def _load_documents() -> list[dict]:
    """JSON 원본을 (품목 x 문서유형) 단위 문서 리스트로 평탄화."""
    raw = json.loads(SOURCE_JSON.read_text(encoding="utf-8"))
    documents = []
    for entry in raw:
        item_name = entry["item_name"]
        category = entry["category"]
        season_months = entry["season_months"]
        for content_type, text in entry["docs"].items():
            documents.append(
                {
                    "id": f"knowledge_{item_name}_{content_type}",
                    "document": text,
                    "metadata": {
                        "item_name": item_name,
                        "category": category,
                        "season_months": season_months,
                        "content_type": content_type,
                        "source": "rag_knowledge",
                    },
                }
            )
    return documents


def main() -> None:
    documents = _load_documents()
    print(f"원본 문서 {len(documents)}건 로드 완료 (품목 x 문서유형)")

    client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

    # 반복 실행 시 중복을 막기 위해 기존 컬렉션을 지우고 새로 만든다(다른 컬렉션은 그대로 둠).
    # [2026-07-15 코드리뷰 반영] "컬렉션 없음"일 때만 삭제를 건너뛰고, 실제 삭제 실패
    # (DB/권한/파일락 등)는 그대로 예외로 터지게 함.
    if KNOWLEDGE_COLLECTION_NAME in {c.name for c in client.list_collections()}:
        client.delete_collection(KNOWLEDGE_COLLECTION_NAME)
        print(f"기존 '{KNOWLEDGE_COLLECTION_NAME}' 컬렉션 삭제")

    collection = client.get_or_create_collection(
        name=KNOWLEDGE_COLLECTION_NAME,
        embedding_function=korean_embedding_fn,
    )
    collection.add(
        documents=[d["document"] for d in documents],
        ids=[d["id"] for d in documents],
        metadatas=[d["metadata"] for d in documents],
    )
    print(f"'{KNOWLEDGE_COLLECTION_NAME}'에 {collection.count()}개 문서 저장 완료")


if __name__ == "__main__":
    main()

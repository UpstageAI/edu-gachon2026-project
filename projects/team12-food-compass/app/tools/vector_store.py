"""ChromaDB 임베딩 모델 및 컬렉션 싱글톤 관리.

임베딩 모델은 모듈 로드 시 즉시 초기화(서버 프로세스당 1회).
Chroma 클라이언트/컬렉션은 최초 요청 시점에 지연 초기화 후 캐싱.
"""
from __future__ import annotations

import os

import chromadb
from chromadb.utils import embedding_functions

CHROMA_DB_PATH = "./data/chroma_db"
COLLECTION_NAME = "all_food_products"
# [2026-07-15 추가] 제철정보·보관법 등 지식 RAG 문서 전용 컬렉션 — 품목명/설명 임베딩
# (all_food_products, 대체품·가공식품 매칭용)과 성격이 완전히 달라서(질문에 대한 근거
# 문단을 검색·인용) 분리. all_food_products의 대체품 검색(where source=kamis)과 섞이지
# 않도록 별도 컬렉션으로 관리.
KNOWLEDGE_COLLECTION_NAME = "food_knowledge"
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "jhgan/ko-sroberta-multitask")

korean_embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
    model_name=EMBEDDING_MODEL_NAME
)
_collection = None
_knowledge_collection = None


def get_collection():
    """Chroma 컬렉션을 최초 호출 시 1회 생성 후 캐싱해서 반환."""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _collection = client.get_collection(
            COLLECTION_NAME,
            embedding_function=korean_embedding_fn,
        )
    return _collection


def get_knowledge_collection():
    """지식 RAG 문서(food_knowledge) 컬렉션을 최초 호출 시 1회 생성 후 캐싱해서 반환.

    아직 문서를 적재하지 않은 환경(insertion_knowledge_rag.py 미실행)에서는 컬렉션이
    없어 chromadb가 예외를 던짐 — 호출부(search_knowledge_node)에서 잡아 "정보 없음"으로
    안전하게 처리하도록 여기서는 그대로 올린다.
    """
    global _knowledge_collection
    if _knowledge_collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DB_PATH)
        _knowledge_collection = client.get_collection(
            KNOWLEDGE_COLLECTION_NAME,
            embedding_function=korean_embedding_fn,
        )
    return _knowledge_collection



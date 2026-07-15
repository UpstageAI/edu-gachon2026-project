import sys

from app.rag.vector_store import backfill_categories, ingest_city


def main():
    print("=== 1. 서울 이어서 수집 ===", flush=True)
    saved = ingest_city("서울")
    print(f"서울 수집 완료: {len(saved)}건 신규 저장", flush=True)

    print("\n=== 2. 카테고리 백필 ===", flush=True)
    result = backfill_categories()
    print(f"백필 완료: {result}", flush=True)


if __name__ == "__main__":
    main()

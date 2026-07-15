"""top-k 검색 단독 확인 스크립트 (파트B — 실데이터 기준).

data/test_questions.json의 normal + no_result 질문으로 law_qa 컬렉션을
top-3 검색해 질문별 매칭 문서(id/분류/distance)를 출력하고,
검색 부족 판정 임계값 제안의 근거가 되는 스코어 분포 요약을 낸다.

관련/무관 판정: 실데이터 id는 전부 law_* 형식이므로 접두어 대신
질문별 기대 category(EXPECTED_CATEGORY)와 문서 metadata의 category를 비교한다.

거리 공간은 cosine distance(0에 가까울수록 유사, ingest_chroma.py에서 설정).

실행: python scripts/check_search.py  (사전 조건: scripts/ingest_chroma.py 적재 완료)
"""

import json
import sys
from pathlib import Path

import chromadb
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402

QUESTIONS_PATH = PROJECT_ROOT / "data" / "test_questions.json"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "law_qa"
EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
EMBEDDING_MODEL = "embedding-query"  # 검색 질의용 모델 (적재는 embedding-passage)
TOP_K = 3

# normal 질문별 기대 category (관련/무관 스코어 분리 기준)
EXPECTED_CATEGORY = {
    "월세 계약 전에 뭘 확인해야 하나요?": "부동산/임대차",
    "전세사기를 당했는데 어떤 지원을 받을 수 있나요?": "부동산/임대차",
    "공공임대주택에 입주하려면 어떤 자격이 필요한가요?": "부동산/임대차",
    "아파트를 분양받으려면 어떤 절차를 거쳐야 하나요?": "부동산/임대차",
    "이사하다가 이사업체와 분쟁이 생기면 어떻게 하나요?": "부동산/임대차",
    "기초생활수급자가 되려면 어떤 조건이 필요한가요?": "복지",
    "혼자 사는 청년인데 1인가구가 받을 수 있는 지원이 있나요?": "복지",
    "거동이 불편한 노인이 집에서 받을 수 있는 돌봄 서비스가 있나요?": "복지",
    "노인학대를 목격하면 어디에 신고해야 하나요?": "복지",
    "치매에 걸린 부모님을 위해 이용할 수 있는 제도가 뭐가 있나요?": "복지",
}


def embed_query(text: str) -> list[float]:
    response = requests.post(
        EMBEDDING_URL,
        headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
        json={"model": EMBEDDING_MODEL, "input": text},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()["data"][0]["embedding"]


def search(collection, question: str) -> list[tuple[str, str, str, float]]:
    """(id, category, subcategory, distance) 리스트를 distance 오름차순으로 반환."""
    result = collection.query(
        query_embeddings=[embed_query(question)],
        n_results=TOP_K,
        include=["metadatas", "distances"],
    )
    return [
        (m["id"], m["category"], m.get("subcategory", ""), d)
        for m, d in zip(result["metadatas"][0], result["distances"][0])
    ]


def main() -> None:
    if not settings.upstage_api_key:
        raise SystemExit("UPSTAGE_API_KEY가 비어 있습니다. .env 설정 후 다시 실행하세요.")

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as exc:
        raise SystemExit(f"law_qa 컬렉션이 없습니다. scripts/ingest_chroma.py를 먼저 실행하세요. ({exc})")

    questions = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))

    relevant_best: list[float] = []  # normal 질문에서 기대 category 문서의 최고(최소) distance
    hit_count = 0
    for question in questions["normal"]:
        matches = search(collection, question)
        print(f"\n[normal] {question}")
        for doc_id, category, subcategory, distance in matches:
            print(f"  {doc_id} [{category}/{subcategory}]: {distance:.4f}")
        expected = EXPECTED_CATEGORY.get(question)
        related = [d for _, category, _, d in matches if category == expected]
        if related:
            hit_count += 1
            relevant_best.append(min(related))
        else:
            print("  !! 기대 category 문서가 top-3에 없음")

    irrelevant_best: list[float] = []  # no_result 질문에서 가장 가까운 문서의 distance
    for question in questions["no_result"]:
        matches = search(collection, question)
        print(f"\n[no_result] {question}")
        for doc_id, category, subcategory, distance in matches:
            print(f"  {doc_id} [{category}/{subcategory}]: {distance:.4f}")
        irrelevant_best.append(min(d for _, _, _, d in matches))

    total = len(questions["normal"])
    print("\n===== 요약 =====")
    print(f"normal 질문 top-3 적중률: {hit_count}/{total}")
    if relevant_best:
        print(f"관련 매칭 distance 범위: {min(relevant_best):.4f} ~ {max(relevant_best):.4f}")
    if irrelevant_best:
        print(f"무관 질문 최근접 distance 범위: {min(irrelevant_best):.4f} ~ {max(irrelevant_best):.4f}")
    print("※ 임계값은 위 두 분포 사이에서 제안하고 승인 후 확정한다.")


if __name__ == "__main__":
    main()

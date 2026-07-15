"""data/raw/*.csv (법제처 백문백답 실데이터)를 ChromaDB에 적재하는 스크립트.

[데이터 추가 반영 절차]
1. data/raw/baekmun_3categories.csv 를 열어 마지막 행 아래에 새 행을 이어붙인다
   (9컬럼 구조 유지, 백문일련번호는 기존과 겹치지 않게, UTF-8로 저장)
2. python scripts/ingest_chroma.py 재실행
3. "N건 적재 완료"의 N이 추가분만큼 늘었는지 확인
끝. 코드 수정 불필요. 새 CSV 파일을 data/raw/에 추가하는 것도 동일하게 지원한다.
(id 중복·필수 필드 누락은 이 스크립트가 검사해 명확히 실패시킨다)

- 입력: data/raw/ 아래 모든 *.csv (utf-8-sig, 9컬럼, 답변은 멀티라인 허용)
- 임베딩: Upstage embedding-passage, 텍스트 = 질문 + "\n" + 답변, 32건 배치 호출
- 저장: chromadb.PersistentClient("chroma_db/"), 컬렉션 law_qa, cosine distance
- metadata: id, category, question, subcategory, source_url (5개 키, ASCII)
- 재실행 멱등: 기존 컬렉션 삭제 후 재생성이므로 중복 적재가 없다.

실행: python scripts/ingest_chroma.py  (사전 조건: .env에 UPSTAGE_API_KEY)
"""

import csv
import sys
from pathlib import Path

import chromadb
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import settings  # noqa: E402

RAW_DIR = PROJECT_ROOT / "data" / "raw"
CHROMA_PATH = PROJECT_ROOT / "chroma_db"
COLLECTION_NAME = "law_qa"
EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
EMBEDDING_MODEL = "embedding-passage"  # 문서 적재용. 검색 질의는 embedding-query 사용
EMBEDDING_BATCH_SIZE = 32  # 긴 답변 다수를 한 요청에 보내면 요청 크기 한도 초과 위험

REQUIRED_COLUMNS = ("백문일련번호", "질문", "답변", "원문링크")
METADATA_KEYS = ("id", "category", "question", "subcategory", "source_url")


def clean_answer(text: str) -> str:
    """전처리 안전망: "테이블 단락" 문자열을 제거한다.

    현재 CSV는 0건이지만(사람이 사전 제거) 추후 추가분 대비로 유지한다.
    ◇ ☞ √ 기호와 줄바꿈은 원문 구조이므로 보존한다.
    """
    return text.replace("테이블 단락", "").strip()


def normalize_row(row: dict) -> dict:
    """CSV 한 행(9컬럼 dict)을 적재용 문서 dict로 정규화한다."""
    return {
        "id": f"law_{row['백문일련번호'].strip()}",
        "category": row["대분류명"].strip(),  # 팀 확정: 원문 그대로 ("복지", "부동산/임대차")
        "question": row["질문"].strip(),
        "answer": clean_answer(row["답변"]),
        "subcategory": row["소분류명"].strip(),
        "source_url": row["원문링크"].strip(),
    }


def load_rows() -> list[dict]:
    """data/raw/의 모든 CSV를 읽어 정규화 문서 리스트로 반환한다.

    행 수를 가정하지 않는다. id 중복·필수 필드 빈 값 발견 시 위치를 알리고 SystemExit.
    """
    csv_paths = sorted(RAW_DIR.glob("*.csv"))
    if not csv_paths:
        raise SystemExit(f"{RAW_DIR} 에 CSV 파일이 없습니다.")

    items: list[dict] = []
    seen_ids: dict[str, str] = {}
    for path in csv_paths:
        with path.open(encoding="utf-8-sig", newline="") as f:
            for record_no, row in enumerate(csv.DictReader(f), start=1):
                missing = [col for col in REQUIRED_COLUMNS if not (row.get(col) or "").strip()]
                if missing:
                    raise SystemExit(
                        f"{path.name} {record_no}번째 데이터 행: 필수 필드가 비어 있음 {missing}"
                    )
                item = normalize_row(row)
                if item["id"] in seen_ids:
                    raise SystemExit(
                        f"id 중복: {item['id']} ({seen_ids[item['id']]} ↔ {path.name})"
                    )
                seen_ids[item["id"]] = path.name
                items.append(item)
    return items


def build_documents(items: list[dict]) -> tuple[list[str], list[str], list[dict]]:
    """문서 리스트를 ChromaDB 적재 형식(ids, documents, metadatas)으로 변환한다."""
    ids = [item["id"] for item in items]
    documents = [f"{item['question']}\n{item['answer']}" for item in items]
    metadatas = [{key: item[key] for key in METADATA_KEYS} for item in items]
    return ids, documents, metadatas


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Upstage Embedding API로 벡터화한다. 32건 배치, 배치 내 index 정렬로 순서 보장."""
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
        batch = texts[start : start + EMBEDDING_BATCH_SIZE]
        response = requests.post(
            EMBEDDING_URL,
            headers={"Authorization": f"Bearer {settings.upstage_api_key}"},
            json={"model": EMBEDDING_MODEL, "input": batch},
            timeout=120,
        )
        response.raise_for_status()
        data = sorted(response.json()["data"], key=lambda entry: entry["index"])
        embeddings.extend(entry["embedding"] for entry in data)
    return embeddings


def main() -> None:
    if not settings.upstage_api_key:
        raise SystemExit("UPSTAGE_API_KEY가 비어 있습니다. .env 설정 후 다시 실행하세요.")

    items = load_rows()
    ids, documents, metadatas = build_documents(items)
    embeddings = embed_texts(documents)

    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:  # 컬렉션이 아직 없는 첫 실행이면 그대로 진행
        pass
    collection = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})
    collection.add(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
    print(f"{collection.count()}건 적재 완료")


if __name__ == "__main__":
    main()

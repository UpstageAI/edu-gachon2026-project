"""
Step 2. disaster_guidelines 전처리 + 임베딩 + 적재
입력: raw_data/disaster_guidelines_raw.json (fetch_all.py 결과)

처리 순서:
1. 카테고리(대분류>중분류>소분류) + 본문(actRmks)을 하나의 텍스트로 결합
   -> 임베딩 시 카테고리 맥락이 같이 들어가야 검색 품질이 좋아짐
   (예: "자연재난 > 호우 > 발생시에는: 하천변 접근을 금지하세요")
2. Solar Embedding API(solar-embedding-1-large-passage)로 임베딩
3. Supabase disaster_guidelines 테이블에 직접 INSERT (pgvector 타입 처리 위해
   pandas.to_sql 대신 psycopg2 직접 사용)

실행: python preprocessors/process_disaster_guidelines.py <source_dataset_label>
예:   python preprocessors/process_disaster_guidelines.py 사회재난
"""
import json
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

DEFAULT_RAW_PATH = "raw_data/disaster_guidelines_raw.json"
DATABASE_URL = os.getenv("DATABASE_URL")
UPSTAGE_API_KEY = os.getenv("UPSTAGE_API_KEY")

EMBEDDING_URL = "https://api.upstage.ai/v1/solar/embeddings"
EMBEDDING_MODEL = "solar-embedding-1-large-passage"
BATCH_SIZE = 100  # Solar API 배치 제한 확인 전이라 안전하게 100으로 설정


def build_combined_text(item: dict) -> str:
    """카테고리 맥락 + 본문을 하나의 텍스트로 결합 (임베딩 검색 품질 향상용)"""
    parts = [
        item.get("safety_cate_nm1"),
        item.get("safety_cate_nm2"),
        item.get("safety_cate_nm3"),
    ]
    breadcrumb = " > ".join(p for p in parts if p)
    content = item.get("actRmks") or ""
    if breadcrumb:
        return f"[{breadcrumb}] {content}".strip()
    return content


def get_embeddings(texts: list) -> list:
    """Solar Embedding API 호출 (배치 처리)"""
    if not UPSTAGE_API_KEY:
        raise RuntimeError("UPSTAGE_API_KEY가 .env에 설정되지 않았습니다.")

    headers = {
        "Authorization": f"Bearer {UPSTAGE_API_KEY}",
        "Content-Type": "application/json",
    }

    all_embeddings = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        resp = requests.post(
            EMBEDDING_URL,
            headers=headers,
            json={"input": batch, "model": EMBEDDING_MODEL},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        all_embeddings.extend(embeddings)
        print(f"  임베딩 배치 {i // BATCH_SIZE + 1}: {len(batch)}건 완료")

    return all_embeddings


def process(source_dataset_label: str, raw_path: str = DEFAULT_RAW_PATH):
    if not os.path.exists(raw_path):
        print(f"[ERROR] {raw_path} 없음. 먼저 fetch_all.py로 수집해야 합니다.")
        sys.exit(1)

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)

    print(f"원본 {len(raw_items)}건 로드 (source_dataset={source_dataset_label})")

    combined_texts = [build_combined_text(item) for item in raw_items]

    print("Solar Embedding API 호출 중...")
    embeddings = get_embeddings(combined_texts)
    print(f"임베딩 완료: {len(embeddings)}건, 차원: {len(embeddings[0])}")

    if not DATABASE_URL:
        print("[ERROR] DATABASE_URL이 .env에 없습니다.")
        sys.exit(1)

    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()

    insert_sql = """
        INSERT INTO disaster_guidelines
        (content, contents_url, safety_cate1, safety_cate2, safety_cate3, safety_cate4,
         safety_cate_nm1, safety_cate_nm2, safety_cate_nm3, source_dataset, embedding)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """

    inserted = 0
    for item, embedding, combined_text in zip(raw_items, embeddings, combined_texts):
        # pgvector는 '[0.1,0.2,...]' 형태의 문자열로 넣으면 자동 캐스팅됨
        embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
        # content는 combined_text 사용 (actRmks가 null인 이미지 자료 케이스가 있어서
        # 카테고리 breadcrumb가 항상 포함된 combined_text를 써야 NOT NULL 제약을 안전하게 통과함)
        cur.execute(insert_sql, (
            combined_text,
            item.get("contentsUrl"),
            item.get("safety_cate1"),
            item.get("safety_cate2"),
            item.get("safety_cate3"),
            item.get("safety_cate4"),
            item.get("safety_cate_nm1"),
            item.get("safety_cate_nm2"),
            item.get("safety_cate_nm3"),
            source_dataset_label,
            embedding_str,
        ))
        inserted += 1

    conn.commit()
    cur.close()
    conn.close()

    print(f"\n적재 완료: {inserted}건 -> disaster_guidelines 테이블")


if __name__ == "__main__":
    label = sys.argv[1] if len(sys.argv) > 1 else "사회재난"
    raw_path_arg = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_RAW_PATH
    process(label, raw_path_arg)
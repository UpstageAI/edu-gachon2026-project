# data/ — ChromaDB 데이터·적재/조회 스크립트

## 폴더/파일

| 항목 | 역할 |
|---|---|
| `chroma_db/` | ChromaDB 영속 데이터(임베딩 저장소). **gitignore 대상** — 서버에서는 docker 볼륨으로 마운트됨 |
| `rag_docs/seasonal_knowledge.json` | 지식 RAG 원본 문서(직접 작성) — KAMIS 전 품목을 커버하는 70품목 × (제철정보+보관법) = 140개 문서. 내용 수정은 이 파일에서 |
| `build_substitute_collection.py` | **대체품 컬렉션(`all_food_products`) 재구축** — Supabase price_snapshot 기준 KAMIS 75품목 + 부류(category) 메타데이터. 같은 부류 안에서만 대체품이 검색되게 하는 기반 |
| `insertion_knowledge_rag.py` | **지식 컬렉션(`food_knowledge`) 적재** — rag_docs JSON을 임베딩해 저장 |
| `inspect_chroma.py` | 저장된 문서를 사람이 읽기 좋게 조회 — `python data/inspect_chroma.py [품목]` / `--all` |
| `sql/init.sql` | Supabase 테이블 스키마(price_snapshot, price_gokr_*, price_cache 등) + RLS 정책. 반복 실행 안전(idempotent) |

## 컬렉션 갱신 절차 (서버)

세 스크립트는 Docker 이미지에 포함돼 있어 서버 컨테이너 안에서 바로 실행합니다:

```bash
# 1) rag_docs JSON 수정 후 커밋/push → CD 배포
# 2) 컨테이너 안에서 적재
docker compose -f docker-compose.prod.yml exec api .venv/bin/python data/build_substitute_collection.py
docker compose -f docker-compose.prod.yml exec api .venv/bin/python data/insertion_knowledge_rag.py
# 3) 컬렉션 캐시 갱신
docker compose -f docker-compose.prod.yml restart api
```

결과는 볼륨 마운트된 `data/chroma_db`에 기록되어 재시작해도 유지됩니다.

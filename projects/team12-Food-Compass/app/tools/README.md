# app/tools/ — 그래프 노드가 사용하는 도구 함수

외부 API·DB·ChromaDB 접근과 도메인 로직(판정, 단위환산 등)이 모여 있습니다.

## KAMIS (농축수산물 원물 시세)

| 파일 | 역할 |
|---|---|
| `kamis_client.py` | KAMIS Open-API 실 호출 클라이언트(legacy SSL 컨텍스트 포함) — 일일 수집 스크립트가 사용 |
| `price_snapshot.py` | Supabase `price_snapshot` 테이블 저장/조회. `search_similar_item_names`(ILIKE 부분일치 폴백 — "고추"→건고추/붉은고추/풋고추) 포함 |
| `kamis.py` | `get_raw_price_node` — 시세 조회 노드. 축산물 이름 정규화(돼지고기→돼지), 부위별 나열(소/돼지/닭), 등급 선택(중품 우선, 소는 1등급), 당일가 결측 시 과거값 폴백 |
| `judge.py` | `judge_price` / `judge_price_node` — 1주일전 vs 1개월전 대비 비쌈/적정/쌈 판정 + 단위 정규화 |
| `normalize.py` | 단위 환산 — `normalize_price_unit`(kg↔g↔사용자 단위), `rice_price_per_bowl`(쌀 → 밥 1공기 환산, 시나리오 1용) |

## 참가격/data.go.kr (가공식품 소매가)

| 파일 | 역할 |
|---|---|
| `price_gokr_client.py` | 참가격(price.go.kr) API 실 호출 — 일일 수집 스크립트가 사용 |
| `price_gokr_snapshot.py` | Supabase `price_gokr_*` 테이블 저장/조회. `search_processed_items`(ILIKE 상품 검색), `get_processed_price`(평균가), `save_store_regions`(매장 8권역 분류) |
| `region.py` | 주소 문자열 → 8개 권역(서울/경기도/강원도/인천/전라도/경상도/충청도/제주도) 분류 (순수 로직, DB 접근 없음) |
| `item_alias.py` | 사용자 표현 → 참가격 실제 상품명 매핑 (예: "즉석밥" → "햇반(210g)", 시나리오 1용) |

## ChromaDB / 기타

| 파일 | 역할 |
|---|---|
| `vector_store.py` | ChromaDB 컬렉션 싱글톤 — `get_collection()`(대체품 유사도 검색용 `all_food_products`), `get_knowledge_collection()`(지식 RAG용 `food_knowledge`) |
| `price_cache.py` | `price_cache` 테이블(API 장애 폴백 캐시, CLAUDE.md §11 설계). 현재 실사용은 `/health`의 `ping()`뿐 — save/get은 설계상 존재하며 `scripts/check_price_cache.py`로 수동 점검 가능 |
| `user_input.py` | `user_input_node` — 지역명·단위 확보. `graph/graph.py`에서 price/hybrid 경로에 연결돼 있음(knowledge는 가격 무관이라 건너뜀). 프론트 selectbox 값이 있으면 그대로 통과, 없으면 사용자 문장에서 LLM으로 추출(필드별 병합 — 이미 있는 값은 유지, 누락된 필드만 보완) |

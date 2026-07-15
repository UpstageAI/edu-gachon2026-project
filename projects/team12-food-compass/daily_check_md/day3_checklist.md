# Project Day3 (7/10) 체크리스트 — 장바구니 물가 판단 에이전트

> 목표: Mock → 실제 API 연동, DB 활용, LLM 작동 확인, FastAPI localhost 테스트
> 완료 기준: FastAPI 로컬 서버에서 "상추 지금 비싸?" 입력 시 실제 KAMIS + LLM 기반 SSE 응답이 10초 이내 완료

---

## 1. KAMIS 실제 API 연동

- [ ] `app/tools/kamis.py` Mock → 실제 KAMIS API 호출로 교체
  - **내용**: `get_raw_price_mock()` 대신 실제 KAMIS `dailyPriceByCategoryList` 호출
  - **엔드포인트**: `https://www.kamis.or.kr/service/price/xml.do`
  - **필수 파라미터**: `p_cert_key`, `p_cert_id`, `p_returntype=json`, `p_product_cls_code`, `p_item_category_code`, `p_item_code`
  - **주의사항**:
    - 가격 문자열 콤마 포함 (`"3,606"`) — 기존 `parse_price()` 재사용
    - 결측치 `"-"` 처리 — 기존 로직 유지
    - 당일 데이터 반영 지연 가능 (당일 없으면 전일 데이터로 대체)
  - **Tool**: `httpx` 또는 `requests`

- [ ] KAMIS 품목코드 매핑 테이블 작성
  - **내용**: `상추 → p_item_code`, `배추 → p_item_code` 등 품목명 ↔ KAMIS 코드 매핑
  - **저장 위치**: `app/tools/kamis_codes.py` 또는 `data/kamis_codes.json`

- [ ] `tenacity` 재시도 로직 추가
  - **내용**: KAMIS API 실패 시 최대 3회 재시도 (`@retry(stop=stop_after_attempt(3), wait=wait_fixed(1))`)
  - **Tool**: `tenacity`

---

## 2. Supabase DB 활용 — API 장애 Fallback 연결

> Day2에 `price_cache` 테이블 및 `app/tools/price_cache.py` 구현 완료.
> Day3에서 실제 KAMIS 호출 흐름에 연결.

- [x] `get_raw_price_node`에 Supabase Fallback 연결 (최소 구현 — mock 데이터 기준)
  - **흐름**: mock 조회 성공 → `save_price_cache()` 캐시 갱신 → 결과 반환 (실제 Supabase 저장 확인 완료)
  - **흐름**: mock에 없는 품목 → `get_price_cache()` 캐시 조회 → `is_fallback=True` 플래그와 함께 반환
  - **파일**: `app/tools/kamis.py`
  - **참고**: 실제 KAMIS API 실패 시나리오(§1 완료 후)로는 아직 미검증 — 팀원 KAMIS 실연동 후 재확인 필요

- [ ] Fallback 사용 시 사용자 고지 문구 추가
  - **내용**: 답변 생성 시 `is_fallback=True`이면 "저장된 최신 데이터 기준입니다" 문구 포함
  - **파일**: `app/prompts/prompts.py`

- [ ] Fallback 동작 pytest 검증
  - **내용**: KAMIS API를 의도적으로 실패시켜 캐시에서 정상 응답 반환 확인
  - **파일**: `tests/test_kamis_api.py`

---

## 3. ChromaDB 활용 — RAG 검색 경로 연결

> Day2에서 미완료된 RAG 구성. Day3에서 knowledge/hybrid 라우팅 경로와 연결.

- [ ] ChromaDB `PersistentClient` 셋업
  - **내용**: `chromadb.PersistentClient(path="./chroma_db")` 로 컬렉션 생성
  - **컬렉션명**: `food_knowledge` (대체품목·제철정보·보관법 통합)
  - **파일**: `app/tools/vector_store.py`
  - **저장 위치**: `chroma_db/` (gitignore 대상)

- [ ] RAG 문서 메타데이터 스키마 확정 및 샘플 문서 삽입
  - **메타데이터 필드**: `item_name`, `category`, `content_type` (`substitute`/`seasonal`/`storage`), `source`
  - **내용**: 상추·깻잎·양배추 등 5~10개 대체품목 관계 문서 임베딩 삽입
  - **저장 위치**: `data/rag_docs/`

- [ ] `search_substitute` / `search_knowledge` 함수 구현
  - **내용**: 쿼리 텍스트로 ChromaDB 유사도 검색 → 상위 3개 문서 반환
  - **파일**: `app/tools/substitute.py`

- [ ] ChromaDB 검색 동작 확인
  - **테스트 쿼리**: "상추 대체품" 검색 시 깻잎·양배추 등 반환되는지 확인
  - **파일**: `tests/test_rag.py` 또는 스크립트로 직접 확인

---

## 4. 라우팅 확장 — 4분류 + item 세분화

- [v] `ROUTER_SYSTEM_PROMPT` 4분류로 업데이트
  - **현재**: price / off-topic 2분류
  - **변경**: price / knowledge / hybrid / off-topic 4분류
    - `price`: 가격·시세 조회만 필요한 질문 ("상추 얼마야?")
    - `knowledge`: 가격 데이터 불필요, 보관법·대체품 지식만 필요 ("상추 보관법 알려줘")
    - `hybrid`: 가격 판정 + 대체품 추천 복합 ("상추 비싸면 대체품 알려줘") ← **핵심 시나리오**
    - `off-topic`: 농수산물 구매와 무관한 질문
  - **파일**: `app/prompts/prompts.py`

- [ ] `ParseQuery` 스키마 item 세분화
  - **현재**: `items: list[str]` (품목명만 추출)
  - **추가 검토**: 수량·단위·조건 등 추가 컨텍스트가 필요한지 팀원과 협의
    - 예시: `"쌀 2kg 사야 해"` → `items: ["쌀"]`, 수량은 별도 필드 여부
    - MVP 범위에서 품목명만으로 충분하면 현 구조 유지
  - **파일**: `app/schemas/RouterOutput.py`

- [v] `ParseQuery` intent Literal 업데이트
  - **내용**: `"knowledge"`, `"hybrid"` 추가
  - **파일**: `app/schemas/RouterOutput.py`

- [v] LangGraph 조건부 엣지 4분류로 확장
  - **내용**:
    - `knowledge` → `search_knowledge` 노드 → 답변 생성
    - `hybrid` → `get_raw_price` → `judge_price` → `search_substitute`(비쌈 시) → 답변 생성
    - `price` / `off-topic` → 기존 경로 유지
  - **파일**: `app/graph/graph.py`
  - **참고**: `search_substitute`는 ChromaDB stub이라도 연결해두기

---

## 5. LLM 연동 테스트 및 작동 확인

- [v] Upstage Solar LLM 단독 호출 테스트
  - **내용**: `ChatUpstage(api_key=...).invoke([HumanMessage(content="상추 비싸?")])` 응답 확인
  - **확인 항목**: API 키 유효성, 모델명(`solar-pro3`) 정상 응답, 레이턴시
  - **파일**: `tests/test_llm.py` 또는 `scripts/check_llm.py`

- [ ] LLM 라우터 실제 분류 정확도 확인
  - **테스트 케이스** (각 5회 이상):
    - "상추 지금 비싸?" → `price` 또는 `hybrid`
    - "상추 비싸면 대체품 알려줘" → `hybrid`
    - "상추 보관법 알려줘" → `knowledge`
    - "안녕하세요" → `off-topic`
  - **기준**: 각 케이스 5회 중 4회 이상 정확 분류

- [v] LLM 오류 시 keyword fallback 작동 확인
  - **내용**: API 키를 임시로 빈 값으로 설정 → keyword router로 fallback 되는지 확인
  - **파일**: `tests/test_router.py` (기존 `TestRouterNode` 활용)

---

## 6. FastAPI + SSE 구현 및 localhost 테스트

- [v] FastAPI 앱 구조 완성
  - **내용**: `app/api/main.py` FastAPI 인스턴스 + CORS 설정 + 라우터 등록
  - **파일**: `app/api/main.py`, `app/api/routes.py`

- [v] `/chat` POST 엔드포인트 작성
  - **요청**: `{"query": str}`
  - **응답**: SSE 스트림 (`text/event-stream`)
  - **SSE 이벤트 구조**:
    ```
    event: status  data: {"step": "의도 분류 중..."}
    event: status  data: {"step": "가격 조회 중..."}
    event: status  data: {"step": "판정 중..."}
    event: result  data: {"answer": "상추: 평년 대비 +60.7% → 비쌈\n..."}
    event: done    data: {}
    ```
  - **Tool**: `sse-starlette`

- [v] localhost 서버 실행 및 직접 테스트
  - **실행 명령어**:
    ```
    $env:PYTHONUTF8=1
    uvicorn app.api.main:app --reload --port 8000
    ```
  - **테스트 시나리오**:
    - [v] "상추 지금 비싸?" → price 경로 SSE 응답 확인 (임시 포트 8010에서 검증, 실제 실행 시 8000 사용)
    - [ ] "상추 비싸면 대체품 알려줘" → hybrid 경로 응답 확인 (라우팅·그래프 배선은 완료, `search_substitute` stub이라 대체품 목록은 항상 빈 값 — 팀원 ChromaDB 연동 후 실제 localhost SSE 테스트로 재확인 필요)
    - [v] "안녕하세요" → off-topic 거절 응답 확인
  - **응답 시간 측정**: 첫 SSE 이벤트 3초 이내 / 전체 10초 이내 (수동 확인 결과 즉시 응답, 정식 측정은 미실시)
  - **주의**: 로컬 환경에 포트 8000을 이미 점유 중인 무관한 프로세스("Lumi Agent API")가 있어 실행 전 확인 필요

- [v] `/health` GET 엔드포인트 추가
  - **내용**: 서버 상태 + DB 연결 상태 반환 (`{"status": "ok", "db": "connected"}`)
  - **활용**: Day4 배포 후 헬스체크용

---

## 7. 예외 처리 강화

- [ ] KAMIS API 응답 이상값 처리
  - **내용**: 빈 배열 응답, HTTP 오류 코드, 타임아웃 각각 처리
  - **파일**: `app/tools/kamis.py`

- [ ] 미지원 품목 안내
  - **내용**: KAMIS 품목코드 매핑에 없는 품목명 입력 시 "지원하지 않는 품목입니다" 응답 (임의 추정 금지)
  - **파일**: `app/graph/nodes.py`

---

## 8. 테스트 전체 통과 확인

- [v] 기존 23개 테스트 전체 통과 유지 (현재 28개 전체 통과)
- [ ] 신규 테스트 작성 및 통과
  - `tests/test_kamis_api.py`: KAMIS 실 API + Fallback
  - `tests/test_llm.py`: LLM 라우터 분류 정확도
  - `tests/test_rag.py`: ChromaDB 검색 동작

---

## 9. 진행 체크 (팀 공유용)

| 담당자 | 담당 파트 | 완료 여부 |
|---|---|---|
| | KAMIS 실 API 연동 + Supabase Fallback | [ ] |
| | ChromaDB RAG 경로 연결 | [ ] |
| | Router 4분류 + item 세분화 | [ ] |
| | LLM 연동 테스트 | [ ] |
| | FastAPI + SSE + localhost 테스트 | [ ] |
| | 예외 처리 + 전체 테스트 통과 | [ ] |

**Day3 완료 기준**: `uvicorn` 실행 후 `/chat`에 "상추 지금 비싸?" 전송 시 실제 KAMIS 데이터 + LLM 기반 SSE 응답이 10초 이내 완료. 전체 pytest 통과.

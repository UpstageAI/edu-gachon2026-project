# Sequel API 명세서

자연어 질의(Text-to-SQL) 에이전트의 HTTP API. FastAPI 기준.

- **Base URL**: `http://localhost:8000`
- **공통 prefix**: `/api/v1`
- **Content-Type**: `application/json` (요청), `application/json` 또는 `text/event-stream`(스트리밍)

> 상태: 노드·도구 구현됨 — 스키마 검색/값샘플/검증(sqlglot)/실행은 **실제 Supabase(읽기전용)** 로 동작하며
> 표의 결과는 라이브 데이터다. 다만 **SQL 생성·난이도 분류·요약은 아직 fake LLM**(LiteLLM 미연결)이라
> 생성 SQL·요약 문구는 고정 mock 이다. LiteLLM 연결 단계에서 실제 생성으로 바뀐다.
> (아래 예시는 실제 Olist 데이터 기준 형태.)

---

## 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| POST | `/api/v1/query` | 질의 → 결과(요약·표·SQL) 동기 반환 |
| POST | `/api/v1/query/stream` | 질의 → 노드별 진행 상황 SSE 스트리밍 |
| POST | `/api/v1/suggestions` | 직전 턴 기반 후속질문(버튼용) 최대 2개, 동기 반환 |

---

## 세션 & 히스토리 (로그인 없음)

로그인 기능이 없어서 **"한 접속" = session_id 하나**로 취급한다. 서버가 세션을 발급하지
않는다 — **프론트가 접속 시 UUID 를 하나 생성**해서(`crypto.randomUUID()` 등) 이후 같은
접속의 모든 요청(`/query`, `/query/stream`, `/suggestions`)에 실어 보내면 된다.

- **저장 내용**: 세션당 최근 **5턴**까지, 턴마다 `{질문, 실행된 SQL, 요약}`.
- **저장 시점**: **성공한 턴만** 기록한다(결과 행이 있었던 경우). 안전성 거절·검증 실패·
  결과 없음 턴은 기록하지 않는다 — 다음 질문의 맥락 병합과 후속질문 제안 재료가
  실패 응답으로 오염되지 않게 하기 위함.
- **TTL**: 세션이 30분간 idle 이면 만료(다음 접근 시 히스토리 없이 새로 시작).
- **저장소**: 프로세스 in-memory. 서버 재시작 시 전체 소실되고, **uvicorn 워커를
  2개 이상**으로 띄우면 세션이 워커마다 갈라진다(같은 session_id 요청이 다른 워커로
  가면 히스토리가 안 보일 수 있음) — 지금은 단일 워커 배포 전제.
- **session_id 를 안 보내면**: 완전 무상태로 동작(히스토리 없음, 후속질문 병합 없음).
  이 경우 `/suggestions` 는 호출할 이유가 없다(참조할 직전 턴이 없어 늘 빈 배열).

---

## GET /health

헬스체크.

```bash
curl http://localhost:8000/health
```

```json
{ "status": "healthy" }
```

---

## POST /api/v1/query

자연어 질의를 처리해 요약·표·실행 SQL 을 **한 번에** 반환한다.

### 요청 (QueryRequest)

| 필드 | 타입 | 필수 | 제약 | 설명 |
|---|---|---|---|---|
| `question` | string | ✅ | 1–2000자 | 사용자 자연어 질의 |
| `session_id` | string | ✗ | 1–200자 | 프론트가 생성한 접속 단위 UUID. 생략하면 히스토리 없이 무상태 처리(§세션 & 히스토리) |

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "가장 많이 팔린 상품 카테고리는?", "session_id": "4b6f9e2a-..."}'
```

### 응답 (QueryResponse)

| 필드 | 타입 | 설명 |
|---|---|---|
| `summary` | string | 자연어 요약 (결론 먼저) |
| `columns` | string[] | 결과 표 컬럼명 |
| `rows` | any[][] | 결과 표 행 |
| `sql` | string | 실제 실행된 SQL |
| `difficulty` | string | `easy` \| `medium` \| `hard` \| `extra_hard` |
| `model` | string | 라우팅된 solar 모델 |
| `error` | string | 오류 시 사유 (정상 시 "") |

```json
{
  "summary": "요청하신 조회 결과입니다. 상위 항목부터 정리했어요.",
  "columns": ["product_category_name", "order_count"],
  "rows": [["cama_mesa_banho", 11115], ["beleza_saude", 9670], ["esporte_lazer", 8641]],
  "sql": "SELECT p.product_category_name, COUNT(*) AS order_count FROM olist_order_items oi JOIN olist_products p ON oi.product_id = p.product_id GROUP BY p.product_category_name ORDER BY order_count DESC LIMIT 10",
  "difficulty": "medium",
  "model": "solar-mini",
  "error": ""
}
```

### 예외 응답

- **검증/실행 실패, 데이터 없음, 안전성 거절**: HTTP 200 + `error` 채움, `summary` 에 안내 메시지.

```json
{ "summary": "그 요청은 데이터를 변경할 수 있어 실행하지 않았어요. 저는 조회(읽기)만 도와드려요.",
  "columns": [], "rows": [], "sql": "", "difficulty": "", "model": "", "error": "unsafe_request" }
```

- **요청 검증 실패**(빈 question 등): HTTP 422 (FastAPI 기본).

---

## POST /api/v1/query/stream

같은 질의를 처리하되, 각 노드가 끝날 때마다 진행 상황을 **SSE** 로 흘려보낸다.
UI 의 "쿼리 생성 중…", "안전성 확인 중…" 같은 실시간 표시에 쓴다.

### 요청

`POST /api/v1/query` 와 동일 (QueryRequest, `session_id` 포함).

```bash
curl -N -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "지난달 가장 많이 팔린 상품은?", "session_id": "4b6f9e2a-..."}'
```

### 응답 (text/event-stream)

각 줄은 `data: <StreamEvent JSON>\n\n` 형식. `event` 값:

| event | 시점 | 필드 |
|---|---|---|
| `node` | 노드 1개 완료 | `node`(노드명), `data`(그 노드가 쓴 상태 조각 JSON 문자열) |
| `done` | 최종 완료 | `data`(최종 answer JSON 문자열) |
| `error` | 오류 | `data`(사유) |

노드 순서: `normalize → schema_link → route → generate → validate → execute → format`

```text
data: {"event":"node","node":"normalize","data":"{\"normalized_question\":\"지난달 가장 많이 팔린 상품은?\",\"keywords\":[],\"time_range\":{\"start\":\"2026-06-01\",\"end\":\"2026-06-30\"},\"ambiguous\":false}"}

data: {"event":"node","node":"schema_link","data":"{\"tables\":[\"olist_order_items\",\"olist_products\", ...],\"schema\":\"CREATE TABLE ...\"}"}

data: {"event":"node","node":"route","data":"{\"difficulty\":\"medium\",\"model\":\"solar-pro2\",\"safety\":{\"ok\":true,\"reason\":\"\"}}"}

data: {"event":"node","node":"generate","data":"{\"sql\":\"SELECT p.product_category_name, COUNT(*) ...\",\"iteration\":1}"}

data: {"event":"node","node":"validate","data":"{\"validation\":{\"ok\":true,\"errors\":[]}}"}

data: {"event":"node","node":"execute","data":"{\"result\":{\"columns\":[\"product_category_name\",\"order_count\"],\"rows\":[[\"cama_mesa_banho\",11115]],\"format\":\"table\",\"truncated\":false}}"}

data: {"event":"done","data":"{\"summary\":\"요청하신 조회 결과입니다. ...\",\"table\":{\"columns\":[\"product_category_name\",\"order_count\"],\"rows\":[[\"cama_mesa_banho\",11115]]},\"sql\":\"SELECT ...\",\"disclaimer\":\"이 결과는 조회 시점 기준입니다.\"}"}
```

**프론트 구현 참고**: `done` 이벤트를 받아 답변을 다 그린 뒤, 같은 `session_id` 로
`POST /api/v1/suggestions` 를 한 번 더(별도) 호출해 후속질문 버튼을 채운다. 스트림
자체에는 후속질문이 섞이지 않는다 — 답변 표시가 후속질문 생성 지연을 기다리지 않기 위함.

---

## POST /api/v1/suggestions

직전에 **성공한 턴**(질문·SQL·요약)을 바탕으로, 사용자가 이어서 궁금해할 만한
후속질문 문구를 최대 2개 만들어 반환한다. `/query` 또는 `/query/stream` 로 답변을
받은 **직후 별도로** 호출하는 동기 엔드포인트다(그래프 실행과 무관, LLM 1회 호출).

### 요청 (SuggestionsRequest)

| 필드 | 타입 | 필수 | 제약 | 설명 |
|---|---|---|---|---|
| `session_id` | string | ✅ | 1–200자 | 직전 `/query`(`/stream`)에 실어 보낸 것과 동일한 값 |

```bash
curl -X POST http://localhost:8000/api/v1/suggestions \
  -H "Content-Type: application/json" \
  -d '{"session_id": "4b6f9e2a-..."}'
```

### 응답 (SuggestionsResponse)

| 필드 | 타입 | 설명 |
|---|---|---|
| `suggestions` | string[] | 후속질문 문구 0~2개 |

```json
{ "suggestions": ["배송 완료된 주문만 보면 순위가 바뀔까?", "2018년만 따로 보면 어때?"] }
```

### 빈 배열이 되는 경우 (정상, 에러 아님)

- `session_id` 에 해당하는 세션이 없음(첫 호출·오탈자·30분 idle 만료)
- 직전 턴이 실패했음(안전성 거절/검증 실패/결과 없음 — 히스토리에 애초에 기록되지 않음)
- LLM 이 적절한 후속질문을 찾지 못함

```json
{ "suggestions": [] }
```

프론트는 `suggestions` 가 비어 있으면 버튼을 0개 렌더링하면 된다(별도 에러 처리 불필요).
버튼 클릭 시 새 API 호출은 없다 — 그 문구를 사용자 입력창에 채워 넣기만 하고, 실제
전송(→ `/query` 또는 `/query/stream` 호출)은 사용자가 직접 눌러야 한다(오클릭 방지).

---

## 파이프라인 매핑 (참고)

| 노드 | 하는 일 | 상태에 쓰는 키 |
|---|---|---|
| `normalize` | 시간표현 정규화 + 키워드 추출 + 후속질문 병합 | `normalized_question`, `keywords`, `time_range`, `ambiguous` |
| `schema_link` | 관련 테이블/컬럼 추림 + 값 예시 | `schema`, `tables` |
| `route` | 난이도 분류 + 모델 선택 + injection 가드 | `difficulty`, `model`, `safety` |
| `generate` | 난이도별 SQL 생성 (실패 시 재생성 루프) | `sql`, `iteration` |
| `validate` | sqlglot 문법·화이트리스트·금지어 검증 | `validation` |
| `execute` | read-only 실행(LIMIT·타임아웃) + 포맷 | `result` |
| `format` | 표 + 자연어 요약 | `answer` |

`/suggestions` 는 이 그래프 밖에서 session_store 의 직전 턴을 읽어 LLM 을 1회만
호출한다(별도 노드 아님).

## 실행

```bash
uv run uvicorn app.main:app --reload --port 8000
# 문서 UI: http://localhost:8000/docs  (FastAPI 자동 생성 OpenAPI)
```

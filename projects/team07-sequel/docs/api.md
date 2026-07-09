# Sequel API 명세서

자연어 질의(Text-to-SQL) 에이전트의 HTTP API. FastAPI 기준.

- **Base URL**: `http://localhost:8000`
- **공통 prefix**: `/api/v1`
- **Content-Type**: `application/json` (요청), `application/json` 또는 `text/event-stream`(스트리밍)

> 상태: 현재는 **골격(skeleton)** — 파이프라인(schema_link → route → generate → validate → execute → format)은
> 배선 완료지만, 각 노드의 실제 로직(도구·LiteLLM·Langfuse)은 후속 단계에서 채워진다.
> 따라서 아래 "응답 예시"는 **완성 시 목표 형태**이며, 현재 스켈레톤은 placeholder(`sql: "SELECT 1"`, 빈 표)를 반환한다.

---

## 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/health` | 헬스체크 |
| POST | `/api/v1/query` | 질의 → 결과(요약·표·SQL) 동기 반환 |
| POST | `/api/v1/query/stream` | 질의 → 노드별 진행 상황 SSE 스트리밍 |

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

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "지난달 가장 많이 팔린 상품은?"}'
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
  "summary": "지난달 가장 많이 팔린 상품은 A입니다 (1,240건).",
  "columns": ["product_name", "order_count"],
  "rows": [["A", 1240], ["B", 980]],
  "sql": "SELECT product_name, COUNT(*) AS order_count FROM orders WHERE order_date >= '2026-06-01' AND order_date < '2026-07-01' GROUP BY product_name ORDER BY order_count DESC LIMIT 10",
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

`POST /api/v1/query` 와 동일 (QueryRequest).

```bash
curl -N -X POST http://localhost:8000/api/v1/query/stream \
  -H "Content-Type: application/json" \
  -d '{"question": "지난달 가장 많이 팔린 상품은?"}'
```

### 응답 (text/event-stream)

각 줄은 `data: <StreamEvent JSON>\n\n` 형식. `event` 값:

| event | 시점 | 필드 |
|---|---|---|
| `node` | 노드 1개 완료 | `node`(노드명), `data`(그 노드가 쓴 상태 조각 JSON 문자열) |
| `done` | 최종 완료 | `data`(최종 answer JSON 문자열) |
| `error` | 오류 | `data`(사유) |

노드 순서: `schema_link → route → generate → validate → execute → format`

```text
data: {"event":"node","node":"schema_link","data":"{\"tables\":[\"orders\"],\"schema\":\"CREATE TABLE orders ...\"}"}

data: {"event":"node","node":"route","data":"{\"difficulty\":\"medium\",\"model\":\"solar-mini\",\"safety\":{\"ok\":true,\"reason\":\"\"}}"}

data: {"event":"node","node":"generate","data":"{\"sql\":\"SELECT product_name, COUNT(*) ...\",\"iteration\":1}"}

data: {"event":"node","node":"validate","data":"{\"validation\":{\"ok\":true,\"errors\":[]}}"}

data: {"event":"node","node":"execute","data":"{\"result\":{\"columns\":[\"product_name\",\"order_count\"],\"rows\":[[\"A\",1240]],\"format\":\"table\",\"truncated\":false}}"}

data: {"event":"done","data":"{\"summary\":\"지난달 가장 많이 팔린 상품은 A입니다 (1,240건).\",\"table\":{\"columns\":[\"product_name\",\"order_count\"],\"rows\":[[\"A\",1240]]},\"sql\":\"SELECT ...\",\"disclaimer\":\"\"}"}
```

---

## 파이프라인 매핑 (참고)

| 노드 | 하는 일 | 상태에 쓰는 키 |
|---|---|---|
| `schema_link` | 관련 테이블/컬럼 추림 + 값 예시 | `schema`, `tables` |
| `route` | 난이도 분류 + 모델 선택 + injection 가드 | `difficulty`, `model`, `safety` |
| `generate` | 난이도별 SQL 생성 (실패 시 재생성 루프) | `sql`, `iteration` |
| `validate` | sqlglot 문법·화이트리스트·금지어 검증 | `validation` |
| `execute` | read-only 실행(LIMIT·타임아웃) + 포맷 | `result` |
| `format` | 표 + 자연어 요약 | `answer` |

## 실행

```bash
uv run uvicorn app.main:app --reload --port 8000
# 문서 UI: http://localhost:8000/docs  (FastAPI 자동 생성 OpenAPI)
```

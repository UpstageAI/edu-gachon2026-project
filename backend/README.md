# Text2SQL Backend

FastAPI 기반 백엔드. 프론트엔드로부터 자연어 질문을 받아, (지금은 mock인) AI agent에게
SQL 생성을 요청하고, 안전성 검증을 거쳐 Supabase(Postgres)에서 조회한 결과를
SSE(Server-Sent Events)로 실시간 스트리밍한다.

## 폴더 구조

```
Backend/
├── app/
│   ├── main.py                  # FastAPI 앱 생성, CORS, 라우터 등록
│   ├── api/routes/query.py      # POST /api/query — 유일한 진입점, SSE 스트리밍 처리
│   ├── schemas/query.py         # 요청/응답 Pydantic 모델, SSE 이벤트·에러코드 상수
│   ├── services/
│   │   ├── agent_client.py      # AI agent 호출 어댑터 (현재 mock, 나중에 실제 HTTP 호출로 교체)
│   │   ├── session_store.py     # 세션별 대화 히스토리 (후속 질문 지원, 인메모리)
│   │   └── guardrail.py         # SQL 안전성 2차 검증 (SELECT만 허용, LIMIT 강제)
│   ├── db/database.py           # Supabase(Postgres) 연결 및 조회 실행
│   └── core/config.py           # 환경변수 로드
├── requirements.txt
└── Dockerfile
```

## 요청/응답 스펙

**요청**

```
POST /api/query
Content-Type: application/json

{ "question": "카테고리별 주문 수 알려줘", "session_id": "abc-123" }
```

**응답 (SSE, `text/event-stream`)**

이벤트가 아래 순서로 흐른다. 실패 시 어느 단계에서든 `error`가 오고 스트림이 끝난다.

| 이벤트 | 데이터 | 의미 |
|---|---|---|
| `status` | `{ "message": "..." }` | 진행 상황 (생성 중 / 안전성 확인 중 / 실행 중) |
| `result` | `{ "table": [...], "summary": "..." }` | 조회 결과 표 + 자연어 요약 |
| `sql` | `{ "sql": "..." }` | 실제 실행된 SQL 원문 (투명성 제공, 프론트엔드에서 토글로 노출) |
| `done` | `{}` | 정상 종료 |
| `error` | `{ "code": "...", "message": "..." }` | 실패. `code`는 `VALIDATION_FAILED` / `NO_RESULT` / `AMBIGUOUS_QUESTION` / `INTERNAL_ERROR` 중 하나 |

## 로컬 실행

### 1) 환경변수

`Backend/.env` 파일에 아래 값이 필요하다 (커밋하지 않음, 팀원과 직접 공유).

```dotenv
SUPABASE_DB_URL=postgresql://text2sql_reader.<project-ref>:<비밀번호>@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres
PORT=8080
```

### 2) uvicorn으로 직접 실행

```bash
pip install -r requirements.txt
export SUPABASE_DB_URL="..."
uvicorn app.main:app --reload --port 8080
```

### 3) Docker로 실행 (Cloud Run 환경에 더 가깝게 검증)

```bash
docker build -t text2sql-backend .
docker run -p 8080:8080 --env-file .env text2sql-backend
```

확인:

```bash
curl http://localhost:8080/healthz
# {"status":"ok"}
```

## 현재 상태 / TODO

- **AI agent 연동 (`services/agent_client.py`)**: 아직 mock. 팀원의 AI agent가 별도 서비스로
  분리되어 HTTP로 호출하는 방식으로 결정되었으나, 요청/응답 스펙·에러 규약·세션 ID 공유
  방식은 미정. 스펙이 정해지면 `ask_ai_agent()` 함수 내부만 실제 HTTP 호출로 교체하면 되고,
  라우트/스키마 등 나머지 코드는 그대로 유지된다.
- **재생성 피드백 루프**: SQL 검증 실패 시 AI agent에게 사유를 돌려주고 재시도시키는 로직은
  아직 없음 (지금은 실패하면 바로 `error` 이벤트로 종료).
- **결과 검증(행 수/스키마/타입 재확인)**: 아직 없음. 현재는 결과가 비어있는지만 확인.
- **CORS**: 지금은 전체 허용(`*`). 배포 시 프론트엔드 실제 URL로 제한 필요.
- **CI/CD (`.github/workflows/*.yml`)**: 아직 작성 전.

## 안전장치 (guardrail.py)

AI agent가 생성한 SQL을 그대로 실행하지 않고, 실행 전에 아래를 검사한다.

- `SELECT`로 시작하지 않으면 차단
- `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`CREATE`/`GRANT`/`REVOKE` 포함 시 차단
- `LIMIT`이 없으면 기본값(`LIMIT 200`)을 자동으로 붙임

DB 연결 자체도 읽기 전용 계정(`text2sql_reader`)이라 쓰기 쿼리는 DB 레벨에서도 이중으로 막힌다.

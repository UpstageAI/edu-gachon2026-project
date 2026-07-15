# 배포 가이드 (프론트/배포 담당자용)

## 이미지 받는 방법 (둘 중 하나)

### 방법 A (추천): 미리 빌드된 이미지 pull
`main` 브랜치에 merge되면 GitHub Actions가 자동으로 이미지를 빌드해서 올려둡니다.
로컬 빌드 필요 없이 바로 pull해서 쓰면 됩니다.

```bash
docker pull ghcr.io/safetytrip2026/be:latest
docker run -p 8080:8080 --env-file .env ghcr.io/safetytrip2026/be:latest
```

(GitHub 패키지가 private이면 먼저 로그인 필요: `docker login ghcr.io -u [깃허브계정] -p [Personal Access Token]`.
저장소 Settings에서 패키지를 public으로 바꾸면 로그인 없이 pull 가능)

### 방법 B: 로컬에서 직접 빌드
```bash
docker build -t disaster-agent-be .
docker run -p 8080:8080 --env-file .env disaster-agent-be
```

## 로컬 빌드/실행 확인 (완료됨)
```bash
docker build -t disaster-agent-be .
docker run -p 8080:8080 --env-file .env disaster-agent-be
curl http://localhost:8080/health   # {"status":"ok"} 나오면 정상
```

## 필수 환경변수 (앱 실행에 진짜 필요한 것만)

| 변수명 | 용도 | 어디서 발급 |
|---|---|---|
| `DATABASE_URL` | Supabase Postgres 연결 (통계 집계 + 벡터 검색) | Supabase 프로젝트 > Settings > Database > Connection string (**Session Pooler** 버전 사용 - IPv6 이슈 있음, 자세한 내용 아래 참고) |
| `UPSTAGE_API_KEY` | Solar Chat/Embedding API 인증 | Upstage 콘솔 |
| `SOLAR_MODEL` | (선택) 기본값 `solar-pro2`. 계정에서 다른 모델명 써야 하면 오버라이드 | - |
| `LANGFUSE_PUBLIC_KEY` | LLM 호출/그래프 실행 트레이싱 | Langfuse 프로젝트 설정 |
| `LANGFUSE_SECRET_KEY` | 〃 | Langfuse 프로젝트 설정 |
| `LANGFUSE_HOST` | 〃 (기본값 `https://cloud.langfuse.com`) | - |
| `LANGCHAIN_TRACING_V2` | LangSmith 트레이싱 활성화 (`true`로 설정) | - |
| `LANGCHAIN_API_KEY` | LangSmith 인증 | smith.langchain.com |
| `LANGCHAIN_PROJECT` | LangSmith 프로젝트명 (예: `disaster-safety-agent`) | - |

**트레이싱 관련 변수(`LANGFUSE_*`, `LANGCHAIN_*`)는 없어도 앱은 정상 동작합니다** (관측성만 빠짐). 급하면 나중에 채워도 됩니다.

**주의**: `fetchers/`, `loaders/` 관련 API 키(`DISASTER_MESSAGES_SERVICE_KEY` 등)는 데이터 수집 단계에서만 쓰이고, **실행 중인 앱(app/)에는 전혀 필요 없습니다.** 배포 시 안 넣어도 됩니다.

## 🆕 최초 배포 시 1회 필요: 체크포인터 테이블 생성

대화 세션 유지(thread_id) 기능을 쓰려면 Supabase에 체크포인터 전용 테이블이 있어야 합니다. **앱을 처음 띄우기 전에 딱 한 번만** 실행하면 됩니다 (이후엔 안 해도 됨):

```bash
pip install -r requirements.txt
python loaders/setup_checkpointer.py
```

`checkpoints` / `checkpoint_blobs` / `checkpoint_writes` 테이블이 생성됩니다. 이미 있으면 아무 일도 안 하고 넘어가서, 실수로 여러 번 실행해도 안전합니다.

## Supabase 연결 관련 알려진 이슈

Supabase의 "Direct connection"(`db.xxx.supabase.co`)은 IPv6 전용이라, IPv6 미지원 네트워크(GCE 기본 네트워크 포함 가능성 있음)에서 연결이 안 될 수 있습니다.
**`DATABASE_URL`은 반드시 Session Pooler 연결 문자열을 사용하세요**:
- Supabase 대시보드 → 프로젝트 → 상단 **Connect** 버튼 → **Session pooler** 탭에서 복사
- 형태: `postgresql://postgres.[project-ref]:[password]@aws-0-[region].pooler.supabase.com:5432/postgres`
- 사용자명이 `postgres.[project-ref]` 형태로 일반 `postgres`와 다르니 그대로 복사할 것

## 엔드포인트

| 경로 | 메서드 | 설명 |
|---|---|---|
| `/health` | GET | 헬스체크 |
| `/chat/stream` | POST | SSE 스트리밍 채팅. body: `{"query": "...", "thread_id": "..."}` (`thread_id`는 선택) |
| `/docs` | GET | Swagger UI (SSE 특성상 여기선 응답이 지저분하게 보이는 게 정상, 실제 프론트 연동엔 문제없음) |

## 프론트 연동 시 참고 (SSE 이벤트 종류) — ⚠️ 오늘 여러 번 변경됨, 최신 스펙입니다

### 🆕 대화 세션 유지 (thread_id) — 오늘 추가됨

- **첫 요청**: `thread_id` 안 보내도 됨. 서버가 새로 만들어서 `session` 이벤트로 알려줌.
- **후속 요청**: 그 `thread_id`를 다음 요청 body에 그대로 담아 보내면, **지역/시기/동반자 정보 없이도** 이전 대화 맥락이 이어짐.
  - 예: 1턴 "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?" → 2턴 "노약자는 뭘 더 챙겨야 해?" (지역/시기 재언급 없이도 정확히 답변됨, 실제 테스트로 확인됨)
- 새로운 대화를 시작하려면 `thread_id`를 안 보내거나 새 값으로 바꾸면 됨.

```javascript
// 프론트 구현 예시
let threadId = null;  // 앱 상태에 저장

async function sendMessage(query) {
  const res = await fetch("/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, thread_id: threadId }),  // 처음엔 threadId=null
  });
  // ... SSE 파싱 (아래 참고) ...
  // "session" 이벤트를 받으면 threadId = data.thread_id 로 저장해두고,
  // 다음 sendMessage() 호출부터 계속 같이 보내기
}
```

`/chat/stream`은 요청 상황에 따라 아래 이벤트들을 순서대로 보냅니다. 항상 마지막은 `done`.

**모든 흐름의 맨 앞에는 항상 `session` 이벤트가 먼저 옵니다** (아래는 그 다음부터의 흐름).

### 정상 흐름 (답변 가능한 경우)
```
session → parsed → stats → citation → token(여러 번) → done
```

### 에스컬레이션 흐름 (근거 부족)
```
session → parsed → stats → escalate → done
```

### 재질문 흐름 (지역/시기 파싱 실패)
```
session → reask → done
```

### AI 서비스 완전 장애 (파싱 단계)
```
session → error → done
```

### AI 서비스 완전 장애 (답변 생성 단계) — 이미 parsed/stats/citation은 정상 전송된 뒤
```
session → ... → citation → degraded → token(강등된 원문 안내) → done
```

### 이벤트별 payload

| 이벤트 | payload 예시 | UI 매칭 |
|---|---|---|
| `session` | `{"thread_id": "17390ba2-..."}` | 다음 요청에 그대로 담아 보낼 값 (대화 이어가기용, 저장 필수) |
| `parsed` | `{"region": "부산광역시 해운대구", "month": "8월", "companions": "노약자 동반", "intent": "prevention", "disaster_type": null}` | 지역/시기/동반자 패널 |
| `stats` | `{"scope_used": "sigungu", "total_count": 132, "risk_scores": [{"disaster_type": "폭염", "risk_score": 80, "count": 56}, ...], "top_risk": "폭염", "fallback_notice": null}` | 위험도 점수 차트 (0~100) |
| `citation` | `{"ids": ["GUIDE-HEAT-ELDERLY-001", "GUIDE-RAIN-GENERAL-001"]}` | 인용 배지 |
| `token` | `{"text": "폭"}` (음절 단위로 쪼개져서 옴, **반드시 이어붙여서 렌더링**) | 안전 리포트 본문 |
| `escalate` | `{"reason": "...", "contact": {"phone": "119", "agency": "소방(재난신고)"}, "message": "..."}` | 에스컬레이션 안내 |
| `reask` | `{"message": "지역과 시기를 조금 더 구체적으로..."}` | 재질문 유도 |
| `error` | `{"message": "일시적으로 AI 서비스에 연결할 수 없습니다...", "contact": {...}}` | 전체 실패 안내 |
| `degraded` | `{"reason": "...", "contact": {...}}` (뒤이어 오는 `token`에 강등된 원문 텍스트) | "일부 장애" 안내 배너 후 원문 표시 |
| `done` | `{}` | 스트림 종료 (로딩 인디케이터 끄기) |

**프론트에서 꼭 처리해야 하는 것**:
- `token` 이벤트가 안 오고 바로 `escalate`/`reask`/`error`가 올 수 있음 (정상 케이스)
- `citation` 이벤트 뒤에 `token` 대신 `degraded`가 올 수 있음 (드물지만 대비 필요)
- 알 수 없는 이벤트 타입이 오면 무시하고 넘어가도록 구현 (추후 이벤트 추가될 수 있음)

브라우저에서는 `EventSource`로 그대로 소비 가능:
```javascript
const es = new EventSource("/chat/stream", { method: "POST", body: JSON.stringify({query}) });
// 주의: EventSource는 기본적으로 GET만 지원하므로 POST가 필요하면
// fetch + ReadableStream 방식으로 구현 필요 (아래 참고)
```

**중요**: 표준 `EventSource`는 GET 요청만 지원해서, POST로 body를 보내야 하는 지금 구조에서는 `fetch()` + 스트림 리더 방식으로 구현해야 합니다. 참고용 소비 로직은 `scripts/demo_client.py`(Python)에 동일한 파싱 로직이 있으니 JS로 포팅하면 됩니다.

## 포트
컨테이너 내부 포트는 `8080` (환경변수 `PORT`로 오버라이드 가능).

## CORS
현재 `app/main.py`에 `allow_origins=["*"]`로 전체 허용되어 있음. 실제 프론트 배포 도메인이 정해지면 그 도메인으로 좁히는 걸 권장.
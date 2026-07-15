# app/api/ — FastAPI 앱과 HTTP 엔드포인트

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 앱 생성, CORS 설정, 라우터 등록, 종료 시 Langfuse 트레이스 flush 훅 |
| `routes.py` | 실제 엔드포인트 정의 |

## routes.py 엔드포인트

- **`POST /chat`** — 핵심 엔드포인트. `{query, region?, unit?}`를 받아 LangGraph를 `astream`으로 실행하고 SSE로 스트리밍 응답:
  - `status` 이벤트: "의도 분류 중..." → "가격 조회 중..." → "판정 중..." 진행 상태
  - `token` 이벤트: generate_answer 노드의 LLM 토큰 실시간 전달
  - `result` 이벤트: 최종 답변 / `done` 이벤트: 스트림 종료
  - 그래프 실행 중 어떤 예외가 나도 result+done으로 정상 종료(프론트가 연결 끊김을 겪지 않도록)
  - Langfuse 트레이싱은 이 엔드포인트에만 연결됨(`get_trace_callbacks`) — 키 미설정 시 자동 무시
- **`GET /health`** — 서버 + Supabase 연결 상태 확인(CD 헬스체크가 사용)

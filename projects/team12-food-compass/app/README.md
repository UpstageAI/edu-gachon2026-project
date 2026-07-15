# app/ — 백엔드 애플리케이션 본체

FastAPI + LangGraph 기반 "푸드 나침반" 에이전트의 모든 서버 코드가 이 아래에 있습니다.

## 하위 폴더

| 폴더 | 역할 |
|---|---|
| `api/` | FastAPI 앱 정의와 HTTP 엔드포인트(`/chat` SSE, `/health`) |
| `core/` | 전역 설정·LLM 인스턴스·DB 연결·트레이싱 등 여러 계층이 공유하는 기반 코드 |
| `graph/` | LangGraph StateGraph 정의 — 라우터, 노드, 상태(AgentState), 그래프 배선 |
| `prompts/` | 프로젝트 전체 LLM 프롬프트 중앙 관리 |
| `schemas/` | Pydantic 스키마(라우터 구조화 출력, 가격 판정 결과 등) |
| `tools/` | 그래프 노드들이 사용하는 도구 함수 — KAMIS/참가격 조회, 판정, 단위환산, ChromaDB 등 |

## 요청 처리 흐름 (한눈에)

```text
사용자 질문 → api/routes.py(/chat, SSE)
  → graph/router.py (의도 분류 + 품목 추출, 2차 검증)
  → graph/graph.py 분기
      price/hybrid → tools/user_input.py(지역/단위 확보) → tools/kamis.py(시세)
                   → tools/judge.py(판정) → [비쌈] tools/... 대체품 검색
      knowledge    → ChromaDB 지식 RAG 검색
      off-topic    → 거절 응답
  → graph/nodes.py generate_answer (LLM 답변 생성 + 하드개런티 검증)
  → SSE로 스트리밍 응답
```

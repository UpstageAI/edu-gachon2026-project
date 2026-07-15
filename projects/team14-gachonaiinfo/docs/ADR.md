# Architecture Decision Record (ADR)

프로젝트명: **가천대학교 AI학과 길잡이**
작성 목적: 프로젝트에서 사용한 주요 기술 스택과 아키텍처 선택 이유를 기록한다.
상태: Draft / Accepted 혼합
작성일: 2026-07-12

---

## 기술 스택 요약

| 영역 | 선택 기술 |
|---|---|
| Backend | FastAPI |
| Agent Workflow | LangGraph |
| LLM | Upstage Solar API |
| Embedding | Upstage Embedding API |
| RAG DB | PostgreSQL + pgvector |
| Frontend | Jinja2, HTML, CSS, JavaScript |
| Streaming | SSE, FastAPI StreamingResponse |
| External Tool | Resend API |
| Test | pytest |
| Container | Docker, Docker Compose |
| Deployment | GCP Compute Engine |
| CI/CD | GitHub Actions |
| LLMOps | Guardrail, Retry/Fallback |

---

# ADR-001. Backend Framework로 FastAPI를 사용한다

## Status

Accepted

## Context

본 프로젝트는 사용자의 학사 관련 질문을 입력받고, RAG 검색, LLM 응답 생성, SSE 스트리밍, 외부 API 호출을 처리해야 한다. Python 기반 AI 라이브러리와 연동이 쉽고, 빠르게 API 서버를 구성할 수 있는 백엔드 프레임워크가 필요했다.

## Decision

Backend Framework로 **FastAPI**를 사용한다.

## Rationale

FastAPI는 Python 기반으로 AI/LLM API, LangGraph, PostgreSQL, Resend API와 연동하기 쉽다. 또한 `StreamingResponse`를 지원하여 SSE 기반 실시간 응답 구현에 적합하다. 자동 Swagger 문서(`/docs`)를 제공하므로 API 테스트와 팀원 간 공유도 편리하다.

## Consequences

API 서버 구현 속도가 빠르고, SSE 스트리밍과 LLM 연동을 자연스럽게 처리할 수 있다. 다만 프론트엔드까지 완성도 높게 구성하려면 별도 FE 프레임워크를 도입하거나 Jinja2 기반 UI를 직접 관리해야 한다.

---

# ADR-002. Agent Workflow로 LangGraph를 사용한다

## Status

Accepted

## Context

사용자의 질문은 단순 질의응답뿐 아니라 RAG 검색, Tool 실행, 리마인드 요청 등 여러 흐름으로 분기될 수 있다. 따라서 질문 의도에 따라 적절한 노드로 이동하고, 상태를 유지하면서 실행 흐름을 관리할 구조가 필요했다.

## Decision

Agent Workflow 구성에 **LangGraph**를 사용한다.

## Rationale

LangGraph는 Agent의 상태와 실행 흐름을 graph 형태로 표현할 수 있어 `router_node`, `rag_node`, `tool_node`, `response_node`와 같은 구조를 명확히 설계할 수 있다. 또한 이후 리마인드 Tool, 이메일 발송 Tool, 추가 학사 Tool 등을 확장하기 쉽다.

## Consequences

Agent 흐름을 명확히 분리할 수 있고, 추후 기능 확장이 용이하다. 다만 단순 API 호출 구조보다 state 관리가 복잡하며, node 간 데이터 전달이 제대로 이루어지는지 로그와 테스트가 필요하다.

---

# ADR-003. RAG 저장소로 PostgreSQL + pgvector를 사용한다

## Status

Accepted

## Context

학사 자료, 졸업요건, 수강신청, 사회봉사, 휴학/복학 등 문서 기반 데이터를 검색해야 한다. 단순 키워드 검색보다 사용자의 자연어 질문과 의미적으로 유사한 문서를 찾기 위해 vector search가 필요했다.

## Decision

RAG 저장소로 **PostgreSQL + pgvector**를 사용한다.

## Rationale

PostgreSQL은 관계형 데이터와 문서 metadata를 함께 관리하기 좋고, pgvector를 사용하면 embedding vector 기반 유사도 검색을 수행할 수 있다. 또한 Docker 환경에서 쉽게 실행 가능하며, 추후 Supabase와 같은 managed PostgreSQL로 확장할 수 있다.

## Consequences

문서 chunk, source, metadata, embedding을 하나의 DB에서 관리할 수 있다. 다만 DB schema와 ingest 로직이 맞지 않으면 검색 실패가 발생할 수 있으므로, 적재 후 documents 개수와 검색 결과를 확인하는 과정이 필요하다.

---

# ADR-004. Embedding과 LLM으로 Upstage API를 사용한다

## Status

Accepted

## Context

한국어 학사 문서를 기반으로 검색하고, 사용자의 한국어 질문에 자연스럽게 답변해야 한다. 따라서 한국어 문서와 질의응답에 적합한 embedding 모델과 LLM이 필요했다.

## Decision

Embedding과 답변 생성을 위해 **Upstage Embedding API**와 **Solar LLM API**를 사용한다.

## Rationale

Upstage API는 한국어 문서 처리에 적합하고, OpenAI 호환 방식으로 사용할 수 있어 Python 코드에서 연동하기 쉽다. Embedding API는 문서 chunk와 사용자 질문을 vector로 변환하는 데 사용하고, Solar LLM은 검색된 context를 기반으로 최종 답변을 생성하는 데 사용한다.

## Consequences

한국어 학사 Q&A에 적합한 응답 품질을 기대할 수 있다. 다만 외부 API에 의존하므로 API key 관리, 호출 실패 처리, rate limit 대응이 필요하다.

---

# ADR-005. 응답 방식으로 SSE Streaming을 사용한다

## Status

Accepted

## Context

LLM 응답은 생성 시간이 걸릴 수 있으며, 사용자가 답변이 생성되는 과정을 실시간으로 확인할 수 있는 UX가 필요했다. WebSocket까지는 필요하지 않고, 서버에서 클라이언트로 토큰을 순차적으로 전달하는 단방향 스트리밍이면 충분했다.

## Decision

응답 스트리밍 방식으로 **SSE(Server-Sent Events)** 를 사용한다.

## Rationale

SSE는 HTTP 기반으로 구현이 단순하고, FastAPI의 `StreamingResponse`와 잘 맞는다. LLM의 stream 응답을 `delta` 이벤트로 전달하여 프론트엔드에서 말풍선에 토큰을 순차적으로 표시할 수 있다.

## Consequences

사용자는 답변이 생성되는 과정을 실시간으로 볼 수 있어 UX가 개선된다. 다만 브라우저와 서버 간 스트리밍 처리를 위해 프론트엔드에서 stream reader 구현이 필요하고, 테스트 시 일반 JSON 응답과 구분해야 한다.

---

# ADR-006. Frontend는 Jinja2 + HTML/CSS/JavaScript로 구현한다

## Status

Accepted

## Context

프로젝트의 핵심 평가는 Agent Backend, RAG, LLM 연동, SSE 구현에 있다. 따라서 복잡한 React 기반 프론트엔드보다 빠르게 데모 가능한 UI가 필요했다.

## Decision

Frontend는 **FastAPI Jinja2 Template + HTML/CSS/JavaScript**로 구현한다.

## Rationale

Jinja2는 FastAPI와 함께 간단히 사용할 수 있고, 별도 프론트엔드 빌드 과정 없이 빠르게 채팅 UI를 구현할 수 있다. JavaScript의 `fetch`와 stream reader를 사용하여 SSE 응답도 처리할 수 있다.

## Consequences

개발 속도가 빠르고 배포 구조가 단순하다. 다만 React/Vue 같은 SPA 프레임워크보다 상태 관리와 UI 컴포넌트 재사용성은 낮다.

---

# ADR-007. 외부 Action Tool로 Resend API를 사용한다

## Status

Accepted

## Context

학사 Q&A뿐 아니라 수강신청, 수강정정, 졸업 관련 일정 등을 사용자에게 이메일로 알려주는 리마인드 기능을 실험하고자 했다. 이를 위해 외부 이메일 발송 API가 필요했다.

## Decision

이메일 리마인드 기능의 외부 API로 **Resend API**를 사용한다.

## Rationale

Resend는 Python SDK를 제공하고, 간단한 API 호출로 이메일 발송을 테스트할 수 있다. MVP 단계에서는 사용자의 리마인드 요청을 감지한 뒤, 이메일 주소를 입력받아 테스트 메일을 발송하는 방식으로 외부 action tool 연동 가능성을 검증한다.

## Consequences

Agent가 단순 답변을 넘어 외부 action을 수행하는 구조를 보여줄 수 있다. 다만 이메일 주소는 개인정보이므로 LLM에 전달하지 않고 Python backend 내부에서만 처리해야 하며, 실제 외부 사용자에게 발송하려면 Resend 도메인 인증이 필요하다.

---

# ADR-008. 배포 환경은 Docker + GCP Compute Engine으로 구성한다

## Status

Proposed

## Context

프로젝트 최종 산출물은 로컬 실행뿐 아니라 외부에서 접속 가능한 배포 URL을 요구한다. 팀원 간 환경 차이를 줄이고, 동일한 실행 환경을 유지하기 위한 컨테이너화가 필요하다.

## Decision

애플리케이션은 **Docker**로 컨테이너화하고, 배포는 **GCP Compute Engine VM**에서 Docker Compose로 실행한다.

## Rationale

Docker는 Python 버전, 패키지, 실행 환경 차이를 줄여준다. GCE VM은 Docker Compose 기반 배포가 가능하고, FastAPI 서버와 PostgreSQL을 함께 구성하기 쉽다.

## Consequences

배포 환경 재현성이 좋아지고, 외부 접속 가능한 데모 URL을 제공할 수 있다. 다만 VM 방화벽, 포트 설정, 환경변수 관리, API key 보안 설정이 필요하다.

---

# ADR-009. CI/CD는 GitHub Actions를 사용한다

## Status

Proposed

## Context

프로젝트가 진행되면서 SSE, RAG, Tool, API 기능이 계속 수정되므로, 기본 테스트가 자동으로 실행되는 구조가 필요하다. 또한 Day4 요구사항에서 GitHub Actions 기반 CI/CD 구성이 요구된다.

## Decision

CI/CD 도구로 **GitHub Actions**를 사용한다.

## Rationale

GitHub Repository와 바로 연동할 수 있고, push 또는 pull request 시 pytest를 자동 실행할 수 있다. 이후 GCE VM 자동 배포 스크립트와 연결하여 CD까지 확장할 수 있다.

## Consequences

테스트 자동화를 통해 핵심 기능 회귀를 줄일 수 있다. 다만 배포 자동화를 위해서는 SSH key, VM 접속 정보, API key 등을 GitHub Secrets로 안전하게 관리해야 한다.

---

# ADR-010. LLMOps 안정성 개선 항목으로 Guardrail과 Fallback을 적용한다

## Status

Accepted

## Context

학사 정보는 정확성이 중요하다. LLM이 자료에 없는 내용을 추측해서 답변하면 사용자에게 잘못된 정보를 제공할 수 있다. 또한 외부 API 호출 실패나 검색 실패 상황에서도 서비스가 중단되지 않도록 대응이 필요하다.

## Decision

LLMOps 안정성 개선 항목으로 **RAG score 기반 Guardrail**과 **API 실패 Fallback**을 적용한다.

## Rationale

RAG 검색 결과의 관련도 점수가 낮으면 LLM 답변을 생성하지 않고 “자료에서 확인되지 않습니다”라고 안내하여 hallucination을 줄일 수 있다. 또한 LLM API, DB 검색, Resend API 호출 실패 시 예외를 처리하고 사용자에게 명확한 안내 메시지를 제공한다.

## Consequences

정확성이 중요한 학사 Q&A에서 안전한 답변을 제공할 수 있다. 다만 threshold가 너무 높으면 실제 자료가 있어도 회피 답변이 나올 수 있으므로, 테스트를 통해 적절한 기준을 조정해야 한다.

---

# ADR-011. 검색 정확도 향상을 위해 경량 Reranker를 적용한다

## Status

Accepted

## Context

pgvector 코사인 유사도만으로는 학번·최신성·카테고리 적합도 같은 도메인 신호가 반영되지 않아, 관련 문서가 상위로 올라오지 못하거나 무관 문서가 임계값을 넘는 경우가 있었다.

## Decision

pgvector 후보를 5개 신호의 가중합으로 재정렬하는 경량 Reranker를 적용한다:
`vector 0.65 + keyword 0.15 + category 0.10 + priority 0.05 + recency 0.05`.

## Rationale

임베딩 유사도(vector)를 주 신호로 두되, 질문 토큰 일치(keyword)·라우터 카테고리 적합(category)·문서 중요도(priority)·최신 학년도(recency)를 보조로 결합해 상위 문서의 도메인 적합성을 높인다. 가드레일 임계값도 이 재정렬 점수 기준으로 판단한다.

## Consequences

관련 질문과 무관 질문의 점수 분리가 개선됐다. 다만 가중치는 실측 기반 상수라, 데이터가 크게 바뀌면 재튜닝이 필요하다.

---

# ADR-012. 환각 방지를 위해 가드레일을 다층으로 확장한다

## Status

Accepted

## Context

ADR-010의 RAG 점수 가드레일만으로는 (1) 다른 학과 질문에 인공지능학과 자료로 답하거나, (2) 어휘가 겹치는 자료 미보유 주제(등록금·셔틀 등)가 임계값을 넘어 답이 나가거나, (3) 학번별로 다른 졸업요건을 뭉뚱그리는 문제가 남았다.

## Decision

RAG 점수 가드레일(ADR-010)에 더해 세 개 층을 추가한다.
- **학과 스코프**: 인공지능학과(구 AI·소프트웨어학부) 외 학과명이 있으면 검색·LLM 없이 결정적으로 거절(out_of_scope).
- **범위밖 주제 레지스트리**: 자료 미보유 행정 주제는 점수와 무관하게 가드레일로 문의처 안내.
- **학번 게이트**: 학번별로 답이 갈리는 질문은 학번을 되묻고, 도중에 정정하면 그 학번으로 검색을 재스코프.

## Rationale

스칼라 임계값 하나로는 정상 질문과 점수대가 겹치는 케이스를 분리할 수 없어, 결정적 규칙(학과명·주제 키워드·학번)으로 별도 방어한다. 각 층은 규칙 기반이라 빠르고 재현 가능하며, 50개 시나리오 회귀 테스트로 오발동 0을 확인했다.

## Consequences

환각·오답을 구조적으로 줄였다(가드레일 정확도 100%, 답변 근거일치 93.8%). 다만 범위밖 주제 레지스트리는 수동 키워드 관리라 새 미보유 주제는 추가 전까지 못 막는다.

---

# 전체 아키텍처 요약

```text
사용자
  ↓
Jinja2 Chat UI
  ↓
FastAPI /api/chat 또는 /api/chat/stream
  ↓
LangGraph Agent
  ├─ Router Node: intent 분류 (규칙 우선, LLM 폴백) → 6경로 분기
  ├─ RAG Node: 학사 문서 검색 + Reranker + 다층 가드레일(ADR-011/012)
  ├─ Tool Node: 졸업학점 계산 · 과목 추천
  ├─ Reminder Node: 이메일 리마인드 (확인 후 예약, Human-in-the-loop)
  ├─ Ask-Year Node: 학번 되묻기 (연도-민감 질문)
  ├─ Out-of-Scope Node: 타 학과 질문 결정적 거절
  └─ Response Node: 최종 답변 생성 (Solar LLM)
  ↓
Upstage Solar LLM
  ↓
SSE Streaming Response
  ↓
프론트엔드 채팅 UI 출력
```

---

# 요약 결정문

본 프로젝트는 가천대학교 인공지능학과 학생을 위한 학사 Q&A Agent를 구현하기 위해 FastAPI, LangGraph, PostgreSQL + pgvector, Upstage API, SSE Streaming을 핵심 기술 스택으로 선택했다. FastAPI는 AI API와 SSE 연동에 적합하고, LangGraph는 Agent의 상태와 분기 흐름을 관리하기에 적합하다. PostgreSQL + pgvector는 학사 문서의 vector search와 metadata 관리를 동시에 지원하며, Upstage API는 한국어 학사 문서 기반 답변 생성에 활용된다. 또한 Resend API를 통해 이메일 리마인드 기능을 실험하여 Agent의 외부 action tool 확장 가능성을 검증한다. 최종적으로 Docker, GCP Compute Engine, GitHub Actions를 통해 배포와 자동화까지 확장하는 구조를 채택한다.

# AI 학과 길잡이 — 가천대학교 인공지능학과 안내 Agent

> 가천대학교 인공지능학과 학생이 학교생활과 전공 학습에 필요한 정보를 공식 학사 자료 기반으로 쉽고 빠르게 확인할 수 있도록 돕는 도메인 전문가 AI Agent 서비스

> 이 문서는 제출용 요약본입니다. 아키텍처·시나리오·로드맵 등 상세 설계 문서는 같은 폴더의 [`README.original.md`](./README.original.md)와 [`docs/`](./docs)를 참고하세요.

---

## 1. 프로젝트 소개

**AI 학과 길잡이**는 가천대학교 인공지능학과 신입생·재학생을 대상으로, 학교생활 적응과 전공 학습·학사 정보 탐색을 지원하는 AI Agent 서비스입니다.

- **한 줄 소개**: 공식 학사 자료를 근거로 질문에 답하고, 졸업요건 계산·과목 추천·이메일 리마인드까지 수행하는 학과 전용 Agent
- **주요 사용자**: 가천대 인공지능학과 신입생 및 학사 정보 탐색이 익숙하지 않은 재학생
- **배경**: 신입생은 수강신청·학사일정·졸업요건·전공 학습 방향 등 흩어진 정보를 여러 곳에서 직접 찾아야 하는 어려움을 겪습니다.
- **최종 결과물**: 로컬/클라우드에서 실행 가능한 **Agentic Workflow 데모** (FastAPI + LangGraph + RAG, 웹 채팅 UI)

---

## 2. 문제 정의

- 수강신청, 학사일정, 졸업요건, 교육과정, 학과 공지 등 학생에게 필요한 정보가 **여러 사이트와 PDF에 흩어져** 있어 탐색 비용이 큽니다.
- 일반 검색이나 범용 챗봇은 **학과·학번별로 다른 규정**(예: 학번별 전공 이수학점 기준, 학과별 졸업인증 기준)을 정확히 반영하지 못하고, **출처 없이 추측**하는 경우가 많습니다.
- 그 결과 신입생은 중요한 일정을 놓치거나 잘못된 정보로 학사 판단을 그르칠 위험이 있습니다.

---

## 3. 문제 해결

- **RAG 기반 출처 응답**: 공식 학사 문서(학사일정·교육과정·졸업요건·학과 공지)를 파싱·청킹·임베딩해 PostgreSQL + pgvector에 적재하고, 검색 결과와 **출처를 함께** 제시합니다.
- **의도 라우팅 Agent**: LangGraph로 질문 의도를 분류해 한 턴에 하나의 경로(RAG / 졸업요건 계산 / 과목 추천 / 리마인드 / 가드레일)로 라우팅합니다.
- **학번 인식**: 학번별로 답이 갈리는 질문(졸업요건 등)은 학번을 되물어 해당 년도 기준으로 계산·응답합니다.
- **다층 가드레일**: ① 검색 점수가 낮으면 문의처 안내, ② 타 학과 질문은 "인공지능학과 전용" 안내, ③ 자료 미보유 행정 주제는 어휘가 겹쳐도 추측 없이 문의처로 안내합니다.
- **안전한 실행 제어**: 이메일 리마인드 등 외부 상태 변경 작업은 **사용자 승인 후에만** 실행합니다.

전체 동작 흐름: `사용자 질문 → FastAPI → LangGraph Agent(의도 분류) → 도구/RAG 실행 → Upstage Solar Pro 3 응답 생성(출처 포함) → UI 반환`

---

## 4. 핵심 기능

- **학사·학과 지식 RAG 질의응답** — 공식 문서 기반 검색 + 출처 인용 답변
- **졸업요건 및 부족 학점 계산** — 학번·이수학점 입력 기반, 학번별 기준 반영
- **다음 학기 과목 추천** — 학년/학기/트랙 기반 개설 과목 안내
- **이메일 리마인드** — 사용자 승인 후 예약, 스케줄러가 발송 (Resend API)
- **다층 가드레일 라우팅** — 타 학과·범위 밖·자료 미보유 질문을 추측 없이 문의처로 안내
- **학번 되묻기(Ask-Year)** — 학번에 따라 답이 갈리는 질문의 정확도 확보
- **정량 평가 하네스** — 시나리오 기반 Tier1(결정적 KPI)/Tier2(심판 LLM) 자동 평가
- **관측성** — Langfuse 연동 트레이싱, PII 마스킹

> 정량 평가(50개 시나리오 기준): intent 정확도 98.2%, 가드레일 100%, 답변 근거일치율 93.8%, 출처 인용률 100%, 평균 응답 ~2.4s. 상세는 `eval/` 참고.

---

## 5. 데모 영상

- 데모 영상: https://youtu.be/hwoSwc-66dE
- 배포 URL: http://34.50.27.156:8000/
- 추가 시연 자료: 주요 시연 시나리오 3종은 [`README.original.md`](./README.original.md)의 "주요 사용자 시나리오" 참고

---

## 6. 팀원 소개

| 이름 | 역할 | GitHub |
|---|---|---|
| 최우진 | Backend / Infra — FastAPI 서비스 구현, DB·RAG 데이터 적재, Docker/GCE 배포, CI/CD, Langfuse 관측성, 리마인드 기능 안정화 | [@woojinwoojin](https://github.com/woojinwoojin) |
| 백승훈 | AI / ML — LangGraph 기반 Agent 흐름, RAG 검색 품질, Guardrail, 학번별 라우팅, 평가 시나리오 및 응답 품질 개선 | [@paekseunghoon](https://github.com/paekseunghoon) |

---

## 7. 참고자료 / 발표자료

- 발표자료: [발표 슬라이드 (Google Slides)](https://docs.google.com/presentation/d/1Lhi1kv14Vd70QQHEBFBJoS1JcVYBChm4bUZ2VwwTYAs/edit?usp=sharing)
- 기획서 / 상세 설계: [`README.original.md`](./README.original.md)
- 아키텍처 설계 문서: [`docs/architecture.md`](./docs/architecture.md)
- 의사결정 기록(ADR): [`docs/ADR.md`](./docs/ADR.md)
- 참고한 오픈소스: [LangGraph](https://github.com/langchain-ai/langgraph), [FastAPI](https://github.com/fastapi/fastapi), [pgvector](https://github.com/pgvector/pgvector)
- 사용 모델/API: Upstage Solar Pro 3, Upstage Document Parse, Resend Email API

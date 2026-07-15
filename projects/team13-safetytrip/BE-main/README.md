# 재난안전 여행 가이드 AI 에이전트

행정안전부 긴급재난문자 3개년 이력과 국민행동요령 공공데이터를 결합하여, 여행지·시기별 과거 재난 발생 패턴을 정량 분석하고 상황별 공식 행동요령을 안내하는 LangGraph 기반 AI 에이전트입니다.

> "이 지역, 이 시기에 여행 가는데 뭘 조심해야 하나요?"라고 물으면, 실제 과거 재난 발령 통계와 공식 행동요령을 근거로 맞춤 안전 리포트를 대화형으로 제공합니다.

**참여자**: 정명성, 조혜린

---

## 핵심 가치

이 프로젝트의 기술적 차별점은 **"모르면 안다고 하지 않는다"** 입니다. 안전 도메인에서는 근거 없는 답변(할루시네이션)이 실제 위험으로 직결될 수 있기 때문에, 통계는 실제 재난문자 이력의 SQL 집계로, 행동 지침은 공식 행동요령 인용으로 제시하며, 근거가 충분하지 않으면 답을 생성하지 않고 담당 대응기관을 안내합니다. 이 판단(에스컬레이션)의 정확도는 자체 평가셋으로 precision/recall을 측정해 감이 아닌 지표로 검증했습니다.

---

## 아키텍처

```
[사용자 질문]
     │
     ▼
[FastAPI /chat/stream] ──SSE──▶ [프론트엔드]
     │
     ▼
[LangGraph: parse → route → stats/retrieve → gate(1차) → judge(2차) → escalate | respond]
     │                              │
     ▼                              ▼
[Supabase Postgres+pgvector]    [Solar API]
 - disaster_messages (53,631건)   - Chat: 파싱 / 2차 판정 / 답변 생성
 - disaster_guidelines (751건)    - Embedding: 벡터 검색
 - response_agencies (613건)
 - checkpoints (대화 세션 상태)
```

- **오케스트레이션**: LangGraph. 판단(parse~judge)까지는 일반 그래프 실행, 최종 답변 스트리밍은 FastAPI 레이어에서 직접 처리 (SSE와 그래프 상태관리를 동시에 최적화하는 복잡도를 피하기 위한 실용적 선택)
- **DB**: Supabase(Postgres+pgvector) 하나로 정형 데이터 + 벡터 + 대화 상태 체크포인트까지 통합
- **LLM**: Upstage Solar API (OpenAI SDK 호환)
- **관측성**: Langfuse + LangSmith 이중 트레이싱
- **배포**: Docker → GitHub Container Registry → GCE, 전 과정 CI/CD 자동화

---

## 주요 기능

- **예방형 질문**: "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?" → 3개년 이력 통계로 지역·시기별 재난 유형 빈도를 집계하고, 상위 유형별로 공식 행동요령을 섹션별로 안내
- **반응형 질문**: "호우경보 문자 받았는데 뭘 해야 하죠?" → 해당 재난의 공식 행동요령을 단계별로 안내, 근거(행동요령 카테고리) 인용
- **대화 세션 유지**: 후속 질문("노약자는 뭘 더 챙겨야 해?")이 이전 턴의 지역·시기·동반자 맥락을 자동으로 이어받음
- **2중 게이트 에스컬레이션**: 관련도 임계값(1차, 벡터 거리) + LLM 적합성 판정(2차)을 통과하지 못하면 답변을 생성하지 않고 재난유형별 공식 신고전화로 안내
- **데이터 공백 폴백**: 표본이 부족한 지역/시기는 자동으로 상위 행정구역 단위로 확대하고, 그래도 부족하면 표본 부족을 솔직히 고지
- **LLM 3단 방어**: 호출당 timeout 30초, 지수 백오프 재시도(일시 오류만), 최종 실패 시 행동요령 원문+연락처로 안전하게 강등

---

## 기술 스택

| 영역 | 사용 기술 |
|---|---|
| Backend / Agent | FastAPI, LangGraph, LangChain |
| LLM | Upstage Solar (Chat, Embedding) |
| Database | Supabase (Postgres + pgvector) |
| Frontend | React (별도 레포/담당) |
| 평가 | 자체 평가 스크립트 (`eval/run_eval.py`), precision/recall/F1 |
| 관측성 | Langfuse, LangSmith |
| Infra | Docker, GCE, GitHub Actions |

---

## 프로젝트 구조

```
data-pipeline/
├── app/                    # FastAPI + LangGraph 애플리케이션 (실제 서빙되는 코드)
│   ├── main.py              # SSE 엔드포인트 (/chat/stream)
│   ├── llm_client.py         # Solar API 래퍼 (파싱/판정/답변생성 + 3단 방어)
│   ├── checkpointer.py       # 대화 세션 체크포인터
│   ├── citation.py           # 인용 배지 ID 생성
│   └── graph/                 # LangGraph 노드/그래프 정의
│
├── tools/                  # LangGraph에서 쓰는 Tool 함수
│   ├── stats_tool.py          # 지역×월별 재난 통계 집계 (데이터 공백 폴백 포함)
│   └── retrieve_tool.py       # pgvector 벡터 검색
│
├── fetchers/                # 공공데이터 API 수집 스크립트
├── preprocessors/           # 데이터 정제, DB 스키마, 임베딩
├── loaders/                 # Supabase 적재/마이그레이션 스크립트
├── eval/                    # 평가셋 + 평가 스크립트
├── tests/                    # 유닛테스트
├── scripts/                  # 데모/디버깅용 스크립트
├── frontend-example/         # 프론트엔드 연동 참고 구현 (React, SSE 소비 예시)
│
├── Dockerfile
├── .github/workflows/         # CI/CD (lint/test, DB마이그레이션, 이미지빌드, GCE배포)
├── DEPLOYMENT.md              # 배포/API 연동 상세 가이드
└── DEVLOG.md                  # 전체 개발 과정 기록 (트러블슈팅 포함)
```

---

## 로컬 실행

### 1. 환경변수 설정
`.env.example`을 참고해서 `.env` 파일 생성. 최소한 `DATABASE_URL`, `UPSTAGE_API_KEY`는 필수입니다.

### 2. 의존성 설치
```bash
pip install -r requirements.txt
```

### 3. DB 마이그레이션 (최초 1회)
```bash
python loaders/create_tables.py        # disaster_messages, response_agencies, disaster_guidelines 테이블
python loaders/setup_checkpointer.py   # 대화 세션 체크포인터 테이블
```

### 4. 서버 실행
```bash
uvicorn app.main:app --reload --port 8000
```

### 5. 테스트
```bash
curl -N -X POST http://localhost:8000/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"query": "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?"}'
```

더 보기 좋게 확인하려면(SSE를 실제로 이어붙여서 렌더링):
```bash
python scripts/demo_client.py "8월 초에 부모님 모시고 부산 해운대 가는데 주의할 게 있을까?"
```

---

## API

`POST /chat/stream` 하나로 모든 대화를 처리합니다 (SSE 스트리밍).

```json
{"query": "사용자 질문", "thread_id": "선택, 대화 이어가기용"}
```

이벤트 종류(`session`/`parsed`/`stats`/`citation`/`token`/`escalate`/`reask`/`error`/`degraded`/`done`)와 페이로드 상세, 프론트엔드 연동 방법은 **[`DEPLOYMENT.md`](./DEPLOYMENT.md)** 를 참고하세요.

---

## 평가 (Evaluation)

에스컬레이션 판단(답변 가능 vs 근거부족)의 정확도를 자체 평가셋 30건(행동요령 있는 상황 20건 + 없는 상황 10건, 경계선 케이스 포함)으로 측정합니다.

```bash
python eval/run_eval.py
```

2차 게이트(LLM 적합성 판정) 도입 및 반복 캘리브레이션을 통해 **F1 스코어 50% → 73.7%** 로 개선했습니다. 상세 과정은 [`DEVLOG.md`](./DEVLOG.md) 5장 참고.

---

## CI/CD

| 워크플로우 | 트리거 | 역할 |
|---|---|---|
| `ci.yml` | PR 생성 시 | lint(ruff) → test(pytest) |
| `db-cd.yml` | `main`에 스키마 변경 push | Supabase 자동 마이그레이션 |
| `docker-cd.yml` | `main`에 앱 코드 변경 push | Docker 이미지 빌드 → ghcr.io 업로드 |
| `gce-deploy-cd.yml` | `docker-cd` 성공 후 | GCE 서버 자동 재배포 + 헬스체크 |

CodeRabbit이 PR에 AI 코드 리뷰를 자동으로 남깁니다.

---

## 더 자세한 내용

- **개발 전체 기록 (트러블슈팅/의사결정 포함)**: [`DEVLOG.md`](./DEVLOG.md)
- **배포 가이드 및 API 상세 스펙**: [`DEPLOYMENT.md`](./DEPLOYMENT.md)

![demo](assets/demo.gif)

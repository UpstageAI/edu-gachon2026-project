# LawHelp — 생활법령 기반 생활법률 RAG 에이전트

## 1. 프로젝트 소개

LawHelp는 법제처 찾기 쉬운 생활법령정보의 백문백답 데이터를 바탕으로, 일반 사용자가 부동산/임대차와 복지 분야의 생활법률 정보를 더 쉽게 확인할 수 있도록 돕는 RAG 기반 AI 에이전트입니다.

사용자 질문을 먼저 지원 범위와 검색 관련도 기준으로 분기하고, 검색 근거가 충분한 경우에만 문서 기반 답변을 생성합니다. 직접 근거가 부족한 질문은 일반지식 기반 안내임을 명확히 표시하며, 지원 범위 밖 질문은 답변 생성을 차단합니다.

본 서비스는 일반 정보 제공용이며, 변호사 상담이나 공식 법률 자문을 대체하지 않습니다.

## 2. 문제 정의

생활법률 정보는 공식 문서에 존재하더라도 일반 사용자가 자신의 상황에 맞는 항목을 찾고 이해하기 어렵습니다.

특히 부동산/임대차, 복지 제도는 용어가 낯설고, 신청 요건이나 권리 관계를 잘못 이해하면 실제 행동에 영향을 줄 수 있습니다. 또한 검색 결과가 애매한 경우에도 AI가 근거 있는 답변처럼 말하면 사용자가 답변의 신뢰도를 과대평가할 위험이 있습니다.

LawHelp는 이 문제를 다음 관점에서 다룹니다.

- 사용자의 질문이 현재 서비스 지원 범위에 속하는지 먼저 확인
- 검색 문서와의 관련도에 따라 답변 방식을 구분
- 근거 기반 답변과 일반지식 기반 안내를 사용자에게 명확히 구분
- 최신 기준이나 개인별 적용 여부는 공식 기관 확인이 필요하다고 안내

## 3. 문제 해결

LawHelp는 질문 처리 흐름을 단순 RAG 호출이 아니라 단계별 Agent workflow로 구성했습니다.

```text
사용자 질문
→ scope_check
→ domain_guardrail
→ ChromaDB raw top-k 검색
→ cosine distance 기반 route 결정
→ route별 답변 생성 또는 고정 응답
→ output_guardrail
→ sync 응답 또는 stream SSE 응답
```

핵심 정책은 다음과 같습니다.

- `GROUNDED_RAG`에서만 검색 문서를 직접 근거로 사용
- `RELATED_HYBRID`, `LLM_ONLY`는 일반지식 기반 제한 안내로 처리
- `OUT_OF_SCOPE`는 LLM generation 없이 고정 안내문 반환
- 답변 끝에는 일반 정보 제공이며 법률 자문이 아니라는 고지 부착
- Langfuse metadata로 route, guardrail, distance, 검색 문서 정보를 추적

## 4. 핵심 기능

- 법제처 생활법령 백문백답 기반 RAG 검색
- 부동산/임대차, 복지 도메인 가드레일
- ChromaDB cosine distance 기반 답변 route 분기
- sync API와 stream SSE API 제공
- Upstage Solar Pro 3 기반 답변 생성
- Solar Pro 2 fallback을 포함한 LLM Retry/Fallback
- Langfuse trace를 통한 관측성 확보
- Streamlit 기반 최소 채팅 UI
- Docker Compose 기반 API/Frontend/ingest 실행
- GitHub Actions CI/CD와 GCE 배포 구성

## 5. 데모 영상

데모 영상: `https://drive.google.com/file/d/1GgplS6b5uRy2WHCrbORkf0x9PsKjxV4V/view?usp=drive_link`
배포 URL: `http://8.230.11.213:8501/`

## 6. 팀원 소개

| 이름 | GitHub ID | 역할 |
| --- | --- | --- |
| 강경현 | `letscodedirty` | Data Processing, RAG Evaluation, Frontend |
| 이정대 | `JJungDae` | Backend, AI Agent, DevOps/Infra |

### 팀명: 생활백답

## 7. 참고자료 / 발표자료

- 데이터 출처: 법제처 찾기 쉬운 생활법령정보 백문백답
- 발표자료: `https://docs.google.com/presentation/d/1TID68N6BgGHnVK51T1M22EpA2Z54zDUtnRWnZlHSbHs/edit?usp=sharing`
- Repository: `https://github.com/JJungDae/lawHelp-agent`

## 8. 시스템 아키텍처

```text
Streamlit Frontend
        ↓
FastAPI Backend
        ↓
LangGraph Agent Workflow
        ↓
Domain Guardrail / Routing / Output Guardrail
        ↓
ChromaDB + Upstage Embedding
        ↓
Upstage Solar Pro 3 / Solar Pro 2 fallback
        ↓
Langfuse Observability
```

주요 서버 구성은 Docker Compose로 관리합니다.

- `api`: FastAPI backend
- `frontend`: Streamlit UI
- `ingest`: ChromaDB 데이터 적재용 profile service
- `chroma_data`: ChromaDB named volume

## 9. 답변 분기 정책

검색 척도는 ChromaDB cosine distance입니다. 낮을수록 더 가까운 문서입니다.

```text
exact_threshold = 0.54
related_threshold = 0.65
```

| route | 조건 | 동작 |
| --- | --- | --- |
| `out_of_scope` | 지원 범위 밖 질문 | LLM 호출 없이 고정 안내문 반환 |
| `grounded_rag` | `distance <= 0.54` | 검색 문서를 직접 근거로 답변 |
| `related_hybrid` | `0.54 < distance <= 0.65` | 직접 근거 부족 경고 후 일반지식 기반 제한 안내 |
| `llm_only` | 지원 분야이지만 관련 검색 결과 부족 | 검색 근거 없는 일반지식 안내 |
| `error` | LLM 호출 실패 등 내부 오류 | fallback 응답 |

`RELATED_HYBRID`와 `LLM_ONLY`는 데이터 기반 답변으로 취급하지 않습니다. 두 route 모두 warning을 먼저 표시하고, 공식 기관 확인이 필요하다는 안내를 붙입니다.

## 10. 기술 스택

### Frontend

- Streamlit
- Requests

### Backend / Agent

- FastAPI
- LangGraph
- Pydantic
- Loguru

### AI / RAG

- Upstage Solar Pro 3
- Upstage Solar Pro 2 fallback
- LiteLLM
- Upstage Embedding API
- ChromaDB

### Observability / Infra

- Langfuse
- Docker
- Docker Compose
- GitHub Actions
- Google Compute Engine

## 11. 데이터셋

- 데이터 출처: 법제처 찾기 쉬운 생활법령정보 백문백답
- 현재 데이터 범위: 부동산/임대차, 복지
- Chroma collection: `law_qa`
- 문서 수: 156
- 저장 방식: `question + answer` 텍스트를 Upstage embedding-passage로 임베딩
- 검색 방식: 질문을 Upstage embedding-query로 임베딩 후 ChromaDB top-k 검색
- distance metric: cosine distance

데이터 적재 스크립트는 `scripts/ingest_chroma.py`입니다.

## 12. 실행 방법

### 로컬 실행

```powershell
py -3.12 -m pip install -r requirements.txt
py -3.12 scripts\ingest_chroma.py
py -3.12 -m uvicorn app.main:app --reload
```

Streamlit UI를 별도로 실행하려면 다음 명령을 사용합니다.

```powershell
streamlit run frontend/app.py
```

### Docker Compose 실행

처음 실행하거나 ChromaDB volume이 비어 있다면 먼저 데이터를 적재합니다.

```powershell
docker compose --profile tools run --rm ingest
docker compose up -d --build
```

## 13. 환경 변수

환경 변수 예시는 `.env.example`에 정의되어 있습니다.

| 이름 | 설명 | 필수 여부 |
| --- | --- | --- |
| `ENVIRONMENT` | 실행 환경 이름 | 선택 |
| `DEBUG` | 디버그 모드 | 선택 |
| `UPSTAGE_API_KEY` | Upstage API 키 | 필수 |
| `LLM_MODEL` | 기본 LLM 모델 | 선택 |
| `LANGFUSE_ENABLED` | Langfuse 활성화 여부 | 선택 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key | Langfuse 사용 시 필요 |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key | Langfuse 사용 시 필요 |
| `LANGFUSE_BASE_URL` | Langfuse endpoint | Langfuse 사용 시 필요 |

Langfuse 키가 없거나 `LANGFUSE_ENABLED=false`이면 tracing 없이 서버가 동작합니다.

## 14. API

### Health

```http
GET /health
```

### Sync Chat

```http
POST /chat/sync
Content-Type: application/json
```

요청 예시:

```json
{
  "message": "전세 계약 전에 뭘 확인해야 하나요?"
}
```

주요 응답 필드:

```text
answer
category
guardrail_blocked
is_fallback
retrieved_count
response_type
warning
suggested_questions
sources
is_grounded
```

### Stream Chat

```http
POST /chat/stream
Content-Type: application/json
```

SSE 이벤트 계약:

```text
event: token
event: metadata
event: done
event: error
```

## 15. 평가 결과

현재 route threshold는 `app/core/routing.py` 기준입니다.

```text
exact_threshold: 0.54
related_threshold: 0.65
```

팀 최종 threshold는 골든셋 75문항 1차 평가를 바탕으로 조정되었으며, 코드 주석에는 라우팅 정확도 개선 근거가 함께 기록되어 있습니다.

기존 routing-only 검토 산출물은 `artifacts/day5_routing_evaluation.csv`에 남아 있습니다.

```text
질문 수: 76
PASS: 66
FAIL: 10
Chroma collection: law_qa, 156 documents
embedding model: Upstage embedding-query
LLM generation: 호출하지 않음
top_k: 3
```

실제 분기 수:

```text
grounded_rag: 24
related_hybrid: 28
llm_only: 6
out_of_scope: 18
```

최종 작업 보고서 기준 검증 결과:

```text
pytest: 84 passed
ruff: passed
```

## 16. 제한사항

- 현재 지원 데이터 범위는 부동산/임대차와 복지 분야로 제한됩니다.
- 모든 법률 분야를 지원하지 않습니다.
- 변호사 상담이나 법률 자문을 대체하지 않습니다.
- 최신 법령을 실시간 웹 검색하지 않습니다.
- 답변의 정확성을 보장하지 않으며, 개인별 적용 여부는 공식 기관 확인이 필요합니다.
- `RELATED_HYBRID`, `LLM_ONLY` 답변은 검색 문서를 직접 근거로 한 답변이 아닙니다.
- LLM이 생성한 안내에는 최신 금액, 기한, 자격 기준이 반영되지 않을 수 있습니다.

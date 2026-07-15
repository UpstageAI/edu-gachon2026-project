# 🧭 Food Compass (장바구니 물가 판단 에이전트)

> 지속되는 고물가 속, 자취생을 위한 "이거 지금 사도 될까?"에 답하는 LangGraph + RAG 기반 AI 에이전트

---

## 1. 프로젝트 소개

### 문제 정의

본 프로젝트는 지속되는 고물가 상황 속에서 실제 자취 경험을 통해 체감한 장보기 부담에서 출발하였습니다. 시중에는 농수산물 시세를 단순 조회하는 서비스는 존재하지만, 사용자의 상황에 맞추어 "지금 사도 되는지", "더 저렴한 대안은 없는지"를 판단해주는 서비스는 찾기 어려웠습니다. 저희 팀은 한국농수산식품유통공사(KAMIS) Open-API와 공공데이터 포탈(식료품)을 통해 실시간 농수산물 가격 데이터와 식료품에 접근 가능함을 사전에 확인하였고, 이를 기반으로 단순 정보 제공을 넘어 판단과 대안 제시까지 수행하는 AI Agent를 구현하여 1인 가구뿐만 아니라 다인 가구에서도 활용할 수 있는 서비스를 구축하고자 하였습니다.

### 문제 해결

최근 식료품 가격 상승으로 인해 자취생들은 한정된 생활비 안에서 식재료를 구매해야 하는 부담이 커지고 있습니다. 특히 농수산물은 계절, 지역, 판매처, 수급 상황에 따라 가격 차이가 크기 때문에 사용자가 직접 여러 정보를 비교하기 어렵습니다. 또한 자취생은 대량 구매보다 소량 구매가 많고, 개개인마다 보관 기간이나 조리 수준이 다르기 때문에 필요에 맞는 물품에 대한 합리적인 구매 결정이 필수적입니다. 따라서 가성비를 고려하여 합리적인 구매 결정을 도와주는 AI Agent가 필요합니다.

이 프로젝트는 사용자가 농수산물와 식료품 구매 전 가격과 대안을 빠르게 비교하고, 자신의 상황에 맞는 선택을 할 수 있도록 지원하는 것을 핵심 문제로 설정합니다.

### 핵심 시나리오

1. **원물 대체품 판단형** — "상추 지금 비싸? 비싸면 대체할 거 없어?"
   시세 조회 → 평년 대비 비쌈/적정/쌈 판정 → 비쌈 판정 시 벡터DB로 같은 부류의 대체 품목 검색
2. **쌀 vs 즉석밥 비교형** — "쌀 사서 밥 짓는 거랑 햇반 사 먹는 거 뭐가 싸?"
   원물(쌀)과 가공식품(즉석밥)을 "밥 1공기" 기준으로 환산해 어느 쪽이 더 경제적인지 비교
3. **가공식품 단독 조회형** — "참치캔 얼마야?"
   KAMIS에 없는 가공식품을 참가격(공공데이터포털) DB에서 검색해 매칭되는 상품 전부의 평균가 제공
4. **지식(제철·보관법) 질의형** — "깻잎 오래 두면 어떻게 보관해?"
   RAG(ChromaDB)에 저장된 문서만 근거로 답변, LLM이 정보를 지어내지 않도록 방지

---

## 2. 핵심 기능

- **자연어 의도 분류 (Router)**: 사용자 질문을 `price`(가격) / `knowledge`(지식) / `hybrid`(가격+대체품) / `off-topic`(무관) 4가지로 분류하고 품목명을 추출 (LLM 구조화 출력, 실패 시 키워드 기반 폴백)
- **2차 검증(Validation)**: 장난·롤플레잉 문장에 식품 키워드가 우연히 섞인 경우(예: "상추 인 더 버거를 대령해오거라")를 걸러내는 방어 로직
- **가격 판정**: 1주일 전 대비 1개월 전 가격 등락률로 "비쌈/적정/쌈" 판정 (평년 대비는 참고 정보로만 제공)
- **단위 환산**: kg/g, 개/단/포기 등 다양한 판매 단위를 사용자가 원하는 기준(100g/500g/1kg)으로 환산
- **원물 ↔ 가공식품 비교**: 서로 다른 두 데이터 소스(KAMIS·참가격)를 하나의 기준(밥 1공기)으로 정규화해 비교
- **대체품 추천 (RAG)**: 비쌈으로 판정된 품목에 대해 같은 부류(채소류/축산물 등) 안에서 벡터 유사도로 대체 품목 검색
- **지식 답변 (RAG)**: 제철 정보·보관법 문서를 벡터DB에서 검색해 그 내용만 근거로 답변 생성
- **환각(hallucination) 방지 하드 가드**: LLM 답변에 품목명 누락, 판정 어조 모순, 근거 없는 퍼센트 수치 등이 감지되면 고정 템플릿 답변으로 자동 폴백
- **SSE 스트리밍 응답**: FastAPI + `sse-starlette`로 진행 상태("가격 조회 중...", "판정 중...")와 최종 답변 토큰을 실시간 스트리밍
- **LLM 폴백**: 주 모델(Upstage Solar) 실패 시 백업 모델로 자동 재시도
- **LLMOps 트레이싱(선택)**: Langfuse 연동 — 미설치·미설정이어도 조용히 비활성화되어 기존 동작에 영향 없음
- **Streamlit 챗봇 프론트엔드**: 지역/단위 선택 후 채팅 형태로 질의

---

## 3. 시스템 아키텍처 (그래프 흐름)

LangGraph `StateGraph`로 구성된 에이전트 파이프라인입니다. 그래프가 실행되기 전, **Streamlit UI에서 사용자가 지역(8개 권역)과 가격 계산 단위(100g/500g/1kg)를 먼저 선택**해야 채팅 입력창이 활성화됩니다(`frontend/app.py`). 선택된 지역·단위는 사용자 질문과 함께 `/chat` 요청(`region`, `unit`)에 실려 그래프의 초기 상태(`AgentState`)로 그대로 전달되고, 이후 `judge_price`(단위 환산 기준)·`generate_answer`(지역/단위 반영 답변) 등에서 사용됩니다.

```
[Streamlit UI] 지역 선택 → 단위 선택 → "선택 완료" → 채팅 입력 활성화
   │  (region, unit 확정)
   ▼
사용자 질문 입력 (user_query) ── region·unit과 함께 /chat 요청으로 전송
   │
   ▼
[router] 의도 분류(price/knowledge/hybrid/off-topic) + 품목 추출
   │
   ├─ off-topic ────────────────────────────► [generate_offtopic] ─► END
   │
   ▼
[validate_request] 2차 검증(장난·오탐 문장 필터링)
   │
   ├─ off-topic(검증 실패) ──────────────────► [generate_offtopic] ─► END
   ├─ knowledge ──► [search_knowledge] ──────► [generate_answer] ─► END
   │
   └─ price / hybrid
        ▼
     [get_raw_price] KAMIS 시세 조회
        ▼
     [resolve_processed_items] 원물+가공식품 조합 여부 판별
        │
        ├─ 원물 1개+가공식품 1개 ──► [compare_items] ─────────────► [generate_answer] ─► END
        ├─ 전부 가공식품(KAMIS 없음) ─► [search_processed_price] ──► [generate_answer] ─► END
        └─ 그 외(일반 원물 조회) ──► [judge_price] 비쌈/적정/쌈 판정(unit 기준 환산)
                                        │
                                        ├─ 비쌈 ─► [search_substitute] 대체품 검색 ─► [generate_answer] ─► END
                                        └─ 그 외 ─────────────────────────────────► [generate_answer] ─► END
```

> 참고: `app/tools/user_input.py`의 `user_input_node`는 UI로 지역/단위를 받지 못한 경우(예: CLI 경로)를 대비해 사용자 발화에서 지역/단위를 LLM으로 직접 추출하는 유틸리티이지만, 현재 `app/graph/graph.py`의 `compiled_graph`에는 아직 연결되어 있지 않습니다 — 지금은 Streamlit UI의 선택값이 사실상 유일한 지역/단위 입력 경로입니다.

---

## 4. 기술 스택

| 영역 | 사용 기술 |
|---|---|
| LLM | Upstage Solar (`solar-pro3`, 백업 `solar-pro2`) via `langchain-upstage` |
| Orchestration | LangGraph (`StateGraph`, conditional edges) |
| Backend | FastAPI + `sse-starlette` (SSE 스트리밍) |
| Frontend | Streamlit |
| Vector DB | ChromaDB (로컬 PersistentClient, `jhgan/ko-sroberta-multitask` 한국어 임베딩) |
| RDB | Supabase(PostgreSQL) — 시세 스냅샷 저장/조회 |
| 외부 API | KAMIS Open-API(농수산물 시세), 공공데이터포털 참가격(가공식품 시세) |
| LLMOps | Langfuse(트레이싱, 선택 항목) |
| Infra | Docker Compose, GHCR, GCP Compute Engine, GitHub Actions(CI/CD + 일일 시세 수집 cron) |
| 패키지 관리 | `uv` |
| 테스트/린트 | pytest, pytest-asyncio, ruff, mypy |

---

## 5. 환경 설정

### 5.1 요구사항

- Python **3.12** (`.python-version` 고정, `pyproject.toml`은 `>=3.11` 허용)
- [`uv`](https://docs.astral.sh/uv/) 패키지 매니저
- Supabase(PostgreSQL) 프로젝트 — 시세 데이터 저장용 RDB
- KAMIS Open-API 인증키, 공공데이터포털(참가격) 서비스키
- Upstage API 키 (LLM 호출용)
- (선택) Langfuse 계정 — 트레이싱용, 없어도 정상 동작

### 5.2 주요 의존성 (`pyproject.toml`)

```toml
[project]
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.32.0",
    "python-dotenv>=1.0.0",
    "pydantic>=2.0.0",
    "httpx>=0.27.0",
    "streamlit>=1.40.0",
    "chromadb>=0.5.0",
    "langchain-core>=0.3.0",
    "langchain-community>=0.3.0",
    "langchain-openai>=0.2.0",
    "langchain-upstage>=0.3.0",
    "langgraph>=1.2.9",
    "sse-starlette>=2.1.0",
    "tenacity>=9.0.0",
    "litellm>=1.50.0",
    "psycopg2-binary>=2.9.12",
    "sentence-transformers>=3.0.0",
    "torch",
]

[dependency-groups]
dev = ["mypy>=2.2.0", "pytest>=8.0.0", "pytest-asyncio>=0.24.0", "ruff>=0.15.21"]
stretch = ["langchain>=1.3.13", "langfuse>=4.13.0"]  # LLMOps 선택 가점 항목
```

> `torch`는 CPU 전용 wheel(`https://download.pytorch.org/whl/cpu`)로 고정되어 있습니다(GPU 없는 배포 환경에서 디스크 부족 방지).

### 5.3 설치

```bash
# 저장소 클론
git clone <repo-url>
cd food-compass

# 의존성 설치 (dev 그룹 포함, Langfuse까지 쓰려면 --group stretch 추가)
uv sync --group dev
# 또는: uv sync --group dev --group stretch
```

### 5.4 환경 변수 (`.env`)

`.env.example`을 복사해 `.env`로 만들고 값을 채웁니다.

```bash
cp .env.example .env
```

| 변수 | 설명 |
|---|---|
| `KAMIS_CERT_KEY` / `KAMIS_CERT_ID` | KAMIS Open-API 인증 정보 |
| `PRICE_GOKR_SERVICE_KEY` | 공공데이터포털 참가격 API 서비스키 |
| `UPSTAGE_API_KEY` | Upstage Solar LLM API 키 |
| `LANGFUSE_TRACING_ENABLED` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_BASE_URL` | (선택) Langfuse 트레이싱 — 값이 비어 있으면 자동으로 비활성화 |
| `SUPABASE_URL` / `SUPABASE_KEY` | Supabase 프로젝트 정보 |
| `DATABASE_URL` | Supabase PostgreSQL 직접 연결 문자열 (`app/tools/*.py`가 `psycopg2`로 직접 사용) |

### 5.5 DB 초기화

Supabase SQL Editor에서 [`data/sql/init.sql`](data/sql/init.sql)을 실행해 아래 테이블/뷰를 생성합니다.

- `price_snapshot` — KAMIS 시세 스냅샷
- `query_log` — 질의/응답 로그(선택)
- `price_gokr_items` / `price_gokr_stores` — 참가격 품목·매장 마스터
- `price_gokr_snapshot` — 참가격 매장별 가격 관측치
- `price_gokr_store_regions` — 매장 주소 → 8개 권역 분류
- `price_gokr_regional_avg` — 지역별 평균가 뷰

이후 최초 1회 시세 데이터를 채워야 합니다.

```bash
# KAMIS 시세 수집
.venv/Scripts/python.exe scripts/fetch_kamis_snapshot.py

# 참가격(가공식품) 시세 수집
.venv/Scripts/python.exe scripts/fetch_price_gokr_snapshot.py
```

(이후로는 GitHub Actions cron이 매일 자동 수집합니다 — §7 참고)

### 5.6 벡터 DB(ChromaDB) 적재

```bash
# 대체품 검색용 컬렉션 (KAMIS 품목, 부류별 메타데이터 포함)
.venv/bin/python data/build_substitute_collection.py

# 지식(제철·보관법) RAG 문서 적재
.venv/bin/python data/insertion_knowledge_rag.py
```

### 5.7 실행

```bash
# 1) 터미널 CLI로 체험
.venv/Scripts/python.exe run.py

# 2) FastAPI 백엔드 서버
uvicorn app.api.main:app --reload

# 3) Streamlit 프론트엔드 (백엔드 서버가 떠 있어야 함)
streamlit run frontend/app.py

# 또는 Docker Compose로 백엔드+프론트엔드 한 번에
docker compose up --build
```

- 백엔드: http://localhost:8000 (`/chat`: SSE 채팅 엔드포인트, `/health`: 헬스체크)
- 프론트엔드: http://localhost:8501

---

## 6. 프로젝트 구조

```
food-compass/
├── app/                    # 백엔드 애플리케이션 (에이전트 로직)
│   ├── api/                 # FastAPI 앱, 라우트
│   ├── core/                 # 설정, LLM 클라이언트, 트레이싱
│   ├── graph/                # LangGraph 그래프 정의(노드/라우터/상태)
│   ├── prompts/               # 전체 프롬프트 중앙 관리
│   ├── schemas/                # Pydantic 스키마(LLM 구조화 출력, Tool 입출력)
│   └── tools/                   # 외부 API 클라이언트, DB 접근, 판정/정규화 로직
├── frontend/                # Streamlit 챗봇 UI
├── data/                    # RAG 문서, 벡터DB 구축/적재 스크립트, ChromaDB 로컬 저장소
├── scripts/                 # 1회성/cron 실행용 시세 수집·점검 스크립트
├── tests/                   # pytest 테스트 스위트
├── .github/workflows/       # CI, CD, 일일 시세 수집 cron
├── Chroma-db/                # (참고 자료) ChromaDB를 GCP Cloud Run에 배포하는 방법 문서 — 현재 앱은 로컬 PersistentClient 사용, 실제 배포엔 미사용
├── Dockerfile.api / Dockerfile.frontend
├── docker-compose.yml / docker-compose.prod.yml
├── run.py                   # 터미널 CLI 진입점
└── pyproject.toml
```

---

## 7. 폴더 및 파일별 상세 설명

### `app/api/` — FastAPI 진입점

| 파일 | 역할 |
|---|---|
| `main.py` | FastAPI 앱 생성, CORS 설정, 서버 종료 시 Langfuse 트레이스 flush |
| `routes.py` | `/chat`(SSE 스트리밍 채팅), `/health`(DB 연결 헬스체크) 엔드포인트 |

### `app/core/` — 공통 설정/인프라

| 파일 | 역할 |
|---|---|
| `config.py` | `pydantic-settings` 기반 전역 설정(`.env` 로드), LLM 모델명·폴백 모델 검증 |
| `llm.py` | 주/백업 LLM(Upstage Solar) 인스턴스 생성 및 폴백 호출(`invoke_with_fallback`, `ainvoke_structured_with_fallback`) |
| `tracing.py` | Langfuse 트레이싱 초기화 — 패키지 미설치·키 미설정 시 조용히 비활성화 |
| `state.py` | `app.graph.state.AgentState`를 재노출(하위 호환용 import 경로) |

### `app/graph/` — LangGraph 에이전트 파이프라인

| 파일 | 역할 |
|---|---|
| `state.py` | 그래프 전체에서 공유되는 `AgentState`(TypedDict) 정의 |
| `router.py` | 1차 의도 분류(`router_node`, LLM+키워드 폴백)와 2차 검증(`validate_request_node`, 오탐 방지) |
| `nodes.py` | 지식 검색, 대체품 검색, 원물/가공식품 비교, 가공식품 단독 조회, 최종 답변 생성 등 대부분의 노드 로직 + 환각 방지 하드 가드 |
| `graph.py` | 위 노드들을 `StateGraph`로 연결하는 조건부 라우팅 정의, `compiled_graph` 생성 |
| `config.py` | 그래프 관련 부가 설정(현재 최소 구성) |

### `app/prompts/`

| 파일 | 역할 |
|---|---|
| `prompts.py` | Router, 검증, 답변 생성(가격 판정/비교/가공식품/지식) 등 모든 시스템 프롬프트를 한 곳에서 관리하는 상수 모음 |

### `app/schemas/` — Pydantic 스키마

| 파일 | 역할 |
|---|---|
| `RouterOutput.py` | Router LLM 구조화 출력(`ParseQuery`), 2차 검증 출력(`ValidateQuery`) |
| `schemas.py` | `RouterOutput`, `RawPriceInput/Output`, `JudgePriceOutput`, `SubstituteOutput` 등 Tool 입출력 스키마 |

### `app/tools/` — 외부 연동 및 핵심 계산 로직

| 파일 | 역할 |
|---|---|
| `kamis_client.py` | KAMIS `dailyPriceByCategoryList` 실 API 클라이언트(legacy TLS 대응 포함) |
| `kamis.py` | Supabase `price_snapshot`에서 조회한 KAMIS 데이터를 그래프 상태(`price_data`)로 가공(축산물 부위별 나열, 대표 등급 선정, ILIKE 유사 품목 폴백 등) |
| `price_snapshot.py` | Supabase `price_snapshot` 테이블 저장/조회(UPSERT, 유사 품목명 검색, 보관 기간 정리) |
| `price_gokr_client.py` | 공공데이터포털 참가격(`ProductPriceInfoService`) 실 API 클라이언트 |
| `price_gokr_snapshot.py` | Supabase `price_gokr_*` 테이블 저장/조회(품목·매장 마스터, 가격 스냅샷, 지역별 분류, 가공식품 부분일치 검색) |
| `item_alias.py` | 사용자가 부르는 일반 명칭(예: "즉석밥") → 참가격 DB 실제 상품명(예: "햇반(210g)") 매핑 |
| `normalize.py` | 무게/개수 단위 환산(`normalize_price_unit`) 및 "밥 1공기" 기준 환산(`rice_price_per_bowl`) |
| `judge.py` | 1주일 전 vs 1개월 전 가격 등락률로 비쌈/적정/쌈 판정(`judge_price`, `judge_price_node`) |
| `price_cache.py` | Supabase `price_cache` 테이블(KAMIS API 장애 시 Fallback 캐시) 저장/조회 |
| `region.py` | 참가격 매장 주소를 8개 권역(서울/경기도/강원도/인천/전라도/경상도/충청도/제주도)으로 분류 |
| `user_input.py` | 사용자 발화에서 지역명·단위를 LLM으로 추출(프론트에서 이미 선택값을 넘긴 경우 스킵) |
| `vector_store.py` | ChromaDB 임베딩 모델·컬렉션(`all_food_products`, `food_knowledge`) 싱글톤 관리 |

### `frontend/`

| 파일 | 역할 |
|---|---|
| `app.py` | Streamlit 챗봇 UI — 지역/단위 선택, SSE 스트리밍 응답 렌더링, 좌우 말풍선 커스텀 스타일 |

### `data/` — RAG/벡터DB 구축 자산

| 파일 | 역할 |
|---|---|
| `build_substitute_collection.py` | Supabase `price_snapshot`의 품목명을 기준으로 대체품 검색용 컬렉션(`all_food_products`)을 부류(category) 메타데이터와 함께 재구축 |
| `insertion_knowledge_rag.py` | `rag_docs/seasonal_knowledge.json`을 읽어 지식 RAG 컬렉션(`food_knowledge`)에 적재 |
| `insertion-chroma-db.py` | **Deprecated** — 예전 방식(참가격 혼재, 부류 메타데이터 없음)의 컬렉션 구축 스크립트. 실행 시 안내만 출력하고 종료(교차오염 방지를 위해 비활성화됨) |
| `inspect_chroma.py` | 저장된 ChromaDB 컬렉션 내용을 확인하는 점검용 스크립트 |
| `rag_docs/seasonal_knowledge.json` | 품목별 제철정보·보관법 원본 지식 문서 |
| `sql/init.sql` | Supabase 초기 스키마(테이블/인덱스/뷰/RLS 정책) 정의 |
| `chroma_db/` | ChromaDB 로컬 퍼시스턴스 파일(런타임 생성물, 볼륨 마운트 대상) |
| `mock/`, `rag_docs/__init__.py` | 테스트/RAG용 보조 모듈 |

### `scripts/` — 운영/점검용 스크립트

| 파일 | 역할 |
|---|---|
| `fetch_kamis_snapshot.py` | KAMIS 전체 부류 가격을 조회해 Supabase `price_snapshot`에 적재 (일일 cron 기반) |
| `fetch_price_gokr_snapshot.py` | 참가격 품목·매장·가격을 조회해 Supabase `price_gokr_*`에 적재 (일일 cron 기반) |
| `check_price_cache.py` | `price_cache` 저장/조회 동작을 터미널에서 직접 확인하는 점검 스크립트 |

### `tests/` — pytest 테스트

| 파일 | 역할 |
|---|---|
| `test_graph.py` | 그래프 end-to-end 테스트(가격 판정, off-topic, 쌀 vs 즉석밥 비교 시나리오 등) |
| `test_router.py` | Router 의도 분류·품목 추출 테스트 |
| `test_judge_price.py` | 가격 판정 로직 단위 테스트 |
| `test_normalize.py` | 단위 환산 로직 단위 테스트 |
| `test_supabase_connection.py` | Supabase 연결 확인 테스트 |
| `test_code_rabbit.py` | CodeRabbit 리뷰 관련 회귀 테스트 |
| `fixtures/kamis_mock.json` | KAMIS 응답 목(mock) 데이터 |
| `APItest.ipynb` | API 실 호출 확인용 노트북(ruff/mypy 검사 대상 제외) |

### `.github/workflows/`

| 파일 | 역할 |
|---|---|
| `ci.yml` | PR/main 푸시 시 lint(ruff)·타입체크(mypy)·시크릿 스캔(gitleaks)·pytest 실행 |
| `cd.yml` | CI 성공 후 Docker 이미지를 빌드해 GHCR에 푸시하고 GCP Compute Engine에 배포(헬스체크 실패 시 자동 롤백) |
| `kamis_daily_fetch.yml` | 매일 09:00 KST, KAMIS 시세를 수집해 Supabase에 적재 |
| `price_gokr_daily_fetch.yml` | 매일 09:00 KST, 참가격 시세를 수집해 Supabase에 적재 |

### 기타 루트 파일

| 파일 | 역할 |
|---|---|
| `run.py` | 터미널에서 에이전트를 대화형으로 체험할 수 있는 CLI 진입점 |
| `Dockerfile.api` / `Dockerfile.frontend` | 백엔드/프론트엔드 각각의 컨테이너 이미지 정의 |
| `docker-compose.yml` | 로컬 개발용 (api + frontend 빌드) |
| `docker-compose.prod.yml` | 운영 배포용 (GHCR에 푸시된 이미지 pull) |
| `project_status.md` | 프로젝트 기획 초기 단계(Day1) 현황 정리 문서 |
| `Chroma-db/` | ChromaDB를 GCP Cloud Run에 별도 배포하는 방법을 정리한 참고 문서 — 현재 앱은 이 방식을 쓰지 않고 로컬 `PersistentClient`(`data/chroma_db`)를 사용 |

---

## 8. 테스트 & 코드 품질

```bash
# 전체 테스트
uv run pytest

# 린트
uv run ruff check app/ frontend/ tests/

# 타입 체크
uv run mypy app/
```

CI(`ci.yml`)는 위 항목들과 시크릿 스캔(gitleaks)을 PR/main 푸시마다 자동으로 실행합니다.

---

## 9. 데이터 흐름 요약

1. GitHub Actions cron이 매일 KAMIS·참가격 API를 호출해 Supabase에 시세 스냅샷 저장
2. 사용자가 질문하면 Router가 의도를 분류하고, `app/tools/kamis.py` 등이 Supabase의 **최신 스냅샷만** 조회(외부 API를 매 요청마다 호출하지 않음)
3. 판정·비교·대체품 검색 결과를 바탕으로 LLM이 자연어 답변을 생성하며, 여러 하드 가드가 사실 왜곡(품목 누락, 판정 모순, 근거 없는 수치)을 걸러냄

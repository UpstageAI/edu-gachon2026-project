# FinBrief 📊

사용자가 관심 있는 금융 토픽을 구독하면 실제 시장 지표와 경제 뉴스를 수집해 매일 아침 7시에 디스코드를 통한 이미지 전송 형태의 브리핑으로 정리해주는 AI 서비스입니다.

사용자는 Discord 챗봇에서 관심 토픽을 관리할 수 있고, 매일 아침 전체 시장 리포트와 토픽별 카드 요약 뉴스를 받아 볼 수 있습니다. 

FinBrief는 투자 판단을 대신하지 않으며, 모든 결과는 참고용 정보로만 제공됩니다.

---

## 1. 일반 사용자용 안내 👥

FinBrief가 이미 배포되어 있고, 사용자는 서비스를 이용하기만 한다는 가정으로 설명합니다. 
별도의 설치, API key, 서버 설정은 필요하지 않습니다.

### FinBrief로 할 수 있는 일 ⚙️

| 기능 | 설명 |
| --- | --- |
| 관심 토픽 구독 | 비트코인, 나스닥, 환율, 금리, 반도체, AI 등 보고 싶은 금융 토픽을 등록합니다. |
| 구독 목록 확인 | 현재 내가 구독 중인 토픽과 구독 가능한 토픽을 확인합니다. |
| 토픽 삭제 | 더 이상 보고 싶지 않은 토픽을 구독 목록에서 제거합니다. |
| 주요 지표 리포트 확인 | 주식 지수, 금리, 원자재, 환율 등 핵심 지표를 이미지 리포트로 봅니다. |
| 토픽별 카드뉴스 확인 | 내가 구독한 토픽에 대해 수치, 요약, 관련 뉴스 근거가 포함된 카드뉴스를 받습니다. |
| 오늘 리포트 설명 요청 | 당일 리포트에서 변동이 큰 지표와 함께 봐야 할 뉴스 흐름을 설명받습니다. |
| 카드뉴스 출처 설명 요청 | 오늘 받은 카드뉴스가 어떤 RSS/RAG 뉴스 근거를 바탕으로 작성됐는지 확인합니다. |

### 웹 화면 이용 💻

[웹 주소](http://34.50.41.2:8000/)에 접속하면 다음 정보를 확인할 수 있습니다.

- FinBrief 세부 설명
- FinBrief에 사용된 기술
- FinBrief를 Discord에 등록하기

### Discord 챗봇 이용 📱

Discord 서버에서 `/finbrief` 또는 `@finbrief` 명령을 사용합니다.

대표 입력 예시는 다음과 같습니다.

```text
/finbrief message: 나스닥 구독해줘
/finbrief message: 내 토픽 보여줘
/finbrief message: 비트코인 취소해줘
/finbrief message: 금리 구독
/finbrief message: 처음인데 뭐 받아보면 좋아?
/finbrief message: 오늘 리포트에서 뭐 봐야 해?
/finbrief message: 오늘 카드뉴스 출처 알려줘
```

### 사용 예시 💬

| 사용자가 입력 | FinBrief가 하는 일 |
| --- | --- |
| `나스닥 구독해줘` | 나스닥 토픽을 내 구독 목록에 추가합니다. |
| `내 토픽 보여줘` | 현재 구독 중인 토픽과 구독 가능한 토픽을 표 형태로 보여줍니다. |
| `금리 구독` | 여러 금리 토픽 후보를 제시하고, 사용자가 선택할 수 있게 안내합니다. |
| `비트코인 취소해줘` | 비트코인 토픽을 구독 목록에서 제거합니다. |
| `오늘 리포트에서 뭐 봐야 해?` | 당일 지표 리포트에서 크게 움직인 지표와 관련 뉴스 흐름을 설명합니다. |
| `오늘 카드뉴스 출처 알려줘` | 내가 받은 카드뉴스별 참고 기사와 출처를 정리합니다. |

### 결과를 읽는 방법 📊

**주요 지표 리포트**는 시장 전체를 빠르게 훑기 위한 이미지입니다.

- 지수, 금리, 원자재, 환율 등 핵심 지표를 한 장에 표시합니다.
- 상승과 하락 방향, 변화폭, 단위를 함께 확인합니다.
- 일부 데이터가 부족하면 가능한 값만 표시하고, 잘못된 값은 그대로 확정하지 않습니다.

**토픽별 카드뉴스**는 내가 구독한 주제만 따로 정리한 결과입니다.

- 토픽 이름과 핵심 요약
- 관련 지표 또는 가격 변화
- RSS 뉴스 기반 근거
- 카드뉴스 작성에 참고한 기사 출처와 링크
- 투자 조언이 아니라는 안내 문구

### 꼭 알아둘 점 ⚠️

- FinBrief는 투자 조언 서비스가 아닙니다.
- 매수, 매도, 목표가, 수익 보장 같은 투자 판단은 제공하지 않습니다.
- 뉴스와 지표는 외부 데이터 소스를 기반으로 하므로, 발표 시점이나 수집 시점에 따라 최신 값과 차이가 있을 수 있습니다.
- 챗봇이 토픽을 정확히 이해하지 못하면 후보를 먼저 제시합니다. 이 경우 원하는 토픽명을 다시 입력하면 됩니다.

---

## 2. 외부 개발자용 안내 🛠️

이 영역은 FinBrief를 로컬에서 실행하거나, 구조를 이해하거나, 배포 환경을 구성하려는 개발자를 위한 설명입니다.

### 프로젝트 개요 🏗️

FinBrief는 FastAPI 기반 백엔드와 LangGraph 에이전트 파이프라인으로 구성됩니다. 외부 데이터 소스에서 금융 지표와 뉴스를 수집하고, Supabase PostgreSQL과 pgvector에 저장한 뒤, RAG 검색과 LLM 분석을 통해 리포트와 카드뉴스를 생성합니다.

전체 흐름은 다음과 같습니다.

```text
사용자 토픽 구독
  -> 토픽 매칭
  -> 외부 지표/뉴스 수집
  -> Supabase 저장
  -> 뉴스 임베딩 및 RAG 검색
  -> LangGraph 리포트/카드 생성
  -> 웹 화면/API/Discord 전달
  -> Langfuse 관측성 기록
```

### 기술 스택 💻

| 영역 | 사용 기술 |
| --- | --- |
| Backend | Python 3.11, FastAPI |
| Agent workflow | LangGraph |
| LLM gateway | LiteLLM |
| Observability | Langfuse |
| Database/RAG | Supabase PostgreSQL, pgvector |
| Data sources | FRED, yfinance, 한국은행 ECOS, RSS |
| Image/report | Pillow, Gemini image model |
| Bot/Delivery | Discord.py |
| Infra | Docker, Docker Compose, GitHub Actions, GCE |

### 사전 준비 📋

실데이터 실행에는 다음 외부 리소스가 필요합니다.

| 준비 항목 | 설명 |
| --- | --- |
| Supabase project | `schemas/supabase.sql` 실행, service role key 준비 |
| Upstage API key | LLM 호출과 4096차원 embedding 생성 |
| Gemini API key | 카드/리포트 이미지 생성 |
| FRED API key | 미국 경제 지표 수집 |
| ECOS API key | 한국은행 통계 수집 |
| 뉴스 RSS URL | 경제/시장 뉴스 수집 URL 목록 |
| Discord bot token | `/finbrief` 명령과 채널 발송 |
| Langfuse key | LLM 호출과 report run 관측성 |

Supabase SQL Editor에서 먼저 실행합니다.

```sql
-- schemas/supabase.sql 전체 실행
```

토픽 seed가 필요한 경우 다음 파일도 실행합니다.

```sql
-- schemas/seed_topics.sql 전체 실행
```

### 환경변수 ⚙️

`.env.example`을 복사한 뒤 실제 값을 채웁니다. 실제 secret은 Git에 커밋하지 않습니다.

```powershell
Copy-Item .env.example .env
```

주요 환경변수는 다음과 같습니다.

| 변수 | 설명 |
| --- | --- |
| `APP_ENV` | 실행 환경. 로컬 개발은 `local`, 배포 환경은 `prod` 권장 |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | 서버 측 Supabase service role key |
| `UPSTAGE_API_KEY` | LLM 및 embedding 호출 key |
| `GEMINI_API_KEY` | 이미지 생성 key |
| `FRED_API_KEY` | FRED 지표 수집 key |
| `ECOS_API_KEY` | 한국은행 ECOS 지표 수집 key |
| `NEWS_RSS_URLS` | 쉼표로 구분한 뉴스 RSS URL 목록 |
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `DISCORD_GUILD_ID` | slash command를 동기화할 Discord guild id |
| `LANGFUSE_ENABLED` | Langfuse 전송 활성화 여부 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse public key |
| `LANGFUSE_SECRET_KEY` | Langfuse secret key |
| `LANGFUSE_HOST` | Langfuse host URL |
| `FINBRIEF_TRACE_SALT` | Discord 사용자/채널 ID를 Langfuse metadata에 남길 때 사용하는 hash salt |
| `FINBRIEF_REPORT_OUT` | 리포트 이미지 출력 경로 |
| `FINBRIEF_FONT` | 한글 리포트 렌더링용 폰트 경로 |
| `SERVICE_PORT` | Docker Compose 노출 포트. 기본값 `8000` |

### 로컬 실행 💻

Windows PowerShell 기준입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

`.env`에 실데이터 값을 채운 뒤 API 서버를 실행합니다.

```powershell
python -m uvicorn app.main:app --reload
```

확인 주소:

- 웹 화면: `http://127.0.0.1:8000/`
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/api/v1/health`

### 주요 API 🔑

토픽 목록 조회:

```powershell
curl http://127.0.0.1:8000/api/v1/topics
```

키워드로 토픽 찾기:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/topics/match `
  -H "Content-Type: application/json" `
  -d "{\"query\":\"비트코인\",\"limit\":5}"
```

토픽 구독:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/subscriptions/demo-user/topics `
  -H "Content-Type: application/json" `
  -d "{\"topic_id\":\"topic_btc\",\"channel\":\"discord\"}"
```

선택 토픽 데이터 수집과 Supabase 적재:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/topics/topic_btc/ingest `
  -H "Content-Type: application/json" `
  -d "{\"run_date\":\"2026-07-14\",\"include_indicators\":true,\"include_news\":true,\"include_embeddings\":true,\"dry_run\":false}"
```

구독 중인 토픽을 새로 수집한 뒤 리포트 생성:

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/reports/run `
  -H "Content-Type: application/json" `
  -d "{\"run_date\":\"2026-07-14\",\"dry_run\":false,\"refresh_data\":true}"
```

오늘 리포트 설명:

```powershell
curl "http://127.0.0.1:8000/api/v1/reports/today/explanation?run_date=2026-07-14"
```

사용자 카드 조회:

```powershell
curl "http://127.0.0.1:8000/api/v1/cards/today?user_id=demo-user&run_date=2026-07-14"
```

사용자 카드뉴스 출처 설명:

```powershell
curl "http://127.0.0.1:8000/api/v1/cards/today/sources?user_id=demo-user&run_date=2026-07-14"
```

### Discord bot 실행 🤖

Discord Developer Portal에서 bot token, guild id, message content intent, `applications.commands` scope를 확인합니다.

```powershell
python -m app.services.discord_bot
```

Supabase 연결이 설정되어 있으면 구독 상태는 DB에 저장됩니다.

### 배치와 스케줄러 ⏰

전체 시장 리포트와 구독 토픽 카드 생성을 한 번 실행합니다.

```powershell
python -m app.services.batch
```

스케줄러는 매일 지정한 KST 시각에 배치를 실행합니다.

```powershell
python -m app.services.scheduler
```

관련 환경변수:

```text
FINBRIEF_BATCH_HOUR=7
FINBRIEF_BATCH_MINUTE=0
FINBRIEF_RUN_ON_START=1
```

### Docker 실행 🐳

Docker Desktop 또는 Docker Engine이 실행 중이어야 합니다.

```powershell
docker compose up -d --build
curl http://127.0.0.1:8000/api/v1/health
docker compose ps
```

종료:

```powershell
docker compose down
```

Compose에는 세 가지 서비스가 포함됩니다.

| 서비스 | 역할 |
| --- | --- |
| `finbrief-api` | FastAPI API와 웹 화면 제공 |
| `finbrief-bot` | Discord 챗봇 실행 |
| `finbrief-scheduler` | 매일 아침 배치 실행 |

### CI/CD 🚀

GitHub Actions는 테스트와 배포를 분리합니다.

| Workflow | 실행 시점 | 역할 |
| --- | --- | --- |
| `FinBrief CI` | push, pull request, 수동 실행 | Python compile, pytest, Docker build |
| `FinBrief CD` | main CI 성공 후 또는 수동 실행 | GHCR 이미지 빌드/푸시, GCE 배포, health check, rollback |

GCE 배포를 사용하려면 GitHub repository secrets에 Supabase, 외부 API, Discord, Langfuse, `FINBRIEF_TRACE_SALT`, GCE SSH 정보를 등록해야 합니다.

최소 GCE 배포 Secret은 다음과 같습니다.

| Secret | 설명 |
| --- | --- |
| `GCE_HOST` | GCE VM 외부 IP 또는 도메인 |
| `GCE_USERNAME` | SSH 접속 사용자 |
| `GCE_SSH_KEY` | 배포용 private key |
| `SERVICE_PORT` | 서비스 포트. 기본값 `8000` |

실데이터 운영에는 `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `UPSTAGE_API_KEY`, `GEMINI_API_KEY`, `FRED_API_KEY`, `ECOS_API_KEY`, `NEWS_RSS_URLS`, `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST`, `FINBRIEF_TRACE_SALT`도 함께 등록합니다.

수동 배포는 GitHub `Actions` -> `FinBrief CD` -> `Run workflow`에서 실행합니다.

### 프로젝트 구조 🏗️

```text
app/
  api/             FastAPI route
  agents/          LangGraph 리포트/카드 생성 pipeline
  core/            설정, schema, LLM, guardrail, observability
  repositories/    Supabase 저장소와 개발용 memory 저장소
  services/        챗봇, 배치, 스케줄러, 데이터 적재 서비스
  tools/           외부 데이터, RSS, embedding, 발송 도구
frontend/          배포본에 포함되는 결과 확인 화면
schemas/           Supabase SQL과 agent state schema
tests/             자동 테스트
.github/workflows/ CI/CD workflow
```

### 검증 🔍

개발 중 기본 검증:

```powershell
python -m compileall app
python -m pytest -p no:cacheprovider --basetemp .pytest_cache\basetemp-local --disable-warnings
docker compose config
```

배포 후 확인:

```powershell
curl http://127.0.0.1:8000/api/v1/health
curl http://127.0.0.1:8000/api/v1/topics
```

### 운영 원칙 📋

- 실제 secret은 `.env` 또는 GitHub Secrets에만 둡니다.
- `.env`, private key, 생성 산출물은 Git에 커밋하지 않습니다.
- Supabase schema와 외부 API key를 준비한 뒤 실행합니다.
- 모든 리포트와 카드에는 투자 조언이 아니라는 disclaimer를 유지합니다.
- 사용자 입력이 모호하면 바로 저장하지 않고 후보 토픽을 안내합니다.

# Text2SQL(Sequel) 프로젝트 종합 정리

작성일: 2026-07-09 (최종 갱신: 2026-07-14, 프론트엔드 4화면 재구성 + 마크다운 렌더링 수정 반영) · 가천대 2026 AI 부트캠프 team07 · 담당: 이후윤 (서버/DB/프론트엔드/백엔드/CI-CD) · 권도윤 (AI agent, 프론트엔드 재구성)

이 문서 하나로 "우리가 지금까지 뭘 만들었고, 어떻게 접근하고, 어떻게 실행하는지"를 전부 확인할 수 있도록 정리했습니다. 자세한 배경/의사결정 히스토리는 `SERVER_HANDOFF.md`, DB 스키마 상세는 `DATA_SCHEMA.md`를 참고하세요.

---

## 1. 프로젝트 한눈에 보기

**Sequel**: 자연어로 질문하면 SQL을 몰라도 데이터베이스에서 바로 답을 받아볼 수 있는 Text-to-SQL 서비스.

```
[사용자] → [Cloud Run: 프론트엔드 React] → [External HTTPS LB] → [GCE VM: 백엔드 FastAPI] → [Supabase Postgres]
                                                                              │
                                                                              └→ [GCE VM: AI agent] (VPC 내부 통신)
```

* 자연어 질의 → AI agent가 실제 SQL 생성 → 백엔드가 안전성 재검증(guardrail) → 읽기 전용 DB 실행 → 실행 결과 재검증(result_validator) → 결과를 SSE로 실시간 스트리밍 → 프론트엔드가 표+요약으로 표시.
* 세션 단위로 대화 히스토리를 기억해서 후속 질문("그 중에 1위만 알려줘")도 처리 가능.
* Defense-in-depth 설계: agent가 만든 SQL/결과를 그대로 신뢰하지 않고, `sql` 문자열만 받아 백엔드가 자체 검증·자체 실행·자체 결과검증까지 독립적으로 수행.
* (로컬 구현 완료, 커밋 보류) 재생성 피드백 루프 — guardrail/실행/결과검증 중 하나라도 실패하면 실패 이유를 agent에게 다시 전달해 최대 2회 재시도. agent와 정식 실패 피드백 파라미터를 상의하기 전까지 커밋을 보류하고 `_wip_query_with_retry_loop.py.txt`에 코드만 보관 중.
* **(완료·배포·프로덕션 검증 완료, 2026-07-13)** 세션 히스토리 전달 + 추천 후속 질문 — agent가 `session_id` 기준으로 자기 히스토리(성공한 턴만 최근 5개)를 직접 관리하고, 백엔드는 답변 성공 직후 별도로 `/api/v1/suggestions`를 호출해 추천 질문 2개를 받아온다. 프론트엔드는 이걸 클릭 가능한 칩으로 보여주고, 클릭하면 그 문구가 그대로 다음 질문이 되어 재요청된다. 자세한 내용은 6·7·9·10번 섹션 참고.
* **2026-07-12: 백엔드·AI agent를 Cloud Run에서 GCE VM(+VPC+External HTTPS LB) 기반으로 이전.** 프론트엔드는 그대로 Cloud Run에 남아있음. 자세한 내용은 4번·8번 섹션 참고.
* **2026-07-14 (권도윤): 프론트엔드 전면 재구성 + 스트리밍 계약 변경.** 단일 다크 채팅 화면을 홈/질문하기(Ask)/히스토리/저장 4화면 + 사이드바 구조로 재구성(새 npm 의존성 추가 없음). 동시에 백엔드에 `proxy.py`(agent의 `/api/v1/query/stream`·`/suggestions`·`/metrics`를 relay하는 라우터)가 추가되면서, 프론트는 이제 이 경로로 agent와 통신하고 기존 `/api/query`(백엔드 자체 guardrail 재검증+DB 재실행, defense-in-depth) 경로는 더 이상 직접 호출하지 않는다. `/api/query`는 코드에는 남아있지만 "레거시 게이트웨이"로만 존재한다. (아래 defense-in-depth 우회 항목 참고 — 같은 날 재검증 로직을 `proxy.py`에 다시 끼워넣어 해결) 자세한 내용은 3-2·3-3·6·7번 섹션 참고.
* **2026-07-14 (이후윤): 답변 텍스트 마크다운 렌더링 수정.** agent가 만드는 요약이 `**볼드**`, 번호 목록(`1. 2. 3.`) 같은 마크다운 문법을 쓰는데, 위 프론트엔드 재구성 직후에는 이걸 그대로 `<p>`에 찍고 있어 화면에 `**` 기호가 그대로 보이는 문제가 있었다. `react-markdown` 같은 새 라이브러리를 추가하지 않고, 필요한 패턴(볼드·코드·번호/불릿 목록)만 처리하는 경량 컴포넌트(`components/Markdown.jsx`)를 새로 만들어 해결. 자세한 내용은 7번 섹션 참고.
* **2026-07-14 (이후윤): `proxy.py`에 defense-in-depth 재검증 복구.** 위 프론트엔드 재구성으로 `/api/v1/query/stream` 경로가 백엔드의 guardrail 재검증·DB 재실행을 거치지 않게 된 것을 발견하고, `proxy.py`가 agent의 SSE 스트림을 이벤트 단위로 파싱하도록 고쳐서 `done` 이벤트만 가로채 `guardrail.py` 재검증 → 백엔드 자체 DB 재실행(`run_readonly_query_table`, 신규) → `result_validator.py` 재검증까지 다시 통과시킨 뒤 프론트로 전달하도록 수정했다. 재검증 실패 시 agent에게 재시도를 요청하지 않고(재생성 피드백 루프는 별도, 아직 로컬 전용) 레거시와 동일하게 즉시 error 이벤트로 종료한다. `node`/`error` 이벤트는 가공 없이 그대로 relay한다. 자세한 내용은 6·7·9·10번 섹션 참고.

---

## 2. 기술 스택

| 영역 | 기술 |
|---|---|
| 프론트엔드 | React 18 + Vite 5 (순수 CSS, 별도 UI 라이브러리 없음) — 홈/질문하기/히스토리/저장 4화면 구조(2026-07-14부터), 히스토리·저장은 localStorage — Cloud Run 배포 |
| 백엔드 | FastAPI + Pydantic + SQLAlchemy + psycopg2 + uvicorn — GCE VM 배포 (2026-07-12부터) |
| AI agent | LangGraph 기반 Text-to-SQL 파이프라인 (팀원 담당) — GCE VM 배포 (2026-07-12부터) |
| DB | Supabase (관리형 Postgres) |
| 컨테이너 | Docker — 백엔드: `python:3.11-slim` / 프론트엔드: `node:20-alpine`(빌드) + `nginx:1.27-alpine`(서빙) 멀티 스테이지 |
| 배포 인프라 (프론트엔드) | GCP Cloud Run (서버리스 컨테이너) |
| 배포 인프라 (백엔드·agent) | GCE VM(Container-Optimized OS, e2-small) + VPC 프라이빗 서브넷 + External HTTPS LB + Cloud NAT + Google-managed SSL |
| 이미지 저장소 | Artifact Registry (`text2sql-repo`) |
| CI/CD | GitHub Actions (WIF 인증) — 프론트엔드는 `gcloud run deploy`, 백엔드/agent는 `gcloud compute instances update-container` |
| 실시간 통신 | SSE(Server-Sent Events) — `fetch` + `ReadableStream`으로 프론트에서 직접 파싱. 2026-07-14부터 이벤트 계약이 `node`/`done`/`error`로 바뀜(agent 원본 계약을 백엔드가 그대로 relay) — 이전 `status`/`result`/`sql`/`done`/`error` 계약은 `/api/query`(레거시)에만 남아있음 |
| AI agent 연동 | httpx(비동기 HTTP 클라이언트) — VPC 내부 IP(`http://10.10.0.2:8001`)로 직접 호출 (2026-07-12부터, 이전에는 Cloud Run 공개 URL) |
| 관리자 접근 | IAP(Identity-Aware Proxy) SSH 터널링 — 프라이빗 VM에 공인 IP 없이 접속 |
| 버전 관리 | GitHub (fork: `Doyunamic-Kwon/edu-gachon2026-project`) |

---

## 3. 폴더/파일 구조

### 3-1. 로컬 작업 폴더 (`~/Claude/Projects/upstage/Text2SQL_project/`)

```
Text2SQL_project/
├── Backend/                      # 백엔드 원본 작업 폴더
├── Frontend/                     # 프론트엔드 원본 작업 폴더
├── edu-gachon2026-project/       # 실제 제출용 GitHub 레포 clone (여기서 커밋/푸시)
├── ci-cd-vm-drafts/              # VM 배포 전환용 워크플로우 초안 (2026-07-12, 반영 완료 후에도 참고용 보관)
├── Backend/mock_agent_for_local_test.py  # 히스토리/추천질문 로컬 테스트 전용 mock agent (커밋 대상 아님)
├── Backend/app/api/routes/_wip_query_with_retry_loop.py.txt  # 재생성 피드백 루프 WIP 보관 (커밋 대상 아님, 2026-07-13)
├── SERVER_HANDOFF.md             # 인프라/배포 상세 핸드오프 문서
├── DATA_SCHEMA.md                # Olist ERD, PK/FK 설계 문서
├── PROJECT_OVERVIEW.md           # 이 문서
├── mentoring_prep_2026-07-10.md  # 멘토링 예상 질문/답변 정리
└── daily_retrospective_*.md      # 일일 회고록
```

### 3-2. 백엔드 (`Backend/`, 레포 안에서는 `projects/team07-sequel/backend/`)

```
backend/
├── app/
│   ├── main.py                  # FastAPI 앱 생성, CORS, 라우터 등록, /health
│   ├── api/routes/
│   │   ├── query.py             # POST /api/query — 레거시 게이트웨이(자체 guardrail 재검증+DB 재실행, defense-in-depth). 2026-07-14부터 프론트가 더 이상 호출하지 않음
│   │   ├── proxy.py             # (신규, 2026-07-14) agent의 /api/v1/query/stream·/suggestions·/metrics를 relay. 지금 프론트가 실제로 쓰는 경로. query/stream은 이벤트 단위로 파싱해서 done만 가로채 guardrail.py+DB 재실행(run_readonly_query_table)+result_validator.py로 재검증(defense-in-depth 복구, 2026-07-14) — node/error는 그대로 relay
│   │   └── _wip_query_with_retry_loop.py.txt  # 재생성 피드백 루프 WIP 보관 (커밋 대상 아님)
│   ├── schemas/query.py         # 요청/응답 Pydantic 모델, SSE 이벤트·에러코드 상수
│   ├── services/
│   │   ├── agent_client.py      # AI agent 호출 어댑터 — session_id 기반 /api/v1/query 호출 + /api/v1/suggestions 별도 호출 (2026-07-13 실제 계약 반영)
│   │   ├── guardrail.py         # SQL 안전성 2차 검증 (SELECT/WITH 허용, 위험 키워드 차단, LIMIT 강제) — 실행 "전" 검사
│   │   └── result_validator.py  # 실행 결과 검증 (행 수/스키마/타입 일관성) — 실행 "후" 검사
│   ├── db/database.py           # Supabase(Postgres) 연결 및 조회 실행 — run_readonly_query(레거시, list[dict]), run_readonly_query_table(신규 2026-07-14, {columns,rows} 형태 — proxy.py 재검증용)
│   └── core/config.py           # 환경변수 로드 (AI_AGENT_BASE_URL, CORS_ALLOWED_ORIGINS 등)
├── tests/                       # pytest 자동화 테스트 (34개 전부 통과)
│   ├── test_guardrail.py        # SELECT/WITH 허용·위험 키워드 차단·LIMIT 강제 검증
│   └── test_result_validator.py # 행 수/스키마/타입 일관성 검증
├── pytest.ini                    # pythonpath=. 설정 (app.* import를 그대로 쓰기 위함)
├── requirements-dev.txt          # pytest 등 테스트 전용 의존성 (프로덕션 이미지엔 미포함)
├── requirements.txt
└── Dockerfile
```

> `session_store.py`/`test_session_store.py`는 2026-07-13에 삭제했습니다. agent가 이제 `session_id` 기준으로 자기 히스토리를 직접 관리해서, 백엔드 쪽에서 별도로 대화 이력을 저장해 agent에 넘길 필요가 없어졌기 때문입니다(9번 섹션 참고).

### 3-3. 프론트엔드 (`Frontend/`, 레포 안에서는 `projects/team07-sequel/frontend/`)

**2026-07-14에 권도윤 님이 4화면 구조로 전면 재구성했습니다** (기존 `src/api/queryStream.js` 기반 단일 다크 채팅 화면 → 아래 구조로 교체, npm 의존성은 그대로 0개 추가).

```
frontend/
├── index.html / vite.config.js / package.json
├── src/
│   ├── main.jsx                   # React 엔트리포인트
│   ├── App.jsx                    # 화면 전환(홈/질문하기/히스토리/저장) + streamQuery 호출·turns 상태 관리
│   ├── api.js                     # 백엔드(/api/v1) 호출 래퍼 — streamQuery(node/done/error 계약)·fetchSuggestions·fetchMetrics
│   ├── store.js                   # localStorage 기반 히스토리·저장 + CSV 내보내기 + 포맷 헬퍼(fmtInt/fmtCost/fmtLatency/relTime)
│   ├── index.css
│   ├── screens/
│   │   ├── Home.jsx               # 오늘의 KPI(/metrics), 최근 질문, 질문 예시 스타터
│   │   ├── Ask.jsx                # 질문 입력, 노드별 실시간 진행 상태, SQL 카드, 표/차트 토글, 후속질문 칩
│   │   ├── History.jsx            # localStorage 기반 히스토리 목록
│   │   └── Saved.jsx              # localStorage 기반 저장(★) 목록
│   └── components/
│       ├── Sidebar.jsx            # 좌측 네비게이션(홈/질문하기/히스토리/저장)
│       ├── SqlCard.jsx            # 생성된 SQL 구문 강조 카드
│       ├── ResultTable.jsx        # 결과 표 렌더링
│       ├── ResultChart.jsx        # 숫자 컬럼 있을 때 결과 차트 토글
│       └── Markdown.jsx           # (신규, 2026-07-14, 이후윤) agent 응답의 마크다운(볼드·코드·번호/불릿 목록)을 실제로 렌더링 — 새 의존성 없이 정규식만으로 처리
├── Dockerfile                     # 멀티 스테이지 (node 빌드 → nginx 서빙)
├── nginx.conf                     # 8080 포트 리스닝 + SPA fallback
└── .dockerignore
```

> 참고: `App.jsx`에는 `?mock=1` 쿼리 파라미터로 백엔드 없이 마크다운 렌더링을 눈으로 확인할 수 있는 테스트용 `useEffect` 블록이 로컬에만 남아있습니다(주석 `⚠️ 테스트용` 표시, 커밋 대상 아님 — GitHub에는 올라가 있지 않습니다).

### 3-4. GitHub 레포 브랜치 구조

* `Backend`, `Fontend`: 각자 작업하는 브랜치
* `main`: 실제 배포 기준 브랜치 (CI/CD가 여기만 감시함)
* `aiagent`: 팀원의 AI agent 작업 브랜치 → PR #1로 `main`에 병합 완료 (2026-07-10), 실제 동작하는 Text-to-SQL agent 코드로 확인됨
* 코드 경로: `projects/team07-sequel/backend/`, `projects/team07-sequel/frontend/`, `projects/team07-sequel/app/`(agent)
* CI/CD 관련 워크플로우 파일(`deploy-*.yml`)은 브랜치 구분 없이 `main`에 직접 반영해온 경우가 많음(공유 인프라 설정이라)

---

## 4. 서버 인프라 접근 방법

| 항목 | 값 |
|---|---|
| GCP 프로젝트 ID | `clean-skill-501705-t4` |
| 리전 | `asia-northeast3` (서울) — VM 존은 `asia-northeast3-a` |
| Artifact Registry | `text2sql-repo` |
| CI/CD 서비스 계정 | `github-deployer@clean-skill-501705-t4.iam.gserviceaccount.com` (`run.admin`, `artifactregistry.writer`, `iam.serviceAccountUser`, `compute.instanceAdmin.v1`, `iap.tunnelResourceAccessor` 권한 보유 — 뒤 두 개는 2026-07-12 VM 마이그레이션 때 추가) |
| VM 런타임 서비스 계정 | `text2sql-vm-runtime@clean-skill-501705-t4.iam.gserviceaccount.com` (`artifactregistry.reader`, `logging.logWriter`) |

### 4-1. 프론트엔드 (Cloud Run, 변경 없음)

* `https://text2sql-frontend-bfkt3wk5mq-du.a.run.app`
* GCP 콘솔에서는 구형 URL(`https://text2sql-frontend-267324339574.asia-northeast3.run.app`)도 같은 서비스를 가리키지만, 백엔드 CORS 허용 목록에 신형 URL만 등록돼 있어 구형 URL로 접속하면 `Failed to fetch`가 납니다. **항상 신형 URL(`bfkt3wk5mq`)만 사용하세요.**

### 4-2. 백엔드·AI agent (2026-07-12부터 GCE VM + VPC + External HTTPS LB)

기존에는 백엔드(`text2sql-backend`)와 agent(`text2sql-agent`)가 각각 Cloud Run 서비스였으나, 2026-07-12에 아래 구조로 전환하고 **기존 Cloud Run 서비스 두 개는 삭제**했습니다.

```
[사용자/프론트엔드] → https://34-96-92-28.nip.io (External HTTPS LB, Google-managed SSL)
        │
[VPC: text2sql-vpc / 서브넷: text2sql-subnet(10.10.0.0/24), asia-northeast3]
        │
        ├─ GCE VM: text2sql-backend-vm (10.10.0.3, e2-small, 포트 8080)
        └─ GCE VM: text2sql-agent-vm  (10.10.0.2, e2-small, 포트 8001)
        │
   Cloud NAT(text2sql-nat) → 외부(Supabase, Upstage LLM API, Langfuse)로 아웃바운드
```

| 리소스 | 이름 |
|---|---|
| VPC | `text2sql-vpc` (custom mode) |
| 서브넷 | `text2sql-subnet` (`10.10.0.0/24`, Private Google Access 활성화) |
| Cloud Router / NAT | `text2sql-router` / `text2sql-nat` |
| 백엔드 VM | `text2sql-backend-vm` (내부 IP `10.10.0.3`, 외부 IP 없음) |
| agent VM | `text2sql-agent-vm` (내부 IP `10.10.0.2`, 외부 IP 없음) |
| 헬스체크 | `text2sql-backend-hc` (`/health`, 8080) |
| Instance Group | `text2sql-backend-ig` (unmanaged, `text2sql-backend-vm` 포함) |
| 백엔드 서비스 | `text2sql-backend-service` |
| LB 고정 IP | `text2sql-lb-ip` → `34.96.92.28` |
| LB 도메인 | `34-96-92-28.nip.io` (도메인 없이 IP 기반 무료 DNS로 HTTPS 구성, nip.io가 자동으로 이 이름을 IP로 매핑) |
| SSL 인증서 | `text2sql-lb-cert` (Google-managed, `ACTIVE`) |
| 방화벽 규칙 | `allow-lb-health-check`(LB 헬스체크), `allow-internal`(서브넷 내부 통신), `allow-iap-ssh`(관리자 SSH) |

**최종 공개 주소**: `https://34-96-92-28.nip.io` (백엔드 API, 프론트엔드가 이 주소로 SSE 호출)

**agent VM 환경변수** (`text2sql-agent-vm`, `--container-env-file`로 관리)

| 변수 | 용도 |
|---|---|
| `PORT` | `8001` |
| `SUPABASE_DB_URL`, `UPSTAGE_API_KEY` | DB 접속, LLM API 인증 |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Langfuse 트레이싱 연동 (`https://jp.cloud.langfuse.com`) |
| `CORS_ORIGINS` | JSON 배열 형식 필수(`["https://..."]`), pydantic-settings가 리스트로 파싱 |
| `MODEL_EASY`, `MODEL_MEDIUM`, `MODEL_HARD`, `MODEL_EXTRA_HARD` | 난이도별 라우팅 모델 (2026-07-13 추가, 현재 전부 `solar-pro2`) |

값을 바꿀 땐 기존 값을 전부 포함한 새 env 파일을 만들어 `gcloud compute instances update-container text2sql-agent-vm --container-env-file=<파일>`로 반영해야 합니다 — 이 옵션은 파일 내용으로 전체를 교체하는 방식이라 기존 값을 빠뜨리면 사라집니다(9번 섹션 참고).

**관리자 접근(SSH)**: 정식 Cloud VPN 대신, GCP의 IAP 터널링으로 충분합니다 (VM에 공인 IP가 없어도 안전하게 접속 가능).

```bash
gcloud compute ssh text2sql-backend-vm --zone=asia-northeast3-a --tunnel-through-iap --project=clean-skill-501705-t4
gcloud compute ssh text2sql-agent-vm --zone=asia-northeast3-a --tunnel-through-iap --project=clean-skill-501705-t4
```

**VM 상태/헬스체크 확인**

```bash
gcloud compute instances list --project=clean-skill-501705-t4
gcloud compute backend-services get-health text2sql-backend-service --global --project=clean-skill-501705-t4
gcloud compute ssl-certificates describe text2sql-lb-cert --global --format="value(managed.status)"
```

**GCP 콘솔/로그 접근**: 팀원에게 프로젝트 소유자(Owner) 권한을 부여해서(2026-07-10, Console 초대 방식) Cloud Run/Compute/로그/IAM 등 프로젝트 전 영역에 나와 동등하게 접근 가능. 개인 계정으로 콘솔 로그인 후 프로젝트 선택기에서 `clean-skill-501705-t4`(My Project 2785) 선택하면 됨.

---

## 5. DB(Supabase) 접근 방법

| 항목 | 값 |
|---|---|
| 프로젝트 ref | `aktpihqadgqmqumricbm` |
| 연결 호스트 | `aws-0-ap-northeast-1.pooler.supabase.com:5432` (Session Pooler, 반드시 이걸로 접속 — Direct connection은 IPv6 전용이라 실패 가능) |
| 관리자 계정 | `postgres` (스키마 변경용) |
| 앱이 쓰는 계정 | `text2sql_reader` (SELECT만 가능, 코드/배포 환경 모두 이 계정 사용) |

```bash
psql "postgresql://text2sql_reader.aktpihqadgqmqumricbm:<비밀번호>@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
```

Supabase 대시보드(https://supabase.com/dashboard) → `text2sql` 프로젝트 → SQL Editor에서 관리자 권한으로 직접 조회도 가능.

**적재된 데이터**: Olist 브라질 이커머스 9개 테이블(PK/FK 적용 완료), Telco Churn, CS 티켓 — 총 11개 테이블. 상세 ERD는 `DATA_SCHEMA.md` 참고.

> 2026-07-12부터 백엔드/agent가 GCE VM에서 Cloud NAT를 거쳐 이 DB에 접속합니다(이전에는 Cloud Run에서 직접 접속). 접속 계정·권한·연결 문자열은 전혀 바뀌지 않았습니다.

---

## 6. 백엔드 사용 방법

**API 스펙**

```
POST /api/query
{ "question": "카테고리별 주문 수 알려줘", "session_id": "abc-123" }
```

SSE 응답 이벤트: `status`(진행상황) → `result`(표+요약+추천 후속 질문) → `sql`(실행된 SQL) → `done`(종료) / 실패 시 `error`.

에러 코드(`ErrorCode`): `VALIDATION_FAILED`(SQL 안전성 위반), `NO_RESULT`(조건에 맞는 결과 없음), `AMBIGUOUS_QUESTION`(질문 모호), `RESULT_VALIDATION_FAILED`(실행 결과 스키마/타입 이상), `INTERNAL_ERROR`(그 외).

환경변수 `AI_AGENT_BASE_URL` — **2026-07-12부터 VPC 내부 IP(`http://10.10.0.2:8001`)로 설정.** 이전에는 agent의 Cloud Run 공개 URL이었으나, 같은 VPC 서브넷 안에서 프라이빗하게 통신하도록 바뀌었습니다.

**세션 히스토리 전달 + 추천 후속 질문 (완료·배포·프로덕션 검증 완료, 2026-07-13)**

권도윤 님이 병합한 `docs/api.md`를 확인해서 처음 가정했던 것과 다른 실제 계약에 맞게 구현했습니다.

* **히스토리는 백엔드가 만들어 보내지 않습니다.** agent가 `session_id` 기준으로 자기 쪽에서 히스토리(성공한 턴만 최근 5개, 30분 idle 시 만료)를 직접 관리합니다. 백엔드는 `/api/v1/query` 요청에 `session_id`만 그대로 실어 보냅니다.
* **추천 질문은 `/api/v1/query` 응답에 포함되지 않습니다.** 완전히 별도의 `POST /api/v1/suggestions` 엔드포인트를, 답변이 성공한 "직후"에 같은 `session_id`로 호출해서 받아옵니다.

```
POST /api/v1/query
  요청: {"question": "...", "session_id": "..."}
  응답: {"sql": "...", "summary": "...", "columns": [...], "rows": [...], "difficulty": "...", "model": "...", "error": ""}

POST /api/v1/suggestions   (query 성공 직후, 같은 session_id로 별도 호출)
  요청: {"session_id": "..."}
  응답: {"suggestions": ["...", "..."]}   # 0~2개, 빈 배열도 정상(직전 턴 없음/실패/LLM이 추천 못 찾음)
```

`agent_client.py`의 `ask_ai_agent(question, session_id)`와 `fetch_suggestions(session_id)`가 이 두 호출을 각각 담당합니다. `fetch_suggestions` 호출이 실패해도(네트워크 등) 추천 질문은 부가 기능이라 전체 요청을 실패시키지 않고 빈 배열로 처리합니다.

로컬 테스트용 `Backend/mock_agent_for_local_test.py`도 이 실제 계약(별도 `/suggestions` 엔드포인트, `session_id` 기반 자체 히스토리)에 맞게 다시 만들어뒀습니다.

**안전장치 (guardrail.py) — 실행 "전" 검사**

AI agent가 생성한 SQL을 그대로 실행하지 않고, 실행 전에 아래를 검사합니다.

* `SELECT` 또는 `WITH`(CTE)로 시작하지 않으면 차단
* `INSERT`/`UPDATE`/`DELETE`/`DROP`/`ALTER`/`TRUNCATE`/`CREATE`/`GRANT`/`REVOKE` 키워드가 어디에(서브쿼리·CTE 내부 포함) 있든 포함되면 차단
* `LIMIT`이 없으면 기본값(`LIMIT 200`)을 자동으로 붙임

DB 연결 자체도 읽기 전용 계정(`text2sql_reader`)이라 쓰기 쿼리는 DB 레벨에서도 이중으로 막힙니다. 실행 "후" 검사는 `result_validator.py`가 담당합니다.

**로컬 실행**

```bash
cd Backend
pip install -r requirements.txt
export SUPABASE_DB_URL="postgresql://text2sql_reader.aktpihqadgqmqumricbm:<비밀번호>@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"
uvicorn app.main:app --reload --port 8080
```

**히스토리/추천 질문 로컬 테스트 (mock agent 사용)**

실제 agent 없이 이 기능만 따로 확인하고 싶으면 `mock_agent_for_local_test.py`를 함께 띄우면 됩니다.

```bash
cd Backend
python3 -m uvicorn mock_agent_for_local_test:app --port 8001 --reload   # 별도 터미널
export AI_AGENT_BASE_URL="http://localhost:8001"                        # 백엔드 실행 전에 설정
```

mock은 실제 agent처럼 `session_id`별로 마지막 성공 턴을 기억해뒀다가, `/api/v1/suggestions` 호출 시 그 턴을 참고해 추천 질문 2개를 돌려줍니다. 2026-07-13에 mock의 SQL이 실제 스키마(`olist_order_items`에 없는 `product_category` 컬럼을 참조)와 맞지 않아 `RESULT_VALIDATION_FAILED`류 오류가 났던 적이 있는데, `olist_products`와 JOIN하도록 수정해서 해결했습니다(9번 섹션 참고).

**테스트 실행** (34개 전부 통과)

```bash
cd Backend
pip install -r requirements-dev.txt
pytest -v
```

**Docker 실행**

```bash
cd Backend
docker build -t text2sql-backend .
docker run -p 8080:8080 --env-file .env text2sql-backend
curl http://localhost:8080/health   # {"status":"ok"}
```

> 참고: 헬스체크 경로는 `/health`입니다(`/healthz` 아님). 원래 Cloud Run(Knative)이 `/healthz`를 내부적으로 예약해서 쓰는 문제 때문에 이렇게 정했는데, 2026-07-12에 백엔드가 GCE VM으로 옮겨가면서 이 제약 자체는 더 이상 적용되지 않습니다. 다만 이름은 그대로 `/health`로 유지하고 있습니다(LB 헬스체크도 이 경로를 봄).

---

## 7. 프론트엔드 사용 방법

**화면 구성 (2026-07-14부터, 권도윤)**

좌측 사이드바(`Sidebar.jsx`)로 4개 화면을 전환하는 구조입니다.

| 화면 | 파일 | 내용 |
|---|---|---|
| 홈 | `screens/Home.jsx` | 오늘의 KPI(`/api/v1/metrics`, Langfuse 집계 프록시), 최근 질문(localStorage), 질문 예시 스타터 |
| 질문하기(Ask) | `screens/Ask.jsx` | 질문 입력, 노드별 실시간 진행 문구, SQL 카드(`SqlCard.jsx`), 결과 표/차트 토글, 지연·토큰·비용 메타, 후속 질문 칩, CSV 내보내기 |
| 히스토리 | `screens/History.jsx` | 지금까지 물어본 질문 목록 (localStorage) |
| 저장 | `screens/Saved.jsx` | ★ 저장한 질문 목록 (localStorage) |

**백엔드와 통신하는 방식 (2026-07-14부터 계약 변경)**

브라우저 기본 `EventSource`는 GET 요청만 지원해서 POST 바디(질문 내용)를 보낼 수 없습니다. 그래서 `src/api.js`의 `streamQuery`가 `fetch` + `ReadableStream`으로 SSE 프레이밍(`event: ...\ndata: ...\n\n`)을 직접 파싱합니다.

**중요한 변화**: 이전에는 프론트가 백엔드 자체 게이트웨이(`POST /api/query`, `status`/`result`/`sql`/`done`/`error` 계약)를 호출했지만, 지금은 `POST /api/v1/query/stream`을 호출합니다. 이벤트 계약은 agent 원본 그대로인 `node`/`done`/`error` 3종입니다(`api.js`가 다시 `status`/`route`/`tables`/`done`/`error`로 가공해서 `Ask.jsx`에 넘김).

이 경로는 백엔드의 `proxy.py`가 처리하는데, 4화면 재구성 직후에는 agent의 스트림을 청크 단위로 그대로 흘려보내기만 해서 **백엔드 자체의 guardrail 재검증·DB 재실행(defense-in-depth)을 거치지 않는** 문제가 있었습니다. **2026-07-14에 이를 복구**해서, 지금은 `proxy.py`가 SSE를 이벤트 단위로 파싱해 `node`/`error`는 그대로 relay하되 `done`만 가로채 (1) `guardrail.py` 재검증 → (2) 백엔드 자체 DB 재실행(`run_readonly_query_table`, 읽기 전용 계정) → (3) `result_validator.py` 재검증까지 다시 통과시킨 뒤, 그 결과(재실행된 표로 교체됨)를 `done`으로 내보냅니다. 재검증에 실패하면 agent에게 재시도를 요청하지 않고(재생성 피드백 루프는 별도 기능, 아직 로컬 전용) 레거시 `/api/query`와 동일하게 즉시 `error` 이벤트로 종료합니다.

| agent 이벤트 | 화면 반응 |
|---|---|
| `node` (normalize/schema_link/route/generate/validate/execute/format 등) | `Ask.jsx` 상태 표시줄에 "SQL을 생성하는 중…" 같은 노드별 진행 문구 표시. `route` 노드에서는 난이도·모델도 함께 표시 |
| `done` | 백엔드가 재검증·재실행까지 마친 최종 `{summary, table, sql, meta}` — 답변 요약(`Markdown.jsx`로 렌더링)·결과 표·SQL 카드·지연/토큰/비용 메타 표시 |
| `error` | agent 자체 오류 또는 백엔드 재검증 실패 메시지를 에러 전용 스타일로 표시 |

옛 `/api/query`(`status`/`result`/`sql`/`done`/`error` 계약)는 백엔드 코드에 "레거시 게이트웨이"로 남아있지만, 지금 배포된 프론트엔드는 더 이상 호출하지 않습니다.

세션 식별자(`session_id`)는 브라우저 탭을 새로고침하기 전까지 하나로 유지되며, 후속 질문("그 중에 1위만 알려줘" 등) 시 agent가 이전 대화 맥락을 이어갈 수 있도록 매 요청에 함께 전달됩니다.

**답변 텍스트 마크다운 렌더링 (신규, 2026-07-14, 이후윤)**

agent가 만드는 요약은 `**볼드**`, 번호 목록(`1. 2. 3.`) 같은 마크다운 문법을 자연스럽게 씁니다. `components/Markdown.jsx`가 이걸 실제로 렌더링합니다 — `react-markdown` 등 새 라이브러리 없이, 정규식으로 `**볼드**`/`` `코드` ``를 인식하고, 줄바꿈 없이 이어져도 숫자가 1부터 순서대로 나오면 번호 목록으로, `-`/`*`로 시작하면 불릿 목록으로 인식합니다. `Saved.jsx`의 한 줄 미리보기 카드는 블록 렌더링 대신 `stripMarkdown()`으로 기호만 제거해서 보여줍니다.

**추천 후속 질문 칩 (완료·배포·프로덕션 검증 완료, 2026-07-13)**

`done` 이벤트로 답변이 완료된 직후 `fetchSuggestions(session_id)`를 별도 호출해서 받아온 배열(보통 2개)을 `Ask.jsx`의 `followups`로 답변 아래 클릭 가능한 pill 버튼으로 렌더링합니다. 클릭하면 입력창 문구가 채워지고, 그대로 새 질문으로 보낼 수 있습니다. 스트리밍 중에는 입력이 비활성화됩니다.

**로컬 실행 (개발 모드, HMR 지원)**

```bash
cd Frontend
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000 (백엔드를 다른 포트로 띄웠다면 그 포트로 수정)
npm install
npm run dev             # http://localhost:5173
```

마크다운 렌더링처럼 백엔드 없이 화면만 빠르게 확인하고 싶을 때는 `http://localhost:5173/?mock=1`로 접속하면 됩니다(위 3-3 참고 — 로컬 전용, 커밋되지 않음).

**프로덕션 빌드 (배포 없이 빌드 결과만 확인)**

```bash
npm run build     # dist/ 에 정적 파일 생성
npm run preview   # 빌드 결과 미리보기
```

**Docker 실행 (배포 환경과 동일하게 검증)**

Vite는 환경변수를 빌드 시점에 파일에 박아넣기 때문에, 백엔드 URL은 런타임이 아니라 빌드 인자로 넘겨야 합니다.

```bash
cd Frontend
docker build -t text2sql-frontend --build-arg VITE_API_BASE_URL=http://localhost:8000 .
docker run -p 5173:8080 text2sql-frontend   # http://localhost:5173
```

로컬 백엔드(Docker 또는 uvicorn)가 같이 떠 있어야 실제 질문 테스트가 가능합니다.

**실제 배포 시 백엔드 주소** (2026-07-12부터)

```
VITE_API_BASE_URL=https://34-96-92-28.nip.io
```

이전에는 CI/CD가 매번 `gcloud run services describe text2sql-backend`로 백엔드의 Cloud Run URL을 조회해서 자동으로 넣어줬지만, 백엔드가 Cloud Run에서 빠지면서 이 조회 로직은 더 이상 쓸 수 없습니다. 지금은 LB의 고정 도메인(`34-96-92-28.nip.io`)을 워크플로우에 직접 고정값으로 넣고 있습니다(8번 섹션 참고).

**Mixed Content 이슈 (2026-07-12에 발견·해결)**: 프론트엔드는 Cloud Run이라 항상 HTTPS로 서빙됩니다. 백엔드 LB를 HTTP로만 만들면, HTTPS 페이지의 JS가 HTTP로 fetch를 보내는 걸 브라우저가 Mixed Content로 차단합니다. 그래서 도메인 없이도 HTTPS를 쓸 수 있는 `nip.io` 무료 DNS + Google 관리형 SSL 인증서로 LB를 HTTPS로 구성해서 해결했습니다.

---

## 8. CI/CD 사용 방법

**흐름**

```
Backend/Fontend 브랜치에서 작업·commit (agent 관련은 main에 직접 반영하는 경우도 있음)
        ↓
main으로 merge & push
        ↓
GitHub Actions 트리거 (push to main)
        ↓
WIF로 GCP 인증 → Docker 이미지 빌드 → Artifact Registry push
        ↓
   ┌─── 프론트엔드: gcloud run deploy (Cloud Run)
   └─── 백엔드·agent: gcloud compute instances update-container (GCE VM 이미지만 교체)
```

* 워크플로우 파일: `.github/workflows/deploy-backend.yml`("Deploy Backend to GCE VM"), `deploy-agent.yml`("Deploy Agent to GCE VM"), `deploy-frontend.yml`("Deploy Frontend to Cloud Run")
* 트리거 조건: `main` 브랜치에 push되고, 각각 `projects/team07-sequel/backend/**`, `projects/team07-sequel/app/**`(agent), `frontend/**` 등 경로가 변경됐을 때만 실행
* **백엔드/agent 배포 방식 변경(2026-07-12)**: 기존 `gcloud run deploy` 대신 `gcloud compute instances update-container <VM> --container-image=<새 이미지>`로 VM의 컨테이너 이미지만 교체합니다. VM 생성 시 설정해둔 환경변수(`--container-env`)는 그대로 유지되고 이미지만 바뀝니다.
* **agent 배포는 헬스체크에 재시도 로직이 있습니다**: agent는 시작할 때 스키마 임베딩 인덱스를 새로 만들어서 기동에 시간이 걸릴 수 있어, 배포 직후 곧바로 확인하면 실패할 수 있습니다. 그래서 최대 6회(10초 간격, 총 1분)까지 재시도한 뒤에 최종 실패 처리합니다.
* 프론트엔드 워크플로우는 더 이상 백엔드 URL을 동적으로 조회하지 않고, LB 고정 도메인(`https://34-96-92-28.nip.io`)을 빌드 인자로 고정해서 넣습니다.
* agent 워크플로우는 GitHub Secrets(`SUPABASE_DB_URL`, `UPSTAGE_API_KEY`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL`)를 VM 생성 시점에 이미 `--container-env-file`로 심어뒀기 때문에, 배포 워크플로우 자체에서는 더 이상 이 값들을 다시 넘기지 않습니다(예전 Cloud Run 방식은 매 배포마다 `--set-env-vars`로 다시 넘겼었음).
* **VM 배포에 필요한 IAM 권한**: `github-deployer` 서비스 계정에 `roles/compute.instanceAdmin.v1`(컨테이너 이미지 교체용), `roles/iap.tunnelResourceAccessor`(헬스체크용 SSH 터널 인증용)를 추가해야 합니다.

**배포 결과 확인**: GitHub 저장소 → Actions 탭 → `Deploy Backend to GCE VM` / `Deploy Agent to GCE VM` / `Deploy Frontend to Cloud Run`에서 성공/실패 및 로그 확인.

**주의사항**: `Backend`/`Fontend`에 아무리 커밋해도 그 자체로는 배포가 안 됩니다. 반드시 `main`으로 merge(단순 commit이 아니라 다른 브랜치 내용을 합치는 작업)해야 워크플로우가 트리거됩니다.

---

## 9. 지금까지 확인된 이슈와 해결 (알아두면 좋은 것)

| 이슈 | 원인 | 해결 |
|---|---|---|
| `aiagent` 브랜치 스펙으로 실제 연동했다가 롤백 (이후 재확인해서 재연동) | 처음엔 `docs/api.md`가 강사 제공 벤치마킹 예시 코드로 보여 mock으로 롤백했으나, 이후 스테일(오래된) git 클론을 보고 판단한 것이었음이 드러남 | 최신 클론으로 다시 확인한 결과 실제 동작하는 Text-to-SQL agent 코드로 확인, `agent_client.py`를 실제 HTTP 연동으로 교체 완료 |
| Cloud Run에서 `/healthz` 요청 시 구글 기본 404 | Cloud Run(Knative)의 queue-proxy 사이드카가 `/healthz`를 자체적으로 가로챔 | 엔드포인트명을 `/health`로 변경 (2026-07-12 VM 이전 후에는 이 제약 자체가 사라졌지만 이름은 유지) |
| Docker 이미지가 코드 수정 반영 안 함 | 이미지는 빌드 시점 스냅샷이라 재빌드 필요 | `docker build` 재실행 후 재기동 |
| npm/rollup 크로스플랫폼 에러 | Linux 샌드박스에서 설치한 `node_modules`가 Mac과 안 맞음 | Mac에서 직접 `rm -rf node_modules package-lock.json && npm install` |
| Git 커밋 시 vi 에디터가 멈춤 | 병합 커밋 메시지 작성용 에디터 설정 문제 | `git commit --no-edit`로 에디터 없이 기본 메시지로 커밋 |
| `main` 로컬 브랜치가 크게 뒤처져 있으면 오래된 내용을 최신으로 착각 | 로컬/샌드박스 클론이 `git pull` 실패(권한/lock 이슈)로 멈춰있는데 모르고 판단 | 중요한 판단 전엔 `git status`로 뒤처짐 확인, 필요하면 새로 clone |
| `auto-label-team.yml`이 403 에러 (`Resource not accessible by integration`) | 워크플로우 권한이 `pull-requests: read`로만 설정돼 라벨 추가에 필요한 `write` 부족 | `pull-requests: write`로 수정. 이미 열려있던 PR은 "Re-run jobs"로 반영 안 되고, PR을 닫았다 다시 열어야(reopened 이벤트) 재실행됨 |
| AI agent가 Cloud Run에서 시작 직후 죽음 (`pydantic_settings.exceptions.SettingsError`) | `.env.example`의 `CORS_ORIGINS=http://localhost:5173`가 리스트 타입 필드인데 JSON 배열 형식이 아니어서 파싱 실패 | `.env.example`을 `CORS_ORIGINS=["http://localhost:5173"]`처럼 JSON 배열 형식으로 수정 |
| 팀원에게 Owner 권한 부여 시 `gcloud ... --role=roles/owner`가 `SOLO_MUST_INVITE_OWNERS`로 실패 | GCP는 첫 Owner 부여를 CLI로 바로 못하게 막고, Console 초대·수락 절차를 요구함 | GCP Console → IAM → "액세스 권한 부여"로 초대, 팀원이 이메일 초대 수락 |
| "카테고리별 매출 알려줘" 같은 집계 질문이 `VALIDATION_FAILED`("SELECT로 시작하는 조회 쿼리만 허용됩니다")로 차단됨 | `guardrail.py`가 `SELECT`로 시작하는 쿼리만 허용했는데, agent가 복잡한 집계는 `WITH ... AS (...) SELECT ...`(CTE) 형태로 생성 — 안전한 읽기 전용 쿼리인데 오탐 차단됨 | `WITH`로 시작하는 쿼리도 허용하도록 정규식 수정, pytest 2개 추가 후 배포·재확인 완료 |
| `gcloud compute instances create-with-container`의 `--container-env`에 콤마 포함된 값(예: `CORS_ALLOWED_ORIGINS`)을 넣으면 파싱 에러 | `--container-env`는 콤마를 "다음 키=값 쌍 구분자"로 해석해서, 값 안의 콤마와 충돌 | `--container-env-file`로 파일에서 줄바꿈 기준으로 읽어오는 방식으로 변경 |
| CI에서 `gcloud compute ssh --tunnel-through-iap` 실행 시 "not authorized"(에러코드 4033) | 방화벽 규칙(`allow-iap-ssh`)은 열려 있었지만, `github-deployer` 서비스 계정에 IAP 터널 사용에 필요한 IAM 권한(`roles/iap.tunnelResourceAccessor`)이 없었음 — 방화벽 규칙과 IAM 권한은 별개로 필요 | `github-deployer`에 `roles/iap.tunnelResourceAccessor` 역할 추가 |
| agent 배포 직후 헬스체크가 `curl: (7) Failed to connect`로 실패 | agent 컨테이너가 재시작될 때마다 스키마 임베딩 인덱스를 새로 빌드하는데, 이게 15초보다 오래 걸릴 수 있어서 헬스체크가 너무 일찍 확인함 | 헬스체크를 최대 6회(10초 간격, 총 1분) 재시도하는 로직으로 변경 |
| HTTPS 프론트엔드(Cloud Run)에서 HTTP LB로 fetch 시 Mixed Content로 브라우저가 차단할 위험 | 도메인이 없어 LB를 HTTP로만 구성했는데, 프론트는 항상 HTTPS로 서빙됨 | `nip.io`(무료 IP 기반 DNS) + Google 관리형 SSL 인증서로 LB를 HTTPS로 구성 (`https://34-96-92-28.nip.io`) |
| 프론트엔드의 구형 Cloud Run URL(`-267324339574.asia-northeast3.run.app`)로 접속하면 `Failed to fetch` | 신형/구형 URL은 같은 서비스를 가리키지만 브라우저 입장에선 다른 Origin이라, 백엔드 `CORS_ALLOWED_ORIGINS`에 등록 안 된 구형 URL의 요청은 CORS로 차단됨 | 서비스에 영향 없다고 판단, 신형 URL(`bfkt3wk5mq`)만 공식 주소로 계속 사용하기로 결정 (허용 목록에 구형 URL을 추가하는 것도 가능하지만 불필요하다고 판단) |
| macOS에서 Python 가상환경(`.venv`) 만들 때 `pip install -r requirements.txt`가 `pydantic-core` 빌드 중 `crates.io` 접속 실패로 실패 | `.venv`가 Python 3.14(너무 최신 버전)로 만들어져서 `pydantic-core`의 사전 빌드본이 없어 Rust(`maturin`/`cargo`)로 직접 컴파일을 시도하다가 발생 | Python 3.11(백엔드 Dockerfile과 동일 버전)로 가상환경을 다시 생성해서 사전 빌드본을 그대로 설치하도록 해결 |
| 추천 질문 로컬 테스트 중 결과 검증 실패(`쿼리 실행 중 오류가 발생했습니다`, 3회 재시도 후 최종 실패) | 로컬 테스트용 mock agent(`mock_agent_for_local_test.py`)가 반환한 SQL이 실제 스키마와 안 맞음 — `olist_order_items`에는 `product_category` 컬럼이 없고 `olist_products.product_category_name`에 있어서 JOIN이 필요했는데, mock SQL에 이 JOIN이 빠져 있었음 | mock SQL을 `olist_products`와 JOIN하도록 수정 — 실제 백엔드/agent 연동 로직 문제가 아니라 로컬 테스트용 mock 데이터 자체의 실수였음 |
| 세션 히스토리/추천 질문의 실제 agent API 계약이 처음 가정(placeholder)과 다름 | `history` 배열을 백엔드가 만들어 보낼 거라 가정했는데, 실제로는 agent가 `session_id` 기준으로 자기 히스토리를 직접 관리하고, 추천 질문도 `/query` 응답이 아니라 완전히 별도의 `/api/v1/suggestions` 엔드포인트였음 — `docs/api.md`를 실제로 확인하기 전까지는 몰랐음 | `agent_client.py`(`ask_ai_agent(question, session_id)`, `fetch_suggestions(session_id)` 신규), `schemas/query.py`(`AgentResult`에서 `suggested_questions` 제거), `query.py`(히스토리 구성 로직 제거, 성공 직후 `fetch_suggestions` 별도 호출) 재작성 |
| 재생성 피드백 루프와 세션 히스토리 기능이 `query.py` 한 파일에 얽혀 있어 하나만 골라 커밋하기 어려움 | 재생성 루프(재시도 for문)가 히스토리/추천질문 로직을 감싸는 구조였음 | 재생성 루프 코드를 잃어버리지 않게 `_wip_query_with_retry_loop.py.txt`(커밋 대상 아님)로 분리 보관하고, `query.py`는 재생성 루프 없이 단일 시도 + 실제 계약 반영 버전으로 되돌려서 커밋 |
| `session_store.py`가 더 이상 쓰이지 않게 됨 | agent가 `session_id`로 자기 히스토리를 직접 관리하게 되면서, 백엔드가 별도로 대화 이력을 저장해 agent에 넘길 필요가 없어짐 — `get_history()`를 쓰는 곳이 하나도 안 남음 | `session_store.py`와 `test_session_store.py` 삭제, pytest 39개 → 34개 |
| agent VM 환경변수 파일(`agent.env`) 작성 중 반복 실수 (`LANGFUSE_HOST`를 `LANGFUSE_BASE_URL`로 잘못 씀, 값에 불필요한 따옴표, `CORS_ORIGINS` 누락) | `--container-env-file`은 파일 내용으로 전체를 교체하는 방식이라 기존 값을 하나라도 빠뜨리거나 이름을 틀리면 그 값이 사라짐 | 매번 `gcloud compute instances describe`로 기존 값을 먼저 확인하고, 기존 값 전부 + 새 값을 합친 파일을 만들어서 반영 |
| 배포 직후 추천 질문 칩이 안 뜨다가 몇 분 뒤 정상적으로 뜸 | agent 컨테이너가 막 재시작된 직후라 `/api/v1/suggestions` 호출이 실패했을 가능성이 높음(임베딩 재빌드 등, 예전 헬스체크 지연과 같은 종류의 타이밍 문제) — 이 실패는 백엔드가 조용히 빈 배열로 처리하도록 설계돼 있어서 에러 없이 그냥 칩만 안 보임 | 몇 분 뒤 재시도해서 정상 동작 확인. 앞으로 배포 직후 바로 테스트하기보다 잠시 기다렸다 확인하는 습관 필요 |
| (2026-07-14) 답변 화면에 `**결론:**`, `1. 2. 3.` 같은 마크다운 기호가 그대로 노출 | 권도윤 님의 프론트엔드 재구성(`Ask.jsx`)이 `turn.summary`를 그대로 `<p>`에 출력 — agent 응답 자체는 마크다운 문법을 쓰는데 이를 해석해주는 코드가 없었음 | 새 의존성 추가 없이 정규식 기반 경량 렌더러 `components/Markdown.jsx` 작성, `Ask.jsx`/`Saved.jsx`에 적용 (3-3·7번 섹션 참고) |
| (2026-07-14 발견, 같은 날 해결) 프론트엔드 재구성 이후 백엔드의 defense-in-depth(`guardrail.py`+`result_validator.py`+자체 DB 재실행)가 실제로는 더 이상 타지 않게 됨 | 새 프론트(`api.js`)가 `/api/query`(레거시)가 아니라 `/api/v1/query/stream`(신규 `proxy.py`)을 호출하도록 바뀌었는데, 당시 `proxy.py`는 agent 응답을 청크 단위로 그대로 relay하기만 해서 재검증 코드를 타지 않았음 — 코드가 삭제된 건 아니라 조용히 우회된 것이라 알아채기 쉽지 않았음 | `proxy.py`를 SSE 이벤트 단위 파싱으로 바꿔서 `done` 이벤트만 가로채 `guardrail.py` 재검증 → 백엔드 자체 DB 재실행(`database.py`에 `run_readonly_query_table` 신규 추가) → `result_validator.py` 재검증까지 다시 통과시킨 뒤 relay하도록 수정. 재검증 실패 시 agent에게 재시도 요청 없이(재생성 피드백 루프는 별도, 로컬 전용 유지) 레거시와 동일하게 즉시 error로 종료. `node`/`error` 이벤트는 그대로 relay |

---

## 10. 현재 상태 / 남은 체크리스트

**완료된 것**

- [x] GCP 인프라(프로젝트/Artifact Registry) 구축
- [x] Supabase DB 적재 + 읽기 전용 계정 분리 + Olist 9개 테이블 PK/FK 적용
- [x] 백엔드 FastAPI 구현(SSE 스트리밍, 세션 히스토리, guardrail) + 로컬/Docker 테스트
- [x] 프론트엔드 React 채팅 UI 구현 + 로컬/Docker 테스트
- [x] 백엔드/프론트엔드 Dockerfile 작성 및 실행 검증
- [x] 브랜치 병합 흐름 확정 (`Fontend`/`Backend` → `main` 직행)
- [x] CI/CD 워크플로우 최초 구축 (2026-07-09, 당시엔 세 서비스 모두 Cloud Run 배포)
- [x] CORS를 실제 프론트엔드 URL로 제한
- [x] AI agent 실제 코드가 `main`에 병합됨을 확인, 실제 연동 완료 — `agent_client.py`가 mock에서 실제 HTTP 호출로 교체됨
- [x] 결과 검증(행 수/스키마/타입 재확인) 로직 추가 — `result_validator.py` 신규 분리(guardrail.py와 책임 구분: SQL 안전성 vs 실행 결과 타당성)
- [x] `UPSTAGE_API_KEY`, Langfuse 키 등록 완료 — GitHub Actions repository secrets로 등록 (MVP 수준에서는 GCP Secret Manager 없이 충분하다고 판단)
- [x] pytest 자동화 테스트 작성 — `guardrail.py`(20개), `session_store.py`(5개), `result_validator.py`(10개) 총 39개 전부 통과 (2026-07-13에 `session_store.py`가 삭제되면서 34개로 조정, 아래 참고)
- [x] guardrail의 WITH(CTE) 쿼리 오탐 차단 버그 수정 — "카테고리별 매출" 등 집계 질문이 정상 동작하도록 수정
- [x] **서버 인프라를 GCE VM + VPC + External HTTPS LB 기반으로 전환 (2026-07-12)** — VPC/서브넷/방화벽 구성 → Cloud NAT/Router 구성 → 백엔드·agent VM 생성 및 헬스체크 확인 → Instance Group/백엔드 서비스 등록 → External HTTPS LB(nip.io + Google-managed SSL) 구성 → 관리자 접근은 IAP SSH로 충분하다고 판단해 별도 Cloud VPN은 구축하지 않음 → 프론트엔드가 새 LB 주소를 쓰도록 교체·재배포 → CI/CD를 `update-container` 방식으로 전환 → 실제 브라우저 엔드투엔드 검증 완료 → **기존 Cloud Run `text2sql-backend`/`text2sql-agent` 서비스 삭제**
- [x] 팀원 GCP 권한을 이후윤 님과 동등하게 동기화 (2026-07-13) — IAM에 `IAP-Secured Tunnel User`, `Compute OS Admin Login` 부여(Owner 권한과 별개로 명시적으로 추가), IAP SSH로 VM 접속 가능 확인
- [x] agent 모델 라우팅 환경변수 추가 (2026-07-13) — `MODEL_EASY`/`MODEL_MEDIUM`/`MODEL_HARD`/`MODEL_EXTRA_HARD`를 agent VM에 반영, 헬스체크로 정상 동작 확인
- [x] **세션 히스토리 전달 + 추천 후속 질문 기능 완료 (2026-07-13)** — 권도윤 님이 병합한 `docs/api.md` 기준 실제 계약(agent가 `session_id`로 자기 히스토리 직접 관리, 추천 질문은 별도 `/api/v1/suggestions` 호출) 확인 후 `agent_client.py`/`schemas/query.py`/`query.py` 재작성, 미사용 `session_store.py` 삭제, `Backend`/`Fontend` 브랜치 커밋 → `main` 병합 → 배포 → 프로덕션 브라우저에서 추천 질문 표시·클릭·재질문까지 전부 정상 동작 확인 완료
- [x] 재생성 피드백 루프 코드는 잃어버리지 않도록 `_wip_query_with_retry_loop.py.txt`로 분리 보관 (커밋 대상 아님, 2026-07-13)
- [x] **프론트엔드 4화면 재구성 완료 (2026-07-14, 권도윤)** — 홈/질문하기/히스토리/저장 4화면 + 사이드바, `api.js`(신규 `node`/`done`/`error` 계약)·`store.js`(localStorage)로 전면 재작성, 새 npm 의존성 0개. 백엔드에 패스스루 `proxy.py` 추가되어 프론트가 agent와 직접(백엔드 relay를 통해) 통신
- [x] **답변 텍스트 마크다운 렌더링 수정 완료 (2026-07-14, 이후윤)** — `components/Markdown.jsx` 신규 작성(볼드·코드·번호/불릿 목록, 새 의존성 없음), `Ask.jsx`/`Saved.jsx` 적용, 로컬(`?mock=1`)·실제 화면 확인 완료, `main` 커밋·푸시·CI 배포 완료
- [x] **`proxy.py`에 defense-in-depth 재검증 복구 완료 (2026-07-14, 이후윤)** — `/api/v1/query/stream`을 SSE 이벤트 단위로 파싱하도록 수정, `done` 이벤트만 가로채 `guardrail.py`→백엔드 자체 DB 재실행(`run_readonly_query_table` 신규)→`result_validator.py` 순으로 재검증 후 전달. 재검증 실패 시 레거시와 동일하게 즉시 error(agent 재시도 없음). mock으로 정상/guardrail 실패/무결과/결과검증 실패 4개 시나리오 로컬 검증 완료, 실제 배포는 아직

**남은 것**

- [ ] CI/CD 안정화 — 코드 수정할 때마다 워크플로우가 계속 잘 도는지 반복 확인 (특히 VM 배포 방식으로 바뀐 지 얼마 안 됐으니 몇 번 더 지켜볼 것)
- [ ] (선택) LB에 실제 도메인 연결 — 지금은 `nip.io` 기반으로 HTTPS를 구성했는데, 실제 도메인이 생기면 그 도메인으로 인증서와 `VITE_API_BASE_URL`만 교체하면 됨
- [ ] `proxy.py` defense-in-depth 재검증 코드를 `main`에 커밋·배포하고 실제 배포 환경(GCE VM)에서 브라우저로 최종 확인

**최종 제출 전에만 처리** (지금 진행 중인 TODO가 아님)

- `project.yml` 플레이스홀더를 실제 내용으로 채우기 — 프로젝트 종료 후 최종 제출 직전에 작성

---

## 11. 참고 문서

* `SERVER_HANDOFF.md` — 인프라 구축 배경, 상세 체크리스트
* `DATA_SCHEMA.md` — Olist ERD, PK/FK 설계
* `mentoring_prep_2026-07-10.md` — 멘토링 중간점검 예상 질문/답변
* `ci-cd-vm-drafts/` — GCE VM 이전 시 사용한 워크플로우 초안 (참고용 보관)

> `Backend/README.md`, `Frontend/README.md`는 2026-07-10에 이 문서(6·7번 섹션)로 통합하고 삭제했습니다. 서버/DB/프론트엔드/백엔드/CI-CD 관련 변경 사항은 전부 이 `PROJECT_OVERVIEW.md`에만 반영합니다.

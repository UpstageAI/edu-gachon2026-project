# Project Day4 (7/13) 체크리스트 — 장바구니 물가 판단 에이전트

> 목표: Day3까지 완성된 MVP 4대 핵심 기능(§13) 코드를 실제 서버에 배포 — Docker화 → GCE 배포 → GitHub Actions CI/CD
> 완료 기준: GCE VM에 배포된 FastAPI 서버의 공인 IP(또는 도메인)로 "상추 지금 비싸?" 요청 시 실제 KAMIS(Supabase) + LLM 기반 SSE 응답이 정상 반환되고, `main` 브랜치 push 시 GitHub Actions로 테스트·배포가 자동 실행됨

---

## 0. 현재 상태 점검

- [ ] Day3 완료 기능이 로컬에서 전부 정상 동작하는지 최종 확인
  - **내용**: `uvicorn app.api.main:app --port 8000` + `streamlit run frontend/app.py` 로컬 실행 후 "상추 비싸?"(price), "상추 비싸면 대체품 알려줘"(hybrid), "안녕"(off-topic) 3가지 경로 재확인
  - **참고**: hybrid 경로의 `search_substitute`는 팀원 ChromaDB 구현 전까지 대체품 빈 배열 stub 상태 — 배포 목표에는 영향 없음(§13 MVP 4대 기능 기준)

- [ ] `Dockerfile.api` / `Dockerfile.frontend` / `docker-compose.yml` 현재 빈 파일 상태 확인
  - **내용**: 레포에 이미 스텁으로 생성되어 있으나 내용 없음 — 아래 §1에서 실제 작성
  - **Tool**: 파일 탐색기, `git log --follow`로 누가 언제 스텁을 만들었는지 참고

---

## 1. Docker 이미지화

- [ ] `Dockerfile.api` 작성 (FastAPI 앱 서버)
  - **내용**: `python:3.12-slim` 베이스 → `requirements.txt`(또는 `pyproject.toml`) 설치 → `app/` 복사 → `uvicorn app.api.main:app --host 0.0.0.0 --port 8000` CMD
  - **Tool**: Docker
  - **참고**: ChromaDB embedded 모드(§16.5)라 별도 DB 컨테이너 불필요 — `chroma_db/` 볼륨만 마운트하면 됨

- [ ] `Dockerfile.frontend` 작성 (Streamlit 프론트)
  - **내용**: `python:3.12-slim` 베이스 → `streamlit` 설치 → `frontend/app.py` 복사 → `streamlit run frontend/app.py --server.port 8501 --server.address 0.0.0.0` CMD
  - **Tool**: Docker
  - **참고**: `BACKEND_URL`을 컨테이너 네트워크 기준 주소(`http://api:8000`)로 바꿀 수 있도록 환경변수화 필요 (`frontend/app.py`의 `BACKEND_URL` 하드코딩 수정)

- [ ] `docker-compose.yml` 작성 — api + frontend 2개 서비스
  - **내용**: `api`(포트 8000), `frontend`(포트 8501) 서비스 정의, `.env` 파일을 `env_file`로 연결, `chroma_db/` 볼륨 마운트
  - **Tool**: Docker Compose
  - **참고**: Supabase는 hosted라 DB 서비스 불필요(`docker-compose.db.yml` 없음, §8 결정사항 그대로 유지)

- [ ] 로컬에서 `docker compose up --build` 정상 기동 확인
  - **내용**: 컨테이너 기동 후 `curl localhost:8000/health` 200 확인, Streamlit UI 접속 확인
  - **Tool**: Docker Desktop / `docker compose`

- [ ] `.dockerignore` 작성
  - **내용**: `.venv/`, `__pycache__/`, `chroma_db/`, `.env`, `tests/` 등 이미지에 불필요한 항목 제외
  - **Tool**: `.dockerignore`

---

## 2. GCE(Google Compute Engine) 배포

- [ ] GCE VM 인스턴스 생성
  - **내용**: 무료/저사양 티어(e2-micro 등)로 VM 생성, 방화벽 규칙에 8000(API)·8501(Streamlit) 포트 허용
  - **Tool**: GCP Console 또는 `gcloud compute instances create`
  - **참고**: §8 인프라 배치 기준 — Public 서버 1대(FastAPI + ChromaDB embedded), 별도 DB 서버 없음(Supabase 사용)

- [ ] VM에 Docker / Docker Compose 설치
  - **내용**: SSH 접속 후 Docker Engine, Docker Compose plugin 설치
  - **Tool**: `apt`, Docker 공식 설치 스크립트

- [ ] 레포 clone 및 `.env` 배치
  - **내용**: VM에서 `git clone`, `.env`는 커밋하지 않고 VM에 직접 생성(또는 배포 스크립트에서 GitHub Secrets로 주입 — §3과 연계)
  - **Tool**: `git`, `scp` 또는 CI/CD 배포 스텝

- [ ] VM에서 `docker compose up -d` 로 실제 배포 및 외부 접속 확인
  - **내용**: VM 공인 IP로 `/health`, `/chat`, Streamlit UI 각각 외부에서 접속 확인
  - **Tool**: `curl`, 브라우저

- [ ] (선택) 도메인 연결 및 리버스 프록시
  - **내용**: 시간 여유 있으면 nginx/Caddy로 80 포트 리버스 프록시 + 도메인 연결
  - **참고**: MVP 완료 기준(§ 상단)에는 필수 아님 — IP:PORT 직접 접속으로도 충분

---

## 3. GitHub Actions CI/CD

- [ ] `.github/workflows/test.yml` — PR/push 시 pytest 자동 실행
  - **내용**: `main`/`jaewoo` 브랜치 push 및 PR 시 `pytest` 전체 실행, 실패 시 머지 차단
  - **Tool**: GitHub Actions
  - **참고**: `DATABASE_URL`, `UPSTAGE_API_KEY` 등은 GitHub Secrets로 등록해 워크플로우 환경변수로 주입 (Day3 테스트가 실제 Supabase·Solar 호출에 의존하므로 필요)

- [ ] `.github/workflows/deploy.yml` — `main` push 시 GCE 자동 배포
  - **내용**: 테스트 통과 후 SSH로 GCE VM 접속 → `git pull` → `docker compose up -d --build`
  - **Tool**: GitHub Actions, `appleboy/ssh-action` 등
  - **참고**: VM 접속용 SSH 키를 GitHub Secrets(`GCE_SSH_KEY`, `GCE_HOST` 등)에 등록

- [ ] `.github/workflows/kamis_daily_fetch.yml` — KAMIS 일일 자동 수집 cron
  - **내용**: 매일 정해진 시각에 `scripts/fetch_kamis_snapshot.py` 실행 → Supabase `price_snapshot` 갱신 (지난 세션에서 설계한 수동 1회 실행을 자동화)
  - **Tool**: GitHub Actions `schedule` (cron) 트리거
  - **참고**: GCE VM 위에서 도는 서버가 아니라 GitHub Actions 러너에서 직접 실행 — Supabase는 외부에서 접근 가능한 hosted DB라 가능

- [ ] 시크릿 값 GitHub Secrets 등록
  - **내용**: `KAMIS_CERT_KEY`, `KAMIS_CERT_ID`, `UPSTAGE_API_KEY`, `DATABASE_URL`, (선택) `LANGFUSE_*` 등록
  - **Tool**: GitHub repo Settings > Secrets and variables > Actions
  - **참고**: 이 대화 중 Supabase DB 비밀번호가 로그에 노출된 이력이 있어 — 배포 전 비밀번호 재발급 여부 재확인 필요

---

## 4. 환경변수 분리 및 보안 점검

- [ ] `.env`는 로컬/서버에만 두고 절대 커밋되지 않도록 `.gitignore` 재확인
  - **내용**: `.gitignore`에 `.env` 포함 여부 확인 (`.env.example`만 커밋 대상)
  - **Tool**: `git check-ignore .env`

- [ ] 운영(prod)/로컬(dev) 환경변수 값 분리
  - **내용**: 로컬 개발용 `.env`와 GCE 배포용 값(예: `DATABASE_URL`은 동일 Supabase 공유, `KAMIS_CERT_*`는 동일 키 사용 가능)을 정리해 혼동 없도록 문서화
  - **참고**: 현재는 팀 공용 Supabase 프로젝트 하나만 사용 중이므로 큰 분리 이슈는 없음 — 값 목록만 명확히 정리

- [ ] Supabase DB 비밀번호 로테이션 (미해결 이월 항목)
  - **내용**: 이전 세션에서 pytest 에러 로그에 평문 비밀번호가 노출된 이력 있음 — 배포 전 재발급 권장
  - **Tool**: Supabase 대시보드 > Database > Reset password

---

## 5. MVP 핵심 시나리오 최종 검증 (배포 서버 기준)

- [ ] 배포된 서버에서 시나리오 2(원물 대체품 판단형) 재현
  - **내용**: 배포 서버의 `/chat`에 "상추 비싸면 대체품 알려줘" 요청 → hybrid 경로 SSE 응답 정상 확인
  - **참고**: 대체품 목록 자체는 ChromaDB 미완이라 빈 값 — 라우팅·판정·SSE 흐름이 배포 환경에서도 동일하게 동작하는지가 핵심

- [ ] 배포된 서버에서 시나리오 2 핵심 케이스 10회 중 9회 이상 정상 재현 (§12 KPI)
  - **내용**: "상추 지금 비싸?" 류 질문 10회 반복 요청 → 에러/타임아웃 없이 정상 응답 비율 확인
  - **Tool**: 반복 curl 스크립트 또는 수동 테스트

- [ ] SSE 응답 속도 실측 (§12 KPI: 첫 응답 3초 이내 / 전체 10초 이내)
  - **내용**: 배포 환경(로컬 대비 네트워크 지연 있음)에서 첫 `status`/`token` 이벤트 도달 시간과 전체 완료 시간 측정
  - **Tool**: Python `httpx` 스트리밍 스크립트로 타임스탬프 로깅

- [ ] `/health` 엔드포인트로 배포 후 DB 연결 상태 확인
  - **내용**: 배포 서버의 `/health` 호출 시 `{"status": "ok", "db": "connected"}` 확인
  - **Tool**: `curl`

---

## 6. 예외 처리 마무리 (Day3 이월 항목 중 배포 전 필요한 것)

- [ ] KAMIS/Supabase 조회 실패 시 사용자 안내 문구 확인
  - **내용**: 배포 환경에서 DB 연결이 일시적으로 끊기는 경우, "미지원" 응답과 실제 장애를 구분해 안내할 수 있는지 점검
  - **참고**: `app/tools/kamis.py`의 DB 조회 예외 처리는 Day3에 구현됨 — 배포 환경에서 재확인만 필요

- [ ] `tenacity` 재시도 로직 추가 (Day3 미완 이월)
  - **내용**: Supabase 조회 실패 시 최대 2~3회 재시도 후 그래도 실패하면 "미지원" 처리
  - **Tool**: `tenacity`

---

## 7. 문서화

- [ ] `README.md` 작성/업데이트
  - **내용**: 프로젝트 소개, 로컬 실행 방법, Docker 실행 방법, 배포 주소(있다면), 환경변수 목록
  - **Tool**: Markdown

- [ ] 배포 절차 간단 정리 (팀원 공유용)
  - **내용**: GCE 접속 방법, 재배포 방법(`docker compose up -d --build` 등) 팀원도 볼 수 있게 기록
  - **Tool**: Markdown 또는 Notion

---

## 진행 체크 (팀 공유용)

| 담당자 | 담당 파트 | 완료 여부 |
|---|---|---|
| | Docker 이미지화 | [ ] |
| | GCE 배포 | [ ] |
| | GitHub Actions CI/CD | [ ] |
| | 환경변수 분리 및 보안 점검 | [ ] |
| | MVP 시나리오 배포 서버 검증 | [ ] |
| | 예외 처리 마무리 | [ ] |
| | 문서화 | [ ] |

**Day4 완료 기준**: GCE에 배포된 서버 주소로 MVP 핵심 시나리오(§13)가 정상 동작하고, `main` push 시 GitHub Actions로 테스트·배포가 자동 실행되는 상태로 하루를 마감합니다.

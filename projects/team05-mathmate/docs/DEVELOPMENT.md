# MathMate 개발 문서

README의 프로젝트 소개용 내용과 분리한 실행·배포·운영 관련 기술 문서입니다.

## 기술 스택

- **Agent**: LangGraph
- **Backend**: FastAPI + SSE (스트리밍)
- **LLM**: Solar API (LiteLLM 게이트웨이)
- **Frontend**: Streamlit
- **관측**: Langfuse (LLM 호출 트레이싱)
- **DB**: Supabase (PostgreSQL, REST 클라이언트 — GCE에서 direct connection IPv6 문제 회피)
- **배포**: Docker + GCP Compute Engine + GitHub Actions

## 설치 및 실행

```bash
# 1. 저장소 클론
git clone https://github.com/leena-0/MathMate.git
cd MathMate

# 2. 가상환경 + 의존성
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. 환경변수 설정 (.env)
cp .env.example .env            # UPSTAGE_API_KEY 등 채우기

# 4. 실행
uvicorn app.main:app --reload

# 5. 동작 확인
curl http://localhost:8000/api/health
```

## 환경변수

| 변수 | 설명 |
|---|---|
| `UPSTAGE_API_KEY` (또는 `SOLAR_API_KEY`) | Solar API 키. 없으면 `USE_LLM=False`로 Mock 규칙 폴백 |
| `FALLBACK_MODEL` / `GEMINI_API_KEY` | (선택) Solar 완전 장애 시 대체 모델(Gemini). 비워두면 Mock 규칙으로 바로 폴백 |
| `SUPABASE_URL` | Supabase 프로젝트 URL |
| `SUPABASE_KEY` | publishable(anon) 키 — 프로필/숙련도(`app/db`) REST 클라이언트용 |
| `SUPABASE_SERVICE_KEY` | (선택) service_role 키 — 문제은행/진척도(`app/repositories`) 서버 전용, RLS 우회. 없으면 `SUPABASE_KEY`로 폴백 |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST` | (선택) LLM 호출 트레이싱. 비워두면 비활성 |

## 프로젝트 구조

```
app/
├── main.py          FastAPI 진입점 (/api/health)
├── api/             라우터 (chat, problems, profile, progress, feedback, health)
├── service/         유스케이스 조율 (tutor_service)
├── agent/           LangGraph State/Node/Graph
├── tools/           의도분류·진단·힌트생성·유출검증 도구
├── repositories/     문제은행·진척도·유저 저장소 (Supabase REST)
├── schemas/          Pydantic 모델
├── core/             config, llm_client(LiteLLM 게이트웨이), prompts
└── db/               Supabase 클라이언트(프로필·숙련도용), 모델
frontend/            Streamlit 채팅 UI
data/                문제은행 + 데이터 구축 스크립트
tests/               pytest
```

## 배포 (Docker Compose + GCE)

### 로컬에서 컨테이너로 실행

```bash
cp .env.example .env   # UPSTAGE_API_KEY 등 채우기
docker compose up -d --build
# API:      http://localhost:8000
# Frontend: http://localhost:8501
```

### GCE VM 배포 (최초 1회, 수동)

1. GCE VM에 Docker + Docker Compose 플러그인 설치
2. 방화벽에서 8000, 8501 포트 열기
3. VM에 저장소 clone 후 `.env` 파일 생성 (실제 키 값 채우기 — git에는 올라가지 않음)
4. `docker compose up -d --build`로 최초 기동

### GitHub Actions CI/CD

- `ci.yml`: main/PR push마다 `pytest` 자동 실행
- `cd.yml`: CI 성공 후 main에 한해 3단계로 자동 배포
  1. **Build & Push to GHCR**: API/Frontend 이미지를 빌드해 `ghcr.io/leena-0/mathmate-{api,frontend}`에 push (태그: `latest` + 커밋 SHA)
  2. **Deploy to Compute Engine**: SSH로 GCE VM 접속 → `git pull`(compose 설정 갱신용) → GHCR 로그인 → `docker compose pull && docker compose up -d` (VM에서 재빌드하지 않고 미리 빌드된 이미지만 받아서 기동)
  3. **Deployment Summary**: 배포된 API 헬스체크 + 배포 URL을 Actions 요약에 기록

CD를 쓰려면 저장소 Settings → Secrets and variables → Actions에 아래를 등록해야 한다.

| Secret/Variable | 설명 |
|---|---|
| `GCE_HOST` | VM 외부 IP |
| `GCE_USER` | SSH 접속 계정 |
| `GCE_SSH_KEY` | SSH 개인키 |
| `GCE_DEPLOY_PATH` (변수, 선택) | VM 위의 저장소 경로, 기본값 `~/MathMate` |

## LLMOps 운영 안정성

- **Retry·Fallback**: Solar 호출 실패(429/5xx/타임아웃) 시 LiteLLM이 자동 재시도(`LLM_NUM_RETRIES`), 그래도 실패하면 대체 모델(Gemini, `FALLBACK_MODEL=gemini/gemini-flash-latest`)로 폴백하고 그마저 안 되면 Mock 규칙으로 최종 폴백. 대체 모델은 Solar와 provider가 달라 `api_key`/`api_base`를 딕셔너리로 명시적으로 덮어써야 한다(문자열로만 넘기면 LiteLLM이 Solar 키를 그대로 재사용해서 실패함). 에러 유형(인증/요청한도/타임아웃/서버오류)별로 로그를 구분해 남긴다 (`app/core/llm_client.py`).
- **답 유출 방지 가드레일(이중화)**: 답 유출 시도는 `refuse_and_redirect`가 차단하고 첫 힌트로 대신 유도, 수학과 무관한 잡담은 `handle_off_topic`이 리다이렉트, 응답을 내보내기 직전 `leak_verify`가 정답 숫자 유출 여부를 최종 검사한다 (`app/agent/nodes.py`).
- **오답 진단 이중검증**: `diagnose_step`이 정답으로 판정하면, 학생이 여러 후보를 동시에 나열해서 우연히 정답이 섞여 있었던 건 아닌지 `CONFIRM_SYS` 프롬프트로 한 번 더 확인한다(1차: 채점 프롬프트 규칙, 2차: 별도 확인 모델 호출) (`app/tools/tutor_tools.py`).
- **학생 맞춤 힌트 + 정답 해설 노출**: 힌트 생성 시 학생이 실제로 낸 답(`student_attempt`)과 진단된 막힌 지점(`stuck_point`)을 프롬프트에 반영해 그 학생 상황에 맞는 힌트를 만든다. 정답에 도달하면 축하와 함께 실제 풀이 과정(`solution_steps`)을 보여주고, 힌트 3단계를 다 쓰고도 틀리면 정답+해설을 공개하고 마무리한다(`reveal_answer`).
- **힌트 단계 유지**: 대화 자체는 매 턴 새로 시작(stateless)하지만, `progress` 테이블에 저장된 `max_hint_level`을 턴마다 읽고 써서 LangGraph 체크포인터 없이도 "이 학생이 이 문제에서 몇 단계까지 힌트를 받았는지"를 이어간다 (`app/repositories/progress_repo.py`).
- **Langfuse Trace**: `LANGFUSE_*` 키를 설정하면 모든 Solar 호출(프롬프트·응답·지연시간·에러)이 Langfuse 대시보드에 `intent_classify`/`diagnose_step`/`generate_hint` 단위로 트레이싱된다. `litellm`과의 호환성 때문에 `langfuse<3`(v2 SDK) 고정 필요.

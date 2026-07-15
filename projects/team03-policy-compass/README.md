# 정책나침반 (Policy Compass)


## 1. 프로젝트 소개


> 정책 나침반은 사용자의 프로필 조건에 맞는 청년 정책•훈련을 추천해주는 AI 챗봇 서비스입니다.


정책나침반은 사용자의 나이, 거주 지역, 취업 상태, 관심 분야와 희망 직무를 자연어
대화에서 파악한 뒤 청년정책과 국민내일배움카드 훈련과정, 채용행사·공채속보를
검색합니다. 사용자에 대한 정보가 부족하면 다시 확인하고, 검증된 후보만 공식 링크, 상세 내용과 함께
최대 3개의 카드로 보여줍니다.


- 주요 사용자: 대학생·졸업예정자·사회초년생을 포함한 취업 준비 청년과 직무
훈련을 찾는 사용자
- 최종 결과물: FastAPI·LangGraph 백엔드와 React
채팅 UI를 결합한 웹 애플리케이션으로 사용자와 Agent가 대화를 주고받는 챗봇 형식
—--

## 2. 문제 정의


- 현재, 청년정책과 직업훈련·채용 정보는 여러 공공 서비스에 흩어져 있습니다. 사용자는
사이트마다 다른 검색 방식과 긴 공고를 살펴보고, 나이·지역·지원 조건·신청
기간이 자신의 조건과 맞는지 직접 일일이 비교해야 합니다.
더불어 사용자가 정책/훈련과 관련해 추가적으로 궁금한 부분이 있으면 직접 검색 포털에서 검색을 해야하는 불편함이 있습니다.
- 청년 정책이나 훈련에 지원할 때 자신이 등록 가능한 조건을 갖췄는지 판단할 때는 여러 정책의 조건을 하나하나 따져봐야 합니다. 그렇기에 사용자가 한 눈에, 한 곳에서 여러 정보를 파악할 수 있게 된다면 시간을 절약하고 더욱 편리하게 정보를 습득하고 처리할 수 있게 될 것이기 때문에 이 문제가 중요하다고 볼 수 있습니다.
—--


## 3. 문제 해결


1. **상황을 자연어로 설명합니다.** 사용자는 복잡한 검색 조건을 만들 필요 없이
  나이, 거주 지역, 취업 상태와 원하는 정책·훈련·직무를 평소 말하듯 입력합니다.
2. **부족한 조건만 확인합니다.** 추천에 필요한 정보가 부족하면 서비스가 필요한
  내용만 다시 질문하므로, 사용자가 자격 조건을 미리 파악할 필요가 없습니다.
3. **공식 정보에서 비교할 후보를 찾습니다.** 온통청년과 고용24에서 관련 정보를
  찾고 지역·연령·신청 기간·질문 관련성을 확인합니다. 명확히 조건이 맞지 않거나
  마감된 결과는 제외하고, 근거가 부족한 경우에는 추가 확인이 필요한 참고 결과로
  표시합니다.
4. **핵심만 카드로 비교합니다.** 대상, 지원·훈련 내용, 기간, 지역과 확인 가능한
  공식 링크를 최대 3개의 카드로 정리해 긴 공고를 처음부터 읽는 부담을 줄입니다.
5. **사용자가 추가 질문을 할 수 있습니다.** 추천받은 정책이나 훈련 내용에 대해 잘 모르겠는 용어에 대해 질문하면 답변을 통해 제공받은 정보에 대해 더 잘 이해할 수 있습니다.
—--

## 4. 핵심 기능


- 대화를 통한 사용자 프로필 추출
- 온통청년/고용24 API를 통한 정책/훈련/채용 정보 수집
- 부족한 사용자 프로필을 다시 질문해 확보
- 사용자 조건과 검색 결과를 비교해 적합한 정책 추천
- 추천 내용과 관련해 사용자의 추가 질문 가능
- 좋아요/싫어요로 추천 내용 만족도 평가
- 가드레일과 마스킹을 통한 사용자의 민감정보 입력 방지

## 대표 시연 시나리오

### 1. 청년정책 공식 정보 확인


1. “서울에 거주하는 만 24세 취업준비생입니다. 국민취업지원제도의 현재 지원 내용과 신청 조건을 확인할 수 있는 공식 청년정책을 찾아줘.”
2. `국민취업지원제도` 추천 카드에서 지원 대상, 지원 내용·금액, 신청 기간, 대상 지역과 공식 링크 확인
3. 추천 카드의 `👍` 버튼을 눌러 피드백 기능 확인


### 2. 국비지원 훈련과정 탐색


1. 새 채팅 생성 후 “서울에서 데이터 분석가 취업을 준비하고 있습니다. 고용24 국민내일배움카드 데이터 분석 국비지원 훈련과정을 찾아줘.”
2. 서울 지역 데이터 분석 훈련과정 카드에서 훈련기관, 훈련비, 신청 기간, 훈련 지역과 고용24 공식 링크 확인
3. 화면을 새로고침해 현재 대화와 추천 카드가 복원되는지 확인
4. 시연이 끝난 대화를 삭제해 기록 관리 기능 확인

## 동작 구조

```text
사용자
  → FastAPI: 입력 검증·민감정보 차단·세션 load
  → prepare_request: Router·프로필·pending·필수 조건
      ├─ 일반 대화/조건 부족
      │    → direct_response → verify_answer
      └─ 검색
           → retrieve → assess_evidence
                ├─ 일시 장애: 동일 소스 추가 1회
                ├─ 보정 가능한 무결과: 검색어 재작성 1회
                ├─ 근거 없음: direct_response
                └─ 근거 있음: build_answer → verify_answer
                                      └─ 수정 가능한 실패: 답변 수정 1회
  → finalize → 세션 save → JSON 또는 SSE 응답
```

## 기술 스택

| 영역 | 기술 |
| --- | --- |
| Backend | Python 3.11, FastAPI, Pydantic, httpx |
| Agent | LangGraph, LangChain, Upstage Solar `solar-pro2` |
| Frontend | React 19, TypeScript, Vite 8, Tailwind CSS |
| Data | 온통청년 Open API, 고용24 Open API, Supabase |
| Observability | Langfuse |
| Infra | Docker, GitHub Actions, GHCR, Google Compute Engine |
| Test | pytest, Ruff, Node test runner |

## 실행 방법

#### 준비

- Python 3.11 이상
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 이상과 npm

```bash
uv sync
cp .env.example .env
cd frontend
npm ci
```

전체 AI·검색 기능을 사용하려면 `.env`에 다음 값을 설정합니다.

| 변수 | 용도 |
| --- | --- |
| `UPSTAGE_API_KEY` | Solar 라우팅·프로필 추출·답변 생성 |
| `YOUTHCENTER_POLICY_API_KEY` | 온통청년 청년정책 검색 |
| `EMPLOYMENT24_TRAINING_API_KEY` | 고용24 훈련과정 검색 |
| `EMPLOYMENT24_JOB_API_KEY` | 고용24 채용행사·공채속보 검색 |
| `SUPABASE_URL`, `SUPABASE_KEY` | 대화 상태·피드백·API fallback cache |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` | 선택적 trace 수집 |


#### 개발 서버

백엔드:

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

프런트엔드:

```bash
cd frontend
npm run dev
```

- React UI: http://localhost:5173/
- 백엔드 정적 UI: http://localhost:8000/
- Swagger: http://localhost:8000/docs

#### Docker

```bash
docker compose up --build
```

Docker 이미지는 React production build와 FastAPI를 묶어
http://localhost:8000/ 에서 제공합니다.

## API

| Method | Endpoint | 설명 |
| --- | --- | --- |
| GET | `/api/health` | 기본 애플리케이션 상태 |
| GET | `/api/live` | 외부 의존성과 무관한 프로세스 생존 확인 |
| GET | `/api/ready` | release SHA와 필수 설정 준비 상태 |
| POST | `/api/chat` | 동기 채팅 |
| POST | `/api/chat/stream` | 노드 진행 상태와 최종 답변을 보내는 SSE 채팅 |
| POST | `/api/chat/feedback` | 추천 카드 묶음 평가 저장 |

## 검증

```bash
uv run ruff check app tests scripts data/scripts
uv run ruff format app tests scripts data/scripts --check
uv run pytest tests -q
cd frontend
npm test
npm run build
```

CI는 위 품질 검사와 함께 Docker 이미지 빌드까지 확인합니다.

## 주요 디렉터리

```text
app/
├── api/routes/       # chat, SSE, feedback, health/readiness
├── core/             # 설정, LLM, 개인정보, 지역, 시간·세션 제어
├── graph/            # 8-node graph, 계약, gate, 응답 검증
├── repositories/    # 온통청년·고용24·Supabase
├── schemas/          # API 모델
└── tools/            # 검색 Tool 입출력
frontend/             # React 채팅 UI와 로컬 대화 저장
data/                 # Supabase schema와 적재 보조 스크립트
tests/                # 백엔드 회귀 테스트
docs/PROJECT_RECORD.md
```

## 6. 팀원 소개


| 이름 | 역할 | GitHub |
| --- | --- | --- |
| 황성민 | AI/Agent, Backend, Data/API | [@sbma0122](https://github.com/sbma0122) |
| 김성은 | Frontend, Database, QA, Infra·Docs | [@k-seun](https://github.com/k-seun) |
—--

## 7. 참고자료 / 발표자료

- 원본 개발 저장소: [upstage-team3/policy-compass-agent](https://github.com/upstage-team3/policy-compass-agent)
- 발표 자료: https://docs.google.com/presentation/d/1dSRvbk0fQzh0zQnrM8aLPncPOmHfPJ3lnxeccGB4SzA/edit?usp=sharing
- 기획서: https://docs.google.com/document/d/19sTEhNnKd-Oaifpb77asq2EEEAJ6CNzRDsVrSm6vkqk/edit?tab=t.259rh1cmak7i#heading=h.qxonfnuld75
- 온통청년 Open API: https://www.youthcenter.go.kr/cmnFooter/openapiIntro/oaiDoc
- 고용24 Open API: https://m.work24.go.kr/cm/e/a/0110/selectOpenApiIntro.do


오픈소스 프레임워크와 라이브러리는 각 패키지의 라이선스와
`pyproject.toml`, `frontend/package.json`을 기준으로 사용했습니다.

# 재난안전 여행 가이드 에이전트 — 개발 로그

> 13조 백엔드(데이터 파이프라인 + RAG + LangGraph + FastAPI) 개발 전체 기록.
> 프론트엔드/팀원 공유용으로, 무엇을 왜 그렇게 만들었는지까지 남겨둠.

---

## 1. 전체 아키텍처

```
[사용자 질문]
     │
     ▼
[FastAPI /chat/stream] ── SSE ──▶ [프론트엔드]
     │
     ▼
[LangGraph: parse → route → stats/retrieve → gate → escalate|respond]
     │                    │
     ▼                    ▼
[Supabase Postgres]   [Solar API]
 - disaster_messages    - Chat (파싱/생성)
 - disaster_guidelines  - Embedding (검색)
   (pgvector)
 - response_agencies
```

- **DB**: Supabase (Postgres + pgvector). 정형 데이터/벡터/추후 체크포인터까지 한 곳에서 관리.
- **LLM**: Upstage Solar API (OpenAI SDK 호환).
- **오케스트레이션**: LangGraph. 단, **스트리밍이 필요한 최종 답변 생성은 그래프 밖(FastAPI 레이어)에서 직접 처리** — 그래프는 "판단"까지만 담당. (이유는 5장 참고)
- **배포**: Docker → GitHub Container Registry(ghcr.io) 자동 빌드 → GCE에서 pull해서 실행.

---

## 2. 데이터 파이프라인

### 2-1. 긴급재난문자 (`disaster_messages`, 최종 53,631건)

**문제 1 — 페이지네이션이 조용히 끊김**
처음 100건씩 수집했는데 18페이지(1800건)에서 멈춤. 원인 진단 결과 API가 특정 순간 **일시적으로 빈 응답**을 준 것뿐, 진짜 끝이 아니었음(재요청하면 정상 데이터 나옴). `numOfRows`를 요청보다 크게 줘도(예: 1000) 실제로는 요청보다 적은 건수만 반환하는 비공식 동작도 발견 → 이 경우 offset이 어긋나서 데이터가 조용히 스킵될 위험이 있음.

**해결**: 매 요청 전 실제 반환량을 probe로 확인하고, 안전하게 검증된 값(100)으로 자동 축소. 빈 응답도 즉시 "끝"으로 판단하지 않고 최대 3회 재시도. 종료 판단은 `totalCount` 대비 누적 수집량으로.

**문제 2 — 실종경보 필터링 누락 (2차 발견)**
기획서상 실종경보문자는 국민행동요령 대상이 아니라 제외 대상. 처음엔 `DST_SE_NM='기타'` + `☎182`(실종신고 전화) 포함 여부로 필터링했는데, **해운대구 8월 데이터 검증 중 `☎112`(경찰 대표번호)로 신고 안내되는 실종문자를 발견** → 182만 체크하면 누락됨. 키워드(`실종`/`배회`/`찾습니다`/`치매`) 기반 보강 추가. (이 필터는 `disaster_type == '기타'`일 때만 적용 — 호우 등 실제 재난 상황 보고에서 "실종"이 언급되는 경우까지 걸러내면 안 되기 때문)

### 2-2. 재난대응기관 (`response_agencies`, 613건)

기획서는 "재난유형별 담당기관·연락처"를 기대했는데, 실제 API는 **전화번호가 없는 행정기관 코드 체계 테이블**(중앙부처/지자체 목록)이었음. `LCLSF_CD`/`SCLSF_CD` 분포 분석으로 확인.

**해결**: 사용자가 제공한 표준 신고전화 인포그래픽(112/119/110 등)을 기반으로 `disaster_type_phone_map.py`를 별도 구축, 34개 재난유형 → 공식 연락처 매핑. `response_agencies`는 지역명 참고용으로만 사용.

### 2-3. 재난 국민행동요령 (`disaster_guidelines`, RAG용, 최종 751건)

**문제 — 공식 API 3종이 전부 한 카테고리만 있음**
신청한 자연재난/사회재난/생활안전 API 3개를 확인해보니 각각 딱 1개 세부 카테고리만 데이터가 있었음(사회재난=해양오염사고 16건, 자연재난=태풍 61건, 생활안전=응급처치 55건). 재난문자 통계 상위권(폭염/호우/대설/한파/산불)에 대한 행동요령이 전혀 없는 상태.

**해결**: 국민행동24 공식 자료를 팀원이 직접 정리해서 20개 재난유형 텍스트를 제공, `[재난유형 / 단계 / 세부카테고리] 문장` 형식으로 파싱하는 스크립트(`parse_manual_guidelines.py`) 작성 → Solar Embedding(4096차원)으로 임베딩 → pgvector 적재.

**부수 이슈**: pgvector의 HNSW/ivfflat 인덱스는 최대 2000차원까지만 지원하는데 Solar 임베딩은 4096차원 → 인덱스 없이 순차 스캔으로 운영 (현재 데이터 규모에선 성능 문제 없음, 데이터가 수만 건 이상으로 커지면 재검토 필요).

---

## 3. 인프라 (Supabase)

- pgvector 확장 활성화.
- **IPv6 이슈**: Supabase의 Direct Connection(`db.xxx.supabase.co`)이 IPv6 전용이라 로컬(맥 환경)에서 연결 실패 → **Session Pooler** 연결 문자열(`aws-0-[region].pooler.supabase.com`, 사용자명이 `postgres.[project-ref]` 형태)로 전환. **GCE 배포 시에도 동일 이슈 가능성 있어 반드시 Pooler 사용.**
- RLS(Row Level Security) 활성화: 공개 데이터라 읽기는 전체 허용, 쓰기는 `service_role`/직접 연결만 가능.

---

## 4. Tool 함수 (`tools/`)

### `stats_tool.py` — 지역×월별 재난 통계
기획서의 "데이터 공백 폴백(단계적 확대)" 로직 구현:
1. 시/군/구 단위 집계 시도 (표본 5건 미만이면 부족 판단)
2. 부족하면 시/도 단위로 자동 확대 + 확대했다는 사실을 답변에 명시
3. 시/도 단위로도 부족하면 → **억지로 답을 만들지 않고 표본 부족을 고지** (핵심 가치: "모르면 안다고 하지 않는다")

`ILIKE` 퍼지 매칭 사용 (LLM이 파싱한 "해운대"만으로도 "해운대구" 매칭), "OO 전체" 형태의 시/도 전체 발령 문자도 자동 포함.

### `retrieve_tool.py` — pgvector 유사도 검색
`solar-embedding-1-large-query`(질문용)로 임베딩 후 코사인 거리(`<=>`) 기준 top-k 검색.

---

## 5. LangGraph 파이프라인 (`app/graph/`)

### 설계 결정: "그래프는 판단까지만, 스트리밍은 FastAPI에서"
LangGraph 노드 자체를 스트리밍시키는 방법도 있지만, 상태관리+스트리밍을 동시에 최적화하면 복잡도가 급격히 올라감. 그래서:
- `parse → stats/retrieve → gate` 까지는 일반 `graph.invoke()`로 실행 (판단만 내림)
- 판단 결과에 따라 FastAPI가 직접 Solar API를 스트리밍 호출

오늘 목표(SSE + Solar 연동 + E2E) 달성이 우선이라 택한 실용적 구조. 추후 필요하면 스트리밍 그래프로 리팩토링 가능.

### 라우팅 버그 — reactive 질문에 지역/월을 강제 요구
"호우경보 문자 받았는데 뭘 해야 하죠?" 같은 반응형 질문은 지역/시기 정보가 필요 없는데, 초기 구현이 무조건 `region_sido`+`month`를 요구해서 전부 "재질문"으로 튕겨나감. **prevention은 지역+월 필수, reactive는 disaster_type만 있으면 진행**하도록 라우팅 분기 수정.

### retrieve 설계 변경 — "합쳐서 검색" → "유형별 개별 검색"
처음엔 통계 상위 3개 재난유형을 한 문장으로 합쳐서("기타, 폭염, 호우 대비 및 행동요령") 한 번에 검색했음. 팀원 피드백으로 "재난문자 취합 → 그 재난 각각에 대한 대비"가 명확히 안 보인다는 문제 제기 → **재난유형별로 각각 개별 검색**(top_k=3씩) + `matched_disaster_type` 태깅 방식으로 변경. 프롬프트도 재난유형별로 그룹핑해서 LLM에 전달 → 답변이 "1. 폭염 대비 / 2. 호우 대비" 식으로 통계 순위와 정확히 일치하는 섹션 구조로 개선됨. ("기타"는 실제 행동요령 카테고리가 없어서 검색 대상에서 제외, 통계 요약에는 그대로 유지)

### Gate (1차 게이트)
검색된 행동요령 중 최소 코사인 거리가 임계값(0.6)보다 크면 "관련 근거 없음"으로 판단 → 에스컬레이션. 실제 테스트("외계 바이러스" 같은 터무니없는 질문)에서 벡터 검색이 그나마 가까운 카테고리(황사, distance 0.61)를 찾아내도 게이트가 정확히 걸러내는 것을 확인함. (2차 LLM 판정 게이트는 아직 미구현 — 다음 단계)

### LLM 3단 방어 (`app/llm_client.py`)
기획서 요구사항 그대로 구현: ① 호출당 timeout 30초 ② 일시 오류 시 지수 백오프 재시도 최대 2회 ③ 최종 실패 시 답변 생성 대신 행동요령 원문 + 대응기관 안내로 안전하게 강등.

**설계 포인트 — 재시도해도 되는 오류 vs 안 되는 오류를 구분**
openai SDK의 예외 계층을 그대로 재시도 대상(`RETRYABLE_EXCEPTIONS`)에 넣었다가, 인증 오류(`AuthenticationError`)도 `APIError`의 하위 클래스라 재시도 대상에 포함되는 버그를 발견함(잘못된 API 키로 테스트하다가 확인). 인증/권한 오류는 재시도해도 절대 성공 못 하는데 백오프 대기(1초+2초)를 낭비하고 있었음. → `FATAL_EXCEPTIONS`(인증/권한)를 별도로 분리해서 **재시도는 스킵하되 여전히 강등 처리로는 이어지게** 함.

**설계 포인트 — 스트리밍 중 실패는 "재시도"가 아니라 "중단 처리"**
이미 사용자에게 토큰 일부가 전송된 뒤 실패하면, 처음부터 다시 스트리밍하면 앞부분이 중복되거나 앞뒤가 안 맞는 답변이 될 위험이 있음. 그래서 토큰을 하나도 못 보낸 상태에서 실패(`LLMUnavailableError`, 재시도 대상)와 일부라도 보낸 뒤 실패(`LLMStreamInterruptedError`, 재시도 없이 중단 안내만 추가)를 명확히 구분.

### Langfuse 트레이싱 (관측성)
`from openai import OpenAI` → `from langfuse.openai import OpenAI`로 클라이언트 교체만으로 모든 Solar API 호출(파싱+스트리밍)이 자동 트레이싱됨 (드롭인 방식, 인터페이스 동일). 추가로 `langfuse.langchain.CallbackHandler`를 `graph.invoke()`에 연결해서 LangGraph 노드별(parse→route→stats→retrieve→gate) 실행 흐름과 타이밍까지 하나의 트레이스로 묶어서 확인 가능. 대시보드에서 실제로 `LangGraph → parse → parse_user_query(LLM) → route_after_parse → stats → retrieve → gate → respond_stream(LLM)` 순서와 각 노드의 output(`should_escalate` 등)까지 정상 수집되는 것을 확인함. 배포 환경(GCE)에서도 로컬과 같은 `LANGFUSE_PUBLIC_KEY`/`SECRET_KEY`를 쓰면 같은 대시보드에 모이므로, 서버 `.env`에도 반드시 동일 키를 넣어야 함.

의존성 관련: `langfuse.langchain.CallbackHandler`는 `langchain` 패키지(LangGraph만으로는 부족)를 필요로 함 — 로컬에서 처음 테스트할 때 `ModuleNotFoundError: langchain` 발생해서 `requirements.txt`에 추가함.

### 2차 게이트 (LLM 적합성 판정) 및 평가셋 검증

**평가셋 구축**: 기획서 기준(행동요령 있는 상황 20건 + 없는 상황 10건) 30건을 LLM에게
생성 요청. B그룹(10건, 에스컬레이션 되어야 함)은 3가지 유형으로 세분화해서 요청함 —
완전 무관(irrelevant) 2건, DB에 없는 재난유형(uncovered_type) 4건, 벡터 검색이 헷갈릴
만한 경계선 케이스(boundary) 4건. 경계선 케이스를 의도적으로 포함시킨 이유: 무관한
질문만으로는 게이트가 너무 쉽게 다 맞혀서 지표가 무의미하게 100%로 나올 수 있음.

**평가 스크립트**: `eval/run_eval.py`. 전체 답변 생성(스트리밍)까지 안 가고
`parse→stats/retrieve→gate→judge`까지만 실행해서 판단만 검증(비용/시간 절감).
에스컬레이션을 positive class로 두고 precision/recall/F1 계산.

**1차 게이트만 있었을 때 (baseline)**: accuracy 76.7%, precision 100%, **recall 33.3%**.
Precision은 완벽한데 recall이 낮다는 건 "답변하면 안 될 상황에서도 답변을 만들어버린다"는
뜻 — 안전 도메인에서 제일 위험한 실패 방향. 특히 #29(폭염 상황에서 포도당 투여 같은
전문 의료행위 요청)를 그럴듯하게 답변해버리는 게 발견되어, 2차 게이트가 왜 필요한지
정량적으로 증명됨.

**2차 게이트 추가 → 캘리브레이션 반복**: 처음 만든 판정 프롬프트("불충분한 경우"만
나열)는 과도하게 엄격해서 recall 88.9%까지 올랐지만 precision이 34.8%로 폭락(정상
질문 대부분을 거부). 원인은 LLM이 "무더위쉼터 위치정보가 정확히 없으니 불충분"처럼,
우리 서비스가 원래 제공 안 하는 실시간·개인화 정보까지 요구하는 방향으로 과보수적으로
판정한 것. **"충분한 경우" 기준과 few-shot 예시를 명시적으로 추가**해서 재캘리브레이션.

**부수적으로 발견한 아키텍처 버그**: 캘리브레이션 과정에서 A그룹 4건(#3,4,10,11)이
계속 실패하는 걸 보니, 예방형(prevention) 질문은 파싱 프롬프트가 애초에
`disaster_type`을 강제로 null로 만들어서(사용자가 재난유형을 직접 언급해도 무시),
검색이 순수 통계 상위유형에만 의존하고 있었음 → 통계에서 안 뜨는 유형을 사용자가
직접 물으면 아예 검색이 안 됨. **예방형이어도 명시된 재난유형은 추출하고, 통계
상위유형과 합쳐서 검색**하도록 수정.

**재발한 회귀 - reask 폭증**: 파싱 프롬프트에 지침을 추가하는 과정에서, 반응형 질문 중
공식 특보명이 없는 경우(#15 갯벌, #16 건물 붕괴) LLM이 `disaster_type`을 더 자주
null로 반환하게 됐고, 라우팅 로직이 "반응형인데 유형 없으면 무조건 재질문"으로 막아서
`reask` 건수가 1→5로 급증. **F1 지표만 보면 개선된 것처럼 보였지만, reask는
precision/recall 계산에서 제외되는 구조라 숫자가 착시를 일으킴** — 원래 맞히던 케이스가
"재질문"이라는 다른 실패 모드로 숨은 것뿐. 근본 해결: 반응형 질문은 `disaster_type`을
못 뽑아도 재질문 대신 **원본 질문 그대로 벡터 검색하는 폴백**으로 진행하도록 라우팅을
완화 (그래프 라우팅 / `main.py` / `eval/run_eval.py` 3곳에 동일 로직 적용).

**최종 결과**: accuracy 80%, precision 70%, recall 77.8%, **F1 50%→73.7%**, reask 1건
(baseline과 동일 수준 유지 — 인위적 개선 아님 확인됨).

**남은 known issue**: #21(완전 무관한 질문, 예: 맛집 추천)이 여전히 통과되는 경우 있음.
근본 원인은 예방형 검색이 원본 사용자 질문을 전혀 안 쓰고 통계 상위 재난유형으로만
쿼리를 새로 만들기 때문에, 1차 게이트(거리 임계값)가 "이 질문이 재난안전과 관련 있는지"
자체를 구조적으로 볼 수 없음 — 2차 게이트(LLM)가 유일한 방어선인데 가끔 놓침.
다만 이 실패의 실제 위험도는 낮음(잘못된 재난정보를 주는 게 아니라 무관한 안내를 주는
것뿐). 근본 해결책은 파싱 단계에 "재난안전 도메인과 무관함(irrelevant)"을 별도
intent로 분류해서 애초에 그래프 진입을 막는 것 — 비용도 저렴한 수정이라 여유 있을 때
추가할 후보로 남겨둠.

### 체크포인터 (대화 세션 유지)

`langgraph-checkpoint-postgres`의 `PostgresSaver`로 구현. 단순히 "체크포인터를 연결"만
하면 실제로 대화가 안 이어짐을 먼저 인지하고 설계함 — `parse_node`가 매 턴마다 새 질문만
갖고 처음부터 파싱하기 때문에, 후속 질문("노약자는 뭘 더 챙겨야 해?")은 지역/시기 정보가
없어서 그 자체로는 파싱이 실패함. 그래서 두 가지를 같이 구현:
1. 체크포인터 자체(Postgres에 `thread_id` 기준 상태 저장/복원)
2. **`parse_node`가 이번 턴에 못 뽑은 필드는 이전 턴 값을 이어받도록 수정** — 체크포인터가
   복원해준 이전 state를 실제로 활용하는 부분. `intent`는 후속 질문마다 다를 수 있어서
   매번 새로 판단하고, `region_sido`/`month`/`disaster_type`/`has_vulnerable`만 이어받음.

**겪은 이슈**: `psycopg_pool.ConnectionPool`에 `max_size=1`만 주고 `min_size`를 안 줬다가
`ValueError: max_size must be greater or equal than min_size` 발생 (기본 `min_size`가
1보다 큼) → `min_size`도 명시적으로 지정해서 해결.

**실제 2턴 테스트로 발견한 추가 이슈**: 체크포인터 자체는 정상 작동(지역/시기/동반자
맥락이 정확히 이어짐)했는데, "노약자는 뭘 더 챙겨야 해?"라는 후속 질문이 엉뚱하게
에스컬레이션됨. 원인은 `retrieve_node`가 검색 쿼리를 만들 때 `has_vulnerable=True`라는
정보를 알고 있으면서도 쿼리 문장에 반영을 안 해서("폭염 발생 시 행동요령"만 검색),
DB에 실제로 있는 노약자 특화 문구(예: "부모님 약물 복용 여부 확인")를 못 찾아낸 것.
`has_vulnerable`이면 쿼리에 "노약자 동반 시 주의사항 포함"을 자동으로 추가하도록 수정 →
재테스트에서 `GUIDE-*-ELDERLY-*` 인용이 대거 잡히고 정상 답변으로 전환됨.

### LangSmith 연동 (Langfuse와 이중 트레이싱)

프로젝트 요건에 LangSmith가 별도로 명시되어 있어서 추가. Langfuse와 방식이 다름:
- Langfuse: `langfuse.openai` 클라이언트 교체 + `CallbackHandler`를 명시적으로 `graph.invoke()`에 연결
- LangSmith: `LANGCHAIN_TRACING_V2` 등 환경변수만 설정하면 LangGraph 노드 구조가 자동으로 잡힘 (코드 수정 불필요)

**주의할 점**: 환경변수 자동 감지는 LangChain Runnable 인터페이스를 쓰는 부분(LangGraph
노드 실행)에만 적용됨. Solar API 호출은 `openai`/`langfuse.openai` SDK를 직접 쓰고 있어서
LangChain 트레이싱 범위 밖 — 이 부분까지 LangSmith에 보이게 하려면 `langsmith`의
`@traceable` 데코레이터를 명시적으로 붙여야 함. `parse_user_query`, `_stream_once`(답변
생성), `judge_relevance`(2차 게이트) 3개 LLM 호출 함수에 추가. `LANGCHAIN_TRACING_V2`가
꺼져있으면 데코레이터가 자동으로 no-op이라 안전하게 항상 붙여둠.

---

## 6. SSE API 설계

### 이벤트 구조 (프론트 UI 요구사항에 맞춰 확정)
| 이벤트 | 내용 |
|---|---|
| `parsed` | 지역/시기/동반자 (사람이 읽기 좋은 문자열로 가공) |
| `stats` | 위험도 점수(0~100) + 표본 범위 |
| `citation` | 인용 배지 ID 목록 |
| `token` | 답변 텍스트 조각 (반드시 이어붙여서 렌더링) |
| `escalate` / `reask` | 예외 상황 분기 |
| `done` | 종료 신호 |

### 위험도 점수(0~100) 계산 방식
단순 발생 비율(%)을 그대로 쓰면 "기타"(잡다한 안전공지 묶음, 실제로는 절반 가까이 차지)에 가려서 진짜 위험도가 왜곡됨. → **"기타" 제외 후 상위 3개 유형 안에서의 상대 비중**으로 재계산.

### 인용 배지 ID (`GUIDE-HEAT-ELDERLY-001` 형식)
DB에는 이런 코드가 없어서(숫자 PK만 존재), 재난유형 영문 코드 + 카테고리 문구 키워드 추론(노약자→ELDERLY, 대피/침수→EVACUATION 등) + 순번으로 생성. **안전 지침 내용 자체는 실제 검색 데이터 그대로 사용, 표시용 라벨만 새로 만든 것**이라 정확성 문제 없음.

### 왜 Swagger/curl에서 지저분하게 보이는가
Solar API가 음절 단위로도 스트리밍하는 경우가 있어서(`"4"`, `"시"`, `"까지는"`), Swagger UI나 curl은 raw 텍스트를 그대로 뿌리기만 함. **실제 프론트는 `EventSource`나 `fetch` 스트림으로 받아서 텍스트를 계속 이어붙이기만 하면 자연스러운 문장이 됨.** (`scripts/demo_client.py`가 이 소비 로직의 Python 참고 구현)

**중요**: 표준 `EventSource`는 GET만 지원. 지금 API는 POST + body가 필요해서 프론트는 `fetch()` + `ReadableStream` 방식으로 구현해야 함.

---

## 7. CI/CD

### CI (`ci.yml`)
- lint(ruff) → test(pytest) → report 순서로 `needs`체인 연결 (PR에서 흐름도로 보이게)
- 겪은 이슈: lint 수정 후 추가 코드 변경으로 lint 이슈 재발생 (재검사 습관 필요), 테스트 파일 내용이 서로 뒤바뀌어 들어간 실수, `preprocessors/parse_manual_guidelines.py` 파일 자체가 로컬에 누락된 경우, 암묵적 네임스페이스 패키지 인식 불안정 → 각 폴더에 명시적 `__init__.py` 추가로 해결.

### DB Schema CD (`db-cd.yml`)
`main`에 `*_schema.sql` 변경 push 시 Supabase에 자동 적용. `workflow_dispatch`로 머지 전 수동 테스트도 가능.
겪은 이슈: GitHub Secret의 **Value 칸에 변수명(`DATABASE_URL=`)까지 같이 넣는 실수**로 `psql: invalid connection option` 에러. Value엔 순수 연결 문자열만 들어가야 함.

### Docker Build & Push CD (`docker-cd.yml`)
GCP 서비스 계정 키 없이도(팀원이 GCP 관리자라 조율 필요) **GitHub 기본 제공 `GITHUB_TOKEN`만으로 ghcr.io에 이미지 자동 업로드**. 배포 담당자는 로컬 빌드 없이 `docker pull`만 하면 됨.
겪은 이슈: `docker/build-push-action`의 기본 `docker` 드라이버가 `cache-to type=gha`를 지원 안 해서 빌드 실패 → `docker/setup-buildx-action`으로 `docker-container` 드라이버 명시 필요. 또한 이 워크플로우 파일 자체를 수정한 커밋은 `paths` 필터(`app/**`, `Dockerfile` 등)에 안 걸려서 트리거가 전혀 안 됨(체크 자체가 안 뜸, 실패도 아님) → 워크플로우 파일 자기 자신의 경로도 `paths`에 포함시켜야 함.

### GCE Deploy CD (`gce-deploy-cd.yml`)
Docker Build & Push CD 완료 후 자동으로 이어져서(`workflow_run` 트리거) SSH로 GCE 서버에 접속 → 최신 이미지 pull → 기존 컨테이너 정리 → 재실행 → 헬스체크까지 자동화. GCP 서비스 계정 키(전체 권한)가 아니라 **그 VM 하나에 대한 SSH 개인키만** 발급받아서 사용 — 훨씬 가벼운 권한 요청으로 팀원과 조율함. `GCE_HOST`/`GCE_USER`/`GCE_SSH_KEY` 3개만 Secret으로 등록.

겪은 이슈 2가지:
1. **이름은 남았는데 포트 필터로 못 잡히는 컨테이너**: 정리 로직이 "8080 포트를 쓰는 컨테이너"만 찾아서 지웠는데, 이전에 수동으로 띄웠던 `disaster-agent-be`라는 이름의 컨테이너가 그 시점엔 8080을 안 쓰고 있어서 필터에 안 걸림 → 새 컨테이너를 같은 이름으로 만들 때 "이름 중복" 충돌. **해결**: 포트 기준 정리 + `docker rm -f disaster-agent-be`(이름 기준, 포트 상태 무관)를 같이 실행해서 이중으로 안전하게 정리.
2. **헬스체크 타이밍 레이스 컨디션**: `docker run -d`는 컨테이너를 만들고 즉시 리턴하는데, 그 안의 FastAPI 앱(LangGraph 컴파일 등)이 완전히 뜨는 데는 몇 초 더 걸림. `sleep 3` 한 번만 주고 curl 했더니 "Connection reset by peer"로 실패 — 실제로는 컨테이너 로그를 보면 앱이 정상적으로 잘 뜬 상태였음(단순 타이밍 문제, 진짜 장애 아니었음). **해결**: 30초까지 3초 간격으로 재시도하는 루프로 변경, 실패 시에만 `docker logs`를 자동 출력해서 다음부터는 SSH 안 해도 Actions 로그에서 바로 원인 확인 가능하게 함.

### CodeRabbit
GitHub App 방식이라 `ci.yml`의 job 그래프와는 별도 체크로 표시됨 (같은 그래프 안에 통합하려면 AI API를 직접 호출하는 커스텀 job이 필요한데, 지금은 더 간단한 App 방식 채택).

---

## 8. 현재 상태 & 다음 단계

**완료**
- 데이터 파이프라인 3종 + RAG(751건, 자연재난/사회재난/생활안전 3종 전부 포함) + SQL 통계 + 연락처 매핑
- LangGraph 파이프라인 (parse→route→stats/retrieve→gate→judge→respond/escalate)
- SSE 스트리밍 + Solar API 실연동, E2E 시나리오 3종(예방형/반응형/에스컬레이션) 검증 완료
- LLM 3단 방어 (timeout/재시도/강등)
- Langfuse + LangSmith 트레이싱 (LLM 호출 + LangGraph 노드별 실행 흐름, 이중 관측)
- 2차 게이트(LLM 적합성 판정) + 평가셋 30건 구축, F1 50%→73.7% 개선 검증 (DeepEval 없이 자체 스크립트로 측정)
- Docker + CI/CD (lint/test/DB마이그레이션/이미지빌드)
- GCE 실배포 완료 (405 이슈 해결) + GCE Deploy CD 완전 자동화 (main 머지 → 이미지 빌드 → 서버 재배포 → 헬스체크까지 전부 자동)
- **LangGraph 체크포인터(PostgresSaver) + thread_id 기반 대화 세션 유지** — 후속 질문이 이전 턴의 지역/시기/동반자 맥락을 이어받음 (실제 2턴 테스트로 검증됨)

**다음 단계**
- (선택, 저비용) 파싱 단계에 "irrelevant"(재난안전 무관) intent 분류 추가 — #21류 완전 무관 질문이 가끔 통과되는 잔여 이슈 해결
- DeepEval 프레임워크로 평가 스크립트 정식 편입 (지금은 자체 스크립트로 측정)
- nginx 리버스 프록시로 포트 정리 (80 -> 8080 라우팅)
- README / 발표자료 / 데모 리허설

---

## 9. 팀원(프론트/배포)이 꼭 알아야 할 것

- API 문서/연동 스펙: `DEPLOYMENT.md` 참고
- SSE `token` 이벤트는 반드시 텍스트를 이어붙여서 렌더링 (한 글자씩 잘려서 오는 게 정상)
- **`session` 이벤트로 받은 `thread_id`를 저장해두고 다음 요청에 그대로 담아 보내야 대화가 이어짐** (오늘 추가된 체크포인터 기능)
- 필수 환경변수: `DATABASE_URL`, `UPSTAGE_API_KEY` (+ 트레이싱용 `LANGFUSE_*`, `LANGCHAIN_*` — 없어도 앱은 동작하지만 관측성이 빠짐). 데이터 수집용 API 키들은 런타임에 불필요
- `DATABASE_URL`은 반드시 Supabase **Session Pooler** 버전 사용

---

## 10. 배포 트러블슈팅

### 405 Not Allowed — 프론트가 80포트로 요청, 백엔드는 8080포트
GCE 실배포 후 프론트에서 `/chat/stream` 호출 시 405 에러 발생. 브라우저 개발자도구로 확인해보니 요청이 `[서버IP]:80`으로 감(백엔드는 8080에 떠있음). **원인**: 프론트 코드가 `/chat/stream`을 상대경로로 fetch해서, 브라우저가 "지금 프론트가 서빙되는 포트(80)"로 자동 요청함. 80번 포트엔 정적 파일 서버만 있어서 그 경로/메서드를 처리 못 함 → FastAPI가 준 405가 아니라 아예 도달을 못 한 상황.

**해결**: 임시로 프론트에서 백엔드 절대경로(`http://[IP]:8080/chat/stream`)로 명시 호출. 정식 해결은 nginx 리버스 프록시로 `/chat/stream` 요청을 8080으로 넘기는 설정 추가 예정(HTTPS 전환 시에도 필요).
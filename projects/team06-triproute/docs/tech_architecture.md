# TripRoute 기술 아키텍처 및 핵심 구현 정리

이 문서는 TripRoute의 **실제 코드 기준** 기술 아키텍처, 핵심 기술 선택 이유, 각 구성 요소의 구현 방식을 한 곳에
정리한 문서입니다. 최초 기획 의도는 `README.md`(1~9절)에, 개별 설계 결정의 배경은 `docs/architecture.md`에
있으며, 이 문서는 **현재 코드가 실제로 어떻게 동작하는지**를 기준으로 작성했습니다.

---

## 1. 한눈에 보는 전체 구조

```text
[사용자]
   ↓ 자연어 입력 + 이동수단 + 인원수 (+ 이전 턴 조건/결과)
   │
   ├─ Gradio UI (/ui, 같은 FastAPI 프로세스 안에 mount) ──── 직접 Python 함수 호출(HTTP 아님)
   │        ↓
   └─ FastAPI REST (POST /trip/plan) ──────────────────── HTTP
            ↓
   app.agents.react_loop.run_triproute_react_loop  (호환 wrapper, 실질적 로직 없음)
            ↓
   app.agents.coordinator.run_triproute_coordinator
            ↓
   app.graph.workflow  — LangGraph StateGraph(TripRouteState).invoke()
            │
            ├─ parse_node        (Solar LLM 또는 Mock 파서로 자연어 → 조건 추출)
            ├─ route_planner_node(관광지 후보/연관장소/동선/일정표 생성)
            ├─ financial_node    (교통비/식비/카페비/입장료/숙박비 계산)
            └─ finalize_node     (State 전체를 최종 응답 스키마로 조립)
            ↓
   TripPlanResponse { condition_summary, daily_schedule, route_summary, cost_summary, warnings, react_trace }
```

핵심 특징: **분기 없는 고정 선형 파이프라인**입니다. `app/graph/edges.py`의 `LINEAR_EDGES`는
`parse → route_planner → financial → finalize` 4단계를 조건 없이 그대로 연결합니다. LLM에게
"다음에 뭘 할지"를 판단시키는 ReAct/Tool-calling 방식은 의도적으로 채택하지 않았습니다(2절 참고).

---

## 2. 핵심 기술 선택과 이유

### 2-1. LangGraph 고정 그래프 (ReAct/Tool-calling 미채택)

`app/tools/schemas.py`에 `ToolCall`/`ToolResult` 스키마가 정의돼 있고 `app/agents/react_loop.py`도
이름은 "ReAct Loop"이지만, **실제로는 둘 다 쓰이지 않습니다.** `react_loop.py`는 `coordinator.py`를
그대로 호출하는 100% 위임 wrapper이고, `app/tools/mock_tools.py`의 4개 mock 도구도 실제 파이프라인에서
호출되지 않습니다(Step 2에서 `route_planner.py`/`financial.py`의 실서비스 연동으로 대체됨).

TripRoute의 일정 생성 절차는 요청마다 달라지지 않고 항상 `조건 분석 → 관광지 검색 → 동선 계산 →
비용 계산 → 조립` 순서로 고정됩니다. 매 단계 "다음에 뭘 호출할지"를 LLM이 판단하게 하면 판단용 LLM
호출이 추가로 필요해 속도·비용이 늘고, 판단 오류 위험만 생기고 얻는 이점이 없습니다. 그래서 그래프
구조(node/edge)는 설계 시점에 코드로 고정하고, LLM(Upstage Solar)은 각 단계 **내부의 좁은 텍스트
작업**(자연어 조건 추출, 추천 이유 문장 생성, 비정형 요금 텍스트 구조화, 자연어 요약 생성)에만 사용합니다.

### 2-2. 왜 Upstage Solar인가

- Chat: `solar-pro2` (OpenAI SDK 호환 — `openai` 파이썬 클라이언트에 `base_url="https://api.upstage.ai/v1"`만
  바꿔 그대로 사용, `response_format` 구조화 출력은 `solar-pro3`가 아직 미지원이라 `solar-pro2` 유지).
- 구조화 출력은 네이티브 JSON 모드/함수 호출이 아니라 **시스템 프롬프트로 JSON 문자열을 지시하고
  수동으로 파싱**하는 방식(`_extract_json`)입니다. 우선 `json.loads`를 시도하고, 실패하면 문자열
  리터럴 안의 중괄호까지 추적하며 균형 잡힌 JSON 블록을 스캔합니다(여러 JSON 블록이 이어붙는 경우를
  막기 위함).
- Embedding: 용도별로 **다른 모델**을 씁니다 — 질의(사용자 취향)는 `solar-embedding-1-large-query`,
  저장(관광지 개요)은 `solar-embedding-1-large-passage`. 비대칭 bi-encoder 구조로, 짧은 질의와 긴
  저장 문서의 성격 차이에 각각 최적화된 모델을 쓰는 편이 검색 정확도가 높다는 Upstage 권장을 따름.
  두 모델 모두 4096차원 벡터를 출력해 서로 비교 가능합니다.
- 모든 Upstage 호출은 `langfuse.openai.OpenAI`(드롭인 래퍼)로 감싸져 있어, 호출부 코드 변경 없이
  모든 chat/embedding 호출이 자동으로 Langfuse에 추적됩니다(prompt/response/토큰/지연시간). Langfuse
  키가 없으면 조용히 no-op.

### 2-3. 왜 Supabase pgvector인가

- 별도 벡터 DB(Pinecone 등)를 두지 않고 Supabase(Postgres + pgvector 확장)에 관광지 임베딩을
  저장 — RAG 저장소와 인증(Auth), 채팅 이력, LangGraph 체크포인트까지 **하나의 Postgres 인스턴스**로
  통합해서 운영 부담을 줄임.
- pgvector 인덱스(HNSW/IVFFlat)는 최대 2000차원까지만 지원하는데 Upstage 임베딩은 4096차원이라
  인덱스를 만들 수 없음 — 현재 규모(도시별 수백 건)에서는 인덱스 없는 전체 스캔으로 충분하다고
  판단하고 무인덱스로 운영. 규모가 커지면 `halfvec` 타입이나 차원 축소를 검토 예정.
- 벡터 거리 정렬은 PostgREST(REST API)로 표현할 수 없어서, `match_places`라는 Postgres 함수를
  만들어두고 `client.rpc("match_places", {...})`로 호출.

### 2-4. 왜 카카오모빌리티인가

자동차 기준 거리·소요시간·택시요금·통행료를 API 하나로 전부 제공(README가 요구하는 4가지 정보를
한 번의 호출로 커버). 대신 **실시간 대중교통 환승 경로는 제공하지 않아서**, 대중교통은 자동차 기준
결과에 휴리스틱(×1.7 소요시간, 구간별 정액 요금)을 적용한 추정치이며 최종 출력에 항상 "추정치" 안내
문구를 포함합니다(`app/utils/transport_rules.py`).

### 2-5. 왜 Google Places API (New)인가

한국관광공사 TourAPI, 카카오 로컬 API, 네이버 검색 API 모두 별점/리뷰수 필드가 없어서, 이 정보를
제공하는 사실상 유일한 API로 채택. (Legacy Places API는 2025년 3월부로 신규 프로젝트 활성화가 막혀
반드시 "Places API (New)"를 사용해야 함.) 이름 텍스트 검색만으로는 오매칭이 실제로 발생했음이
확인됐고(가짜 장소명이 전혀 관계없는 서울 법무법인과 매칭된 사례), TourAPI가 이미 갖고 있는
좌표(mapx/mapy)로 `locationBias`(반경 500m)를 걸어 검증하는 방식으로 해결했습니다.

---

## 3. LangGraph 워크플로우

### 3-1. 그래프 구성

`app/graph/workflow.py`의 `build_trip_route_graph(checkpointer)`가 4개 노드를 만들고
`app/graph/edges.py`의 `LINEAR_EDGES = [(PARSE, ROUTE_PLANNER), (ROUTE_PLANNER, FINANCIAL),
(FINANCIAL, FINALIZE)]`를 그대로 연결합니다(조건 분기 없음). 그래프는 모듈 임포트 시점에
`_TRIP_ROUTE_GRAPH = build_trip_route_graph(get_checkpointer())`로 한 번만 컴파일되어 재사용됩니다.

- `run_trip_route_workflow(...)`: `@observe(name="trip_plan_workflow")`(Langfuse 트레이스)로
  감싸져 있고, 체크포인터가 켜져 있으면 매 호출 시작 전에 `checkpointer.delete_thread(thread_id)`를
  호출합니다 — 즉 **같은 thread_id라도 매 요청은 항상 빈 체크포인트에서 시작**합니다. 턴 간
  연속성(후속 요청)은 체크포인터가 아니라 `previous_condition_summary`/`previous_result` 파라미터로
  앱 레벨에서 직접 처리합니다.
- `stream_trip_route_workflow(...)`: 노드가 끝날 때마다 `(진행 메시지, 결과 또는 None)`을 yield —
  Gradio가 "여행 조건을 분석하고 있어요..." 같은 단계별 진행 메시지를 실시간으로 보여주는 데 사용.
  `@observe` 대신 `start_as_current_observation(...as_type="span")`으로 감싸는데, 이는 제너레이터가
  중간에 닫히면 `@observe`가 span을 너무 일찍 종료시키는 문제를 피하기 위함입니다.

### 3-2. `TripRouteState` (LangGraph State, `total=False`)

```python
class TripRouteState(TypedDict, total=False):
    user_input: str
    transport_mode: str
    people_count: int
    previous_condition_summary: Optional[Dict[str, Any]]
    previous_result: Optional[Dict[str, Any]]

    # parse_node가 채움
    city: str
    season: str
    duration: str
    travel_style: List[str]
    schedule_intensity: str
    prefer_local: bool
    prefer_budget: bool
    is_peak_season: bool
    must_include_places: List[str]
    parser: str

    # 후속 요청(슬롯 교체) 전용
    target_day: Optional[int]
    target_time_slot: Optional[str]

    # 후속 요청(장소 이동) 전용
    move_source_day: Optional[int]
    move_source_time_slot: Optional[str]
    move_destination_day: Optional[int]
    move_destination_time_slot: Optional[str]

    # 처음 계획 시에만 쓰이는 일차별 취향 오버라이드
    daily_preferences: List[Dict[str, Any]]

    # route_planner_node가 채움
    candidate_places: List[Dict[str, Any]]
    rag_ranked_places: List[Dict[str, Any]]
    related_places: List[Dict[str, Any]]
    selected_places: List[Dict[str, Any]]
    route_summary: List[Dict[str, Any]]
    daily_schedule: List[Dict[str, Any]]
    lodging_place: Optional[Dict[str, Any]]
    data_source: str  # "rag" | "real_api" | "mock"

    # financial_node가 채움
    cost_summary: Dict[str, Any]

    # 누적 필드(operator.add) — 여러 노드가 이어서 추가
    warnings: Annotated[List[str], operator.add]
    react_trace: Annotated[List[Dict[str, Any]], operator.add]

    # finalize_node가 채움
    result: Dict[str, Any]
```

`warnings`/`react_trace`만 `operator.add`로 누적되고, 나머지 필드는 마지막에 값을 쓴 노드 기준으로
덮어씁니다.

### 3-3. Route Planner 노드의 4가지 분기

`route_planner_node`(`app/graph/nodes.py`) 자체는 분기 없이 항상 실행되지만, 그 안에서 호출하는
`route_planner.py`의 함수는 **후속 요청 종류에 따라 4가지로 나뉩니다** (이 판단은 그래프 엣지가
아니라 노드 내부 로직):

| 조건 | 호출 함수 | 동작 |
|---|---|---|
| 이전 결과 있음 + 기간이 늘어남 | `build_incremental_route_plan` | 기존 Day는 그대로 두고 늘어난 날짜만 새로 채움 |
| 이전 결과 있음 + 장소 이동 요청 | `build_place_move_route_plan` | 지정한 장소를 목적지 슬롯으로 옮기고, 원래 자리는 새로 백필. 목적지 슬롯의 식사(점심/저녁) 여부와 옮겨오는 장소의 음식점 여부가 불일치하면 이동을 취소 |
| 이전 결과 있음 + 슬롯 교체 요청 | `build_slot_replacement_route_plan` | 지정한 슬롯 하나만 새 장소로 교체 |
| 그 외(첫 계획 또는 전체 재계획) | `build_route_plan` | 처음부터 전체 일정을 새로 생성 |

---

## 4. Agent 구현 상세

### 4-1. Coordinator (`app/agents/coordinator.py`, `app/agents/react_loop.py`)

`coordinator.py`는 `run_trip_route_workflow`/`stream_trip_route_workflow`를 그대로 호출하는 얇은
진입점이고, `react_loop.py`는 다시 `coordinator.py`를 그대로 호출하는 호환 wrapper입니다(과거 이름의
흔적, 실질 로직 없음). FastAPI(`/trip/plan`)와 Gradio UI 둘 다 `react_loop.py`를 통해 진입합니다.

### 4-2. Route Planner (`app/agents/route_planner.py`, 이 프로젝트에서 가장 큰 모듈)

**후보 수집 3계층**
1. RAG(Supabase pgvector) 우선 검색 — `_search_rag_places`. 취향 문장을 임베딩해 `match_places` RPC로
   유사도 상위 후보를 가져오고, 유사도가 `MIN_SIMILARITY` 미만이면 제외.
2. RAG 결과가 없으면 TourAPI `searchKeyword2` 실시간 검색으로 폴백 — `_search_real_places`.
3. 숙박(`_search_lodging_place`)·음식점(`_search_restaurant_places`)은 각각 별도로 RAG 검색 →
   (부족하면) TourAPI 실시간 검색으로 보충. 두 경로 모두 `is_in_expected_region()`으로 다른 지역
   동명 상호 오염을 걸러냄.

**후보 정제 규칙** (일반 관광지 후보군에서 항상 제외)
- 숙박/음식점(각각 별도 슬롯으로 채움) — 카테고리 + 이름 키워드(카라반/글램핑/캠핑장 등, TourAPI가
  "레포츠"로 잘못 등록하는 경우 대응).
- 쇼핑 — 단, 이름에 "시장"이 들어가면 예외(재래시장은 실제 관광 명소이지 아울렛/브랜드 매장과 다름).
- 공항 — 이름에 "공항"이 들어가면 제외(경유지일 뿐 방문 목적지가 아님).
- 여행코스 하위 장소 중 "점심식사(OO식당)" 같은 안내문 성격 항목 — 이름 패턴으로 우선 제외하고,
  그래도 카테고리를 못 정한 항목은 안전하게 제외(단, content_id가 오래돼 죽은 것뿐인 진짜 장소는
  이름으로 재검색해 살려냄 — 아래 "데이터 정합성" 참고).
- 지리적 군집화 — 취향 1등 기준 15km 이내 후보만 남기되, 그 결과가 필요한 슬롯 수보다 적으면
  군집화를 건너뛰고 필터링 전 전체 후보로 되돌림(제주도처럼 넓은 지역에서 Day 2/3가 통째로 비는
  문제 방지).

**일정 조립**
- `_build_time_slots`: 일정 강도(빡빡/보통/여유)에 따라 하루 관광지 슬롯 수(2~3개) 결정, 겨울/마지막
  날은 저녁 슬롯 제외.
- `_reorder_places_for_time_slots`: 점심/저녁 슬롯에는 음식점 카테고리만 우선 배정.
- `_insert_lodging_checkin`: 1일차 점심 직후(보통 체크인 가능 시간)에 체크인 일정을 끼워 넣고,
  그 앞뒤 구간의 `route_summary`도 함께 갱신.
- `_check_daily_density`: 하루 이동시간 합이 일정 강도별 기준(여유 180분/빡빡 300분)을 넘으면 경고.

**데이터 정합성 이슈 대응 (실측으로 발견하고 수정한 것들)**
- 카카오모빌리티 API 호출에 재시도(최대 3회, 선형 백오프)를 추가 — 일시적 네트워크 오류로 "조회
  실패" placeholder가 그대로 굳어버리는 문제 방지(단, `result_code != 0` 같은 실제 길찾기 불가
  응답은 재시도해도 결과가 같으므로 재시도하지 않음).
- RAG 유사도 임계값(`MIN_SIMILARITY`)이 실제 임베딩 분포보다 훨씬 높게(0.5) 잡혀 있어 사실상 항상
  빈 결과를 반환하던 문제 — 실측(관련 있는 취향도 top-5가 0.28~0.30, 완전 무관한 취향도
  0.22~0.27)을 근거로 0.2로 낮춤. 음식점/숙박 검색에는 TourAPI 실시간 폴백이 아예 없었어서 이
  임계값 문제 하나가 체크인/점심/저녁 슬롯이 통째로 빠지는 원인이었음.
- 여행코스 하위 장소가 가리키는 `subcontentid`가 TourAPI에서 병합/삭제돼 `detailCommon2`가 빈
  응답을 주는 경우가 실측으로 확인됨(예: "오죽헌", "태종대 전망대"). 장소 자체는 멀쩡하므로 이름으로
  재검색해 살아있는 content_id로 갱신하고, 그래도 못 찾으면(진짜 안내문 항목이면) 제외.

### 4-3. Financial (`app/agents/financial.py`)

1. `travel_days`/`nights`를 `daily_schedule`의 고유 Day 수로 계산.
2. 교통비: 렌터카는 여행 전체 1회, 그 외 이동수단은 `route_summary`의 각 구간을 합산
   (`app/utils/transport_rules.py`의 이동수단별 규칙 — 택시는 4인승 기준 대수 올림, 자차는 0원,
   대중교통은 거리 기반 정액 요금 누진).
3. `selected_places`를 콘텐츠 타입으로 재분류해 식사 장소/카페(브랜드명 키워드 포함, 예: 스타벅스)를
   구분.
4. 숙박·음식점 제외 장소는 TourAPI `usefee`(입장료 비정형 텍스트)를 Upstage로 파싱해 실제 요금 확보,
   음식점/카페는 Google Places `priceLevel`을 요금 구간표로 환산.
5. 숙박은 Route Planner가 고른 `lodging_place`를 우선하고, TourAPI `detailInfo2`(객실 목록)로 실제
   1박 요금을 인원수/성수기 반영해 추정(`app/utils/cost_rules.py`).
6. 실측 데이터가 없는 항목은 전부 고정 단가 fallback(식비 3만원/인/일, 카페 1.5만원/인/회, 숙박
   5만원/인/박 등)으로 대체.
7. 모든 TourAPI/Google Places 부가 조회는 24시간 파일 캐시(`app/utils/cache.py`)를 거침.

---

## 5. RAG 파이프라인

```text
[오프라인 수집] TourAPI searchKeyword2(도시×8개 콘텐츠타입) → detailCommon2(개요/좌표)
      → 지역 필터(is_in_expected_region) → Upstage passage 임베딩(4096차원)
      → Google Places 평점/리뷰수 조회 → Supabase places 테이블 upsert(content_id 기준)

[실시간 검색] 사용자 취향 문장 → Upstage query 임베딩
      → Supabase match_places RPC(코사인 유사도 top-N, city_filter로 지역 제한)
      → MIN_SIMILARITY(0.2) 미만 제거 → Route Planner로 전달
```

- 콘텐츠 타입: 12=관광지, 14=문화시설, 15=축제공연행사, 25=여행코스, 28=레포츠, 32=숙박, 38=쇼핑,
  39=음식점 (`DEFAULT_CONTENT_TYPE_IDS`). 32/38은 초기 수집에서 누락돼 있었다가 나중에 추가됨.
- `CITY_TO_REGION_PREFIXES` + `is_in_expected_region()`: `searchKeyword2`가 전국 대상 검색이라
  "부산" 검색에 충북 옥천의 "부산식당" 같은 동명 상호가 섞이는 문제를 주소 접두사로 걸러냄. 원래
  오프라인 수집 전용이었으나, Route Planner의 TourAPI 실시간 검색 폴백(관광지/음식점/숙박 3곳
  모두)에도 동일하게 적용하도록 확장.
- 인덱스 없는 pgvector 전체 스캔(4096차원은 HNSW/IVFFlat 인덱스 생성 자체가 안 됨 — 2000차원 제한).
- `event_start_date`/`event_end_date`(축제), `rating`/`review_count`(Google Places)는 수집 시점에
  함께 저장해서 Route Planner가 재조회할 필요가 없게 함.

---

## 6. 외부 API 연동 요약

| API | 용도 | 재시도 | 캐싱 | 비고 |
|---|---|---|---|---|
| TourAPI(KorService2) | 관광지 검색/상세/코스/요금 | 최대 3회, 선형 백오프(네트워크 오류·JSON 파싱 실패만) | 상세조회 7일 캐시 | 대량 호출 시 429 실측 발생 이력 있음 |
| 카카오모빌리티 | 자동차 거리/시간/택시비/통행료 | 최대 3회(네트워크 오류만, 결과코드 실패는 재시도 안 함) | 24시간 캐시(같은 출발/도착 조합) | 대중교통은 자체 휴리스틱(×1.7)으로 추정 |
| Google Places API (New) | 평점/리뷰수/가격대/좌표 보완 | 최대 3회(429만) | 24시간 캐시 | 좌표 기반 `locationBias`로 오매칭 방지 |
| Supabase(REST+RPC) | pgvector 검색, 관광지 저장, 채팅 이력, 인증 | — | — | anon 키(RLS)와 service_role 키(RLS 우회, 채팅 이력용) 분리 사용 |
| Supabase(Postgres 직결) | LangGraph 체크포인트 | 풀 생성 3회 재시도(DNS 실패 대응) | — | 트랜잭션 모드 풀러 대응 위해 `prepare_threshold=None` |
| Upstage Solar | 조건 파싱/요약/요금 텍스트 구조화/임베딩 | — | — | Langfuse OpenAI 래퍼로 자동 트레이싱 |

---

## 7. 프론트엔드 (Gradio UI)

`ui/gradio_app.py`는 다크 3단 레이아웃(사이드바 · 결과패널 · 요청)으로 구성되고, FastAPI 앱에
`gr.mount_gradio_app(app, demo, path="/ui")`로 같은 프로세스에 마운트됩니다(별도 서버 아님).

- **좌측 사이드바**: 로그인/프로필, "새로운 대화" 버튼, 최근 대화 검색 + 목록(`gr.Radio`).
- **중앙 결과 패널**: `gr.Tabs`로 일정표/이동 동선/예상 비용/조건 요약 4개 마크다운 뷰.
- **우측 요청 패널**: `gr.Chatbot`, 이동수단/인원수 입력, 메시지 입력창.
- **백엔드 호출 경로**: HTTP가 아니라 **같은 프로세스 안에서 Python 함수를 직접 호출**
  (`stream_triproute_react_loop`) — FastAPI의 `/trip/plan`과는 별개의 진입 경로이지만 내부적으로
  같은 Coordinator/LangGraph 체인을 재사용.
- **인증**: Supabase Auth(`auth_client.py`) 기반 이메일/비밀번호 로그인. `gr.BrowserState`에는
  `refresh_token`/`user_id`/`email`만 저장하고 **access_token은 서버 측 `gr.State`에만 보관**(브라우저
  로컬스토리지 미저장). 만료 60초 전에 미리 갱신.
- **대화 이력**: Supabase `chat_sessions`/`chat_messages` 테이블에 저장, 세션 재개 시 이전
  `condition_summary`/전체 결과까지 복원.
- **스트리밍 UX**: 노드 진행 메시지를 실시간으로 보여준 뒤, 완료되면 Upstage Solar 스트리밍으로 자연어
  요약을 타이핑 효과로 붙임. 사용자 에코 텍스트는 `html.escape()` 처리(챗봇이 raw HTML을 렌더링하므로
  XSS 방지).
- 로그인 세션의 `session_id`를 LangGraph 체크포인터의 `thread_id`로 그대로 재사용.

---

## 8. 배포 (Docker + CI/CD → GCE)

- **Dockerfile**: 멀티스테이지. 1단계(`builder`)는 `uv sync --frozen --no-dev`로 의존성만 설치,
  2단계(`runtime`)는 `.venv`와 소스만 복사해 비root 사용자(`appuser`)로 실행, `uvicorn app.main:app`을
  8000번 포트로 기동.
- **docker-compose.yml**(dev) / **docker-compose.prod.yml**(prod): prod는 `ghcr.io/bbbj00/team06-triproute`에
  미리 빌드된 이미지를 pull해서 띄우는 방식(로컬 빌드 아님), 둘 다 헬스체크로 `localhost:8000/` 폴링.
- **CI**(`ci.yml`): PR/`main` push 시 `uv sync` → `ruff check` → `python -m compileall`(문법 체크) →
  `pytest`.
- **CD**(`cd.yml`): CI 성공 후 자동 트리거. `build`(Docker 이미지 빌드) → `push`(GHCR에 `:sha`/`:latest`
  태그로 push) → `deploy`(GCE VM에 `docker-compose.prod.yml` 전송 → SSH로 `docker compose pull && up -d`
  → 헬스체크 최대 30회 폴링 후 실패 시 컨테이너 로그 출력하고 워크플로우 실패 처리).
- 목표(README 3절/Step 8)였던 "Docker 컨테이너화 + CI/CD 기반 GCP 배포"가 GCE VM 대상으로 이미
  구현되어 있는 상태(Cloud Run이 아니라 VM + docker-compose 방식으로 최종 결정됨).

---

## 9. 캐싱 전략

`app/utils/cache.py`: 네임스페이스 + 파라미터 해시(SHA-256) 기준 JSON 파일 캐시(`data/cache/`).
경로별 `RLock`으로 동시 쓰기 경합을 막고, 임시파일 작성 후 `os.replace()`로 원자적 교체. TTL은
호출부마다 다르게 지정:

| 데이터 | TTL |
|---|---|
| 카카오 경로(`kakao_route`) | 24시간 |
| TourAPI 상세조회(`detail_common`, `course_detail_info`, `must_include_search`) | 7일 |
| TourAPI 요금/소개(`detail_intro_usefee`, `detail_info_lodging`) | 24시간 |
| Google Places 가격대(`google_places_price_level`) | 24시간 |

---

## 10. 테스트 전략

`pytest` 기반, 총 96개 테스트(`tests/` 디렉터리). 외부 API는 `monkeypatch`로 모듈 레벨 함수
(`route_planner.retrieve_places_by_taste`, `route_planner.search_keyword`, `route_planner.get_route`
등)를 교체해 네트워크 호출 없이 결정적으로 테스트합니다. `test_checkpointer.py`는 실제 Supabase
대신 LangGraph의 인메모리 `MemorySaver()`로 체크포인트 동작(스냅샷/스레드 격리)만 검증합니다.
`conftest.py`는 공유 fixture 없이 `sys.path`에 프로젝트 루트만 추가하는 최소 구성입니다.

주요 분포: `test_route_planner.py`(49, 가장 큼 — 후보 필터링/일정 조립/후속 요청 3종),
`test_financial.py`(15), `test_solar_parser.py`(10), `test_auth_client.py`(9),
`test_chat_store.py`(7), 나머지(`checkpointer`/`react_loop`/`formatter`) 소수.

CI(`ci.yml`)에서 `ruff check`(린트) + `compileall`(문법) + `pytest`를 매 PR/push마다 실행합니다.

---

## 11. 알려진 한계

- **대중교통은 실측이 아니라 휴리스틱**: 카카오모빌리티가 자동차 기준 정보만 제공하므로, 대중교통
  소요시간/요금은 자동차 기준값에 배율/정액 요금을 적용한 추정치입니다. 최종 출력에 항상 안내 문구를
  포함합니다.
- **지도 시각화/실시간 재최적화 없음**: MVP 범위에서 의도적으로 제외.
- **RAG 코퍼스는 사전 수집된 10개 도시로 한정**(강릉/부산/제주/경주/전주/여수/속초/춘천/인천/서울).
  그 외 도시는 TourAPI 실시간 검색만으로 동작(취향 유사도 순위·평점/리뷰수 기반 정렬 불가).

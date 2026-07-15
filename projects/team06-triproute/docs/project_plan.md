# TripRoute 프로젝트 실행 계획 (Project Plan)

> 본 문서는 README의 개발 로드맵을 기반으로, **날짜 없이 "무엇을 해야 하는가"** 중심으로 작업 항목을 정리한 실행 계획서입니다.
> 각 단계는 순차적으로 진행하되, 외부 API 연결(Step 2)과 State/Agent 기본 흐름(Step 3)은 병행 가능합니다.

---

## Step 0. 개발 환경 및 사전 준비

- [x] `uv` 기반 가상환경 세팅 (`pyproject.toml` + `uv.lock`, FastAPI/Gradio/LangGraph/langchain/supabase/httpx/python-dotenv/langfuse 등)
- [x] 팀원 각자 `uv sync` 실행해 동일 환경 재현
- [x] `.env.example` 작성 (Upstage / TourAPI / Kakao Mobility / Supabase / Langfuse 키)
- [x] `.env` 생성 및 실제 API Key 입력 (Git에 커밋되지 않도록 주의)
- [x] `.gitignore`에 `.env`, `.venv`, `__pycache__`, `data/cache/`, `data/raw/` 포함 확인
- [x] 각 외부 API 계정 발급 및 키 확보
  - [x] Upstage Solar API 키
  - [x] 공공데이터포털(data.go.kr) 인증키 발급 — **아래 두 서비스에 각각 "활용신청" (키 값은 계정당 1개 공통, `TOUR_API_KEY` 하나로 둘 다 호출)**
    - [x] 한국관광공사_국문 관광정보 서비스_GW (ID 15101578) — 일반 관광정보
    - [x] 한국관광공사_관광지별 연관 관광지 정보 (ID 15128560) — 연관 관광지
  - [x] 카카오모빌리티 API 키
  - [x] Supabase 프로젝트 생성 + URL/KEY
  - [x] Langfuse 프로젝트 생성 + 키

---

## Step 1. 프로젝트 기본 구조 구성

- [x] README의 폴더 구조에 맞춰 디렉토리 및 `__init__.py` 생성
  - [x] `app/` (core, graph, agents, services, rag, utils, schemas)
  - [x] `ui/`, `data/` (raw, cache, sample), `docs/`, `tests/`
- [x] `app/core/config.py` — `.env` 환경변수 로드 로직 구현
- [x] `app/main.py` — FastAPI 앱 초기화 및 기본 실행 확인 (`uvicorn app.main:app --reload`)
- [x] `ui/gradio_app.py` — Gradio UI 구현 및 실행 확인 완료. "CHAT A.I+" 스타일(인디고 포인트
      컬러 + 라벤더 배경 + 2단 사이드바/채팅 레이아웃, `docs/ui_design_spec.md` 기준)로
      전체 재구성. 여행 계획 결과(일정/동선/비용/조건/주의사항/실행과정)는 챗봇 버블이 아니라
      별도 탭형 "결과 패널"로 분리해 정보 밀도 문제 해결. 로딩 상태 표시, React trace 기본
      숨김(탭 뒤로), 입력창 placeholder 처리까지 포함. Playwright로 실제 브라우저 end-to-end
      확인 완료(콘솔 에러 없음).
- [x] `app/schemas/` — 요청/응답 Pydantic 모델 정의
  - [x] `request.py` (user_input, transport_mode, people_count)
  - [x] `response.py` (condition_summary, daily_schedule, route_summary, cost_summary, warnings)
  - [x] `place.py` (관광지 데이터 모델) — `Place` Pydantic 모델 자체는 정의 완료(content_id/
        name/category/address/좌표/overview/운영시간/휴무일/이용요금/source). 단, 실제
        코드(`route_planner.py` 등)는 이 모델 대신 여전히 느슨한 `Dict[str, Any]`로 장소를
        주고받고 있어 검증에는 쓰이지 않는 상태.
        > **보류 (나중에 확장 시 진행)**: 지금 스키마엔 실제로 쓰는 필드(rating/review_count/
        > similarity/reason/content_type_id 등)가 빠져 있어서 확장부터 필요하고,
        > `route_planner.py`/`financial.py`/`formatter.py`의 place 관련 코드를 대부분 손봐야
        > 하는 범위가 넓은 작업. 장소 데이터를 별도 API로 공개하는 등 실제 검증이 필요해지는
        > 시점에 진행. 지금은 새 기능 없이 내부 안정성만 개선하는 작업이라 우선순위 낮음.

---

### Mock ReAct Loop 프로토타입 — Step 1~3 선행 작업

- [x] `app/agents/react_loop.py` — Thought → Action → Observation → Final 흐름의 Mock ReAct Loop 구현
- [x] `app/tools/mock_tools.py` — `search_places` / `get_related_places` / `get_route_info` / `estimate_cost` Mock Tool 구현
- [x] `app/tools/schemas.py` — `ToolResult` 스키마 정의 (⚠️ `ToolCall`은 정의만 되어있고 실제로는 미사용 — 아래 참고)
- [x] `tests/test_react_loop.py`, `tests/conftest.py` — Mock ReAct Loop pytest 시나리오
- [x] 위 Mock Tool들을 Step 2의 실제 API 서비스로 교체 완료 — `route_planner.py`/`financial.py`가
      RAG(Supabase)/`tour_api.py`/`kakao_mobility.py`를 기본 경로로 사용하고, `mock_tools.run_tool`은
      RAG·실시간 API 둘 다 실패했을 때만 타는 최종 fallback(`_build_mock_fallback`)으로만 남음
      (의도적으로 유지 — 아래 설계 결정 참고). 단 `related_place_api.py`는 코스 기반 연관 장소
      검색으로 완전히 대체돼 지금은 어디서도 안 쓰이는 죽은 코드 상태(삭제 여부는 팀 논의 필요).
- [x] `react_loop.py`를 Step 3의 Coordinator/Route Planner/Financial 3-Agent + LangGraph 구조로
      리팩터링 완료 — `react_loop.py` → `coordinator.py` → `app/graph/workflow.py`(LangGraph
      StateGraph: parse → route_planner → financial → finalize) 순으로 연결됨. 상세 내용은
      `docs/langgraph_workflow.md` 참고.
- [x] **설계 결정**: TripRoute는 절차가 항상 고정된 파이프라인이라 Tool Calling(LLM이 다음 행동을
      스스로 판단하는 ReAct 방식)을 도입하지 않기로 함. 대신 LangGraph 고정 그래프 + 각 Agent 내부의
      좁은 범위 LLM 호출(입력 분석/문장 생성/텍스트 구조화) 방식으로 감. 상세 근거는
      `docs/architecture.md` 참고. `app/tools/` 폴더는 지금 지우지 않고 유지 — Step 2/3 리팩터링
      시점에 팀 논의 후 삭제 여부 재결정.

---

## Step 2. 외부 API 연결 테스트

- [x] `app/services/tour_api.py` — 관광지 검색(`searchKeyword2`)/상세공통(`detailCommon2`)/소개정보(`detailIntro2`, 운영시간·usefee) 호출 및 테스트 완료
- [x] `app/services/related_place_api.py` — 연관 관광지 조회(`areaBasedList1`, `searchKeyword1`) 호출 및 테스트 완료
- [x] `app/services/kakao_mobility.py` — 길찾기(거리·소요시간·택시요금·통행료) 호출 및 테스트 완료
- [x] `app/services/upstage_client.py` — Solar LLM(`solar-pro2`) + Embedding(query/passage, 4096차원) 호출 및 테스트 완료
- [x] `app/services/supabase_client.py` — Supabase 연결 확인 + pgvector 확장/테이블/검색 함수 세팅 완료 (`insert_place`, `search_similar_places`로 실제 강릉 관광지 임베딩 저장·유사도 검색까지 테스트 성공, Step 4 RAG 기반 작업 미리 완료)
- [x] `app/utils/cache.py` — API 응답 캐싱(JSON) 구현. `cached_call()`로 감싸서 `kakao_mobility.get_route()`에
      적용 완료 (같은 출발지-도착지 조합은 24시간 캐시 재사용 — 실측 0.56초 → 0.02초). 목적은 속도뿐 아니라
      TourAPI 429 같은 할당량 보호 + API 장애 시 Fallback도 겸함.
- [x] `data/sample/` — API 실패 대비 샘플 데이터 확보 (`sample_places.json`은 불필요 판단으로 스킵 — 위 참고)
  - [x] `sample_routes.json`: 카카오모빌리티 장애 대비, `summarize_route()`와 동일한 형식(distance_km/
        duration_min/taxi_fare/toll_fare)으로 강릉 데모 시나리오 구간 3개 작성
  - [x] `sample_plan.json`: `TripPlanResponse` 스키마와 동일한 형식으로 강릉 1박2일 전체 응답 예시 작성
        (README 15절 예시 기반, 현재 스키마의 `route_summary` 필드 포함하도록 갱신)

---

## Step 3. State 및 Agent 기본 흐름 구현

- [x] `app/core/state.py` — `TripRouteState` TypedDict 정의 (README 9절 필드 기준)
- [x] `app/core/prompts.py` — Agent별 프롬프트 템플릿 관리. Coordinator의 Solar 파싱 프롬프트를
      `upstage_client.py`에서 분리해 `COORDINATOR_PARSE_SYSTEM_PROMPT`로 이관 완료. Route
      Planner/Financial은 아직 자체 LLM 프롬프트가 없어서 추가할 게 생기면 이 파일에 계속 보탤 것
- [x] `app/agents/coordinator.py` — 자연어 입력 분석 및 조건 추출 (도시·계절·기간·취향·일정강도).
      `이동수단`/`인원수`는 자연어 추출 대상이 아니라 Gradio UI의 체크박스/숫자 입력값을 그대로 받아
      덮어씀 (README 6절 설계대로).
  - [x] "로컬만 아는 곳/사람 안 몰리는 곳" 같은 표현을 인식해서 `condition_summary`에 hidden-gem
        선호 신호(`prefer_local`)로 남기기 완료 (Solar 프롬프트 필드 추가 + Mock parser 키워드 매칭
        fallback). Route Planner의 `_sort_by_prefer_local()`에서 review_count 기반 정렬로 실제
        반영까지 완료됨(아래 route_planner.py 항목 참고).
  - [x] Mock parser(Solar API 장애 시 fallback) 개선 — 원래 사용자 입력을 무시하고 강릉 고정값만
        반환하던 것을, `city`/`prefer_local`만큼은 키워드 매칭으로 실제 입력을 반영하도록 수정
  - [x] **prefer_budget**("가성비" 등 예산 중시 표현) / **is_peak_season**(성수기 여행 여부)
        신호 추가 — `prefer_local`과 동일한 패턴(Solar 프롬프트 필드 + Mock 키워드 fallback).
        route_planner.py의 숙박 선택 로직과 financial.py의 성수기 요금 반영에서 사용.
- [x] `app/agents/route_planner.py` — 관광지 후보 생성 로직에 Supabase RAG 연동 완료.
      `_search_rag_places()`가 취향 문장을 임베딩해 `match_places` RPC(도시 필터 추가, 아래 참고)로
      해당 도시 관광지 중 유사도 top-N을 가져오고, 실패/결과 없음이면 기존 TourAPI 실시간 검색으로,
      그것도 실패하면 Mock으로 넘어가는 3단계 fallback 구조. RAG 결과는 좌표가 없어서 선택된
      후보만 `get_detail_common()`으로 좌표/지역코드를 보완함(`_fill_missing_place_details`).
  - [x] `places.review_count` 기반으로 `prefer_local` 신호에 따라 필터링/정렬하는 로직 완료
        (`_sort_by_prefer_local`) — `prefer_local=true`면 review_count 낮은 순, 아니면 높은 순.
        review_count가 없는(Google Places 매칭 실패) 장소는 배제하지 않고 뒤쪽에 배치.
  - [x] `match_places` Supabase 함수를 `city_filter` 파라미터 + `rating`/`review_count`/`category`/
        `address` 반환 컬럼을 갖도록 재정의 (SQL Editor에서 수동 실행, `places` 테이블 자체는
        안 건드림 — 함수만 교체)
  - [x] `tests/test_route_planner.py` 작성 — 정렬 로직, taste_text 생성, RAG 경로 end-to-end
        (mocking) 테스트 5건 추가
  - [x] **연관 관광지 추천 로직 교체**: TourAPI `TarRlteTarService1`(T맵 내비게이션 기반 "관광지별
        연관 관광지 정보")이 제공 기간(2024.05~2025.04) 만료로 어떤 조회를 해도 0건만 반환하는 걸
        확인 — 대신 관광공사가 직접 큐레이션한 **여행코스**(contentTypeId=25) 데이터를 활용.
        `tour_api.py`에 `get_detail_info()`(반복정보조회) 추가, 선택된 장소가 어떤 여행코스의
        하위 장소로 포함돼 있는지 찾아서 같은 코스의 다른 장소를 연관 장소로 추천
        (`_search_course_related_places`) — 실제 데이터로 매칭 성공 확인함(안목해변 → 자디마루/
        경포호/호텔n리조트 등). 코스 구성은 자주 안 바뀌어서 `app/utils/cache.py`로 7일 캐싱 적용.
        기존 `_search_real_related_places`/`related_place_api.py` 의존 코드는 제거함.
  - [x] **다일차 코스 구간 제한**: 코스 하위 장소엔 "몇 일차"인지 구분이 없어서, 5일 코스인데
        2일 여행이면 다른 날짜 구간 장소가 섞일 수 있었음 — 매칭된 장소의 코스 내 순서 기준
        앞뒤 2개(`COURSE_NEARBY_WINDOW`)만 추천하도록 근사치 제한 추가, 라이브 검증 완료.
  - [x] **지리적 효율성 필터링**: RAG는 취향 유사도만 보고 거리를 안 봐서, 취향 1등과 2등이
        도시 반대편이어도 그대로 동선에 들어가는 문제 발견 — `_filter_places_within_radius()`로
        하버사인 거리 계산해 취향 1등 기준 15km(`MAX_CANDIDATE_DISTANCE_KM`) 이내 후보만
        순차 채택하도록 수정.
  - [x] **여행코스 데이터 보강**: 도시당 코스가 너무 적어(경주·전주·서울 0건) 연관 장소 추천
        풀이 좁던 문제 — `ingest_city()`가 여행코스(addr1 없는 경우 대부분)를 주소 필수 필터로
        다 걸러내던 버그를 고치고 재수집, 10개 도시 총 96건으로 보강 완료
        (도시별 수치는 `docs/api_notes.md` 2절 참고).
  - [x] **연관 장소도 거리 필터 적용**: 처음엔 `_filter_places_within_radius()`가 RAG 후보
        (`candidate_places`)에만 적용되고 코스 매칭으로 붙는 `related_places`는 거리 검증 없이
        그대로 합쳐지는 걸 재점검 중 발견 — `anchor_places` 파라미터를 추가해 이미 확정된
        candidate_places 군집 기준으로 related_places도 15km 이내인지 걸러지도록 수정.
        테스트로 검증(anchor 기준 먼 곳 배제 확인).
  - [x] **추천 이유(reason) 장소별 개인화**: 기존엔 검색 배치 전체가 동일한 reason 문자열을
        공유해서(예: "RAG 유사도가 높은 강릉 지역 관광지입니다."가 모든 장소에 똑같이 붙음)
        일정표의 "추천 이유" 열이 획일적이었음 — `_build_place_reason()`을 추가해 장소별
        category/rating/review_count를 반영하도록 수정(`_normalize_rag_place`/
        `_normalize_tour_place`). 실제 실행 확인: "리뷰 686개, 평점 4.2의 인기 관광지..."처럼
        장소마다 다르게 나옴.
  - [x] **식사 시간대 카테고리 배정**: 점심/저녁 시간대에 음식점이 아니라 아무 장소나 배치되던
        문제 — `_reorder_places_for_time_slots()`로 `category == "음식점"`인 장소를 점심/저녁
        슬롯에 우선 배정. 다만 RAG 랭킹 상위권에 음식점이 아예 안 뽑히는 경우가 있어(취향
        유사도만 보고 카테고리를 안 보므로), `_search_lodging_place`와 동일한 패턴으로
        `_search_restaurant_places()`를 추가해 점심/저녁 슬롯 수만큼 음식점 후보를 별도로
        확보. real_api(TourAPI 실시간 검색) fallback 경로는 애초에 `category`를 채운 적이
        없던 것도 같이 발견해 고침(`_normalize_tour_place`).
  - [x] **일정 강도별 관광지 개수 차등화**: `_build_time_slots()`가 "보통"/"빡빡한 일정"을
        구분 없이 똑같이 취급하고, "여유로운 일정"은 점심 슬롯 자체가 없던 구조를 재설계 —
        이제 관광지 슬롯 개수는 일정 강도로 정해짐(빡빡한 일정=하루 3개, 그 외=2개)이고
        점심/저녁은 강도와 무관하게 항상 포함(겨울철 저녁 제외, 마지막 날 저녁 제외 규칙은
        유지). 테스트 4건 추가.
- [x] `app/agents/financial.py` — 비용 계산 로직에 실측 데이터 반영 완료.
  - [x] **입장료(admission_cost)**: TourAPI `detailIntro2`의 usefee(비정형 텍스트)를
        `parse_usefee_amount()`(Upstage 구조화 추출, `FINANCIAL_USEFEE_PARSE_SYSTEM_PROMPT`)로
        성인 1인 요금만 뽑아냄. 무료/파싱불가는 구분해서 처리, 실패 시 기본값(5,000원) 대체.
  - [x] **숙박비 선택 보장**: Route Planner가 1박 이상이면 `_search_lodging_place()`로 숙박
        후보를 명시적으로 하나 골라 `route_plan["lodging_place"]`에 담아 넘김 (RAG가 우연히
        골라주길 기다리지 않음). 이미 선택된 관광지 군집과 15km 이내, prefer_budget이면
        실제 요금 최저가, 아니면 rating 최고 순으로 선택 — 정렬 후 그중 **실제 요금 데이터가
        있는 첫 후보**를 우선 선택(동점/전부 없음이면 원 순위 유지).
  - [x] **숙박비(lodging_cost) 실측**: TourAPI `detailInfo2`(객실 목록)에서 인원수(roommaxcount
        기준 수용 가능 객실, 초과 시 객실 여러 개로 근사)와 성수기(`is_peak_season`) 반영해서
        1박 요금 계산 (`app/utils/cost_rules.py`의 `estimate_lodging_fee_per_night` 등 —
        Route Planner의 숙박 선택 시점과 동일 로직 재사용). 요금 필드가 "0"으로 등록된
        데이터 오류 케이스 발견 후 `to_positive_int()`로 방어 처리.
  - [x] 교통비 계산 시 하드코딩됐던 `travel_days=2`를 daily_schedule에서 실제 일수를 세도록 수정.
  - [x] `tests/test_financial.py`/`tests/test_route_planner.py`에 usefee 파싱, 인원수별 객실
        수용 여부, 성수기 요금, 0원 데이터 방어, 실요금 우선 선택 테스트 추가.
- [x] `app/graph/nodes.py` — 각 Agent를 LangGraph 노드로 래핑 완료 (`parse_trip_request`/
      `route_planner`/`financial`/`finalize` 4개 노드). `app/core/state.py`의 `TripRouteState`를
      실제로 사용하도록 필드 확장(`total=False` + `warnings`/`react_trace`는
      `Annotated[..., operator.add]` 리듀서로 누적). `react_trace`가 하드코딩된 6단계 설명이
      아니라 실제 노드 실행 기록으로 바뀜(4단계).
- [x] `app/graph/edges.py` — 노드 실행 순서 정의 완료(`LINEAR_EDGES`). 단, TripRoute Workflow는
      분기 없는 선형 파이프라인이라 조건부 분기(`add_conditional_edges`)는 아직 없음 — RAG
      실패 시 real_api/mock으로 넘어가는 fallback은 여전히 `route_planner.py` 내부 try/except로
      처리 중(`docs/langgraph_workflow.md` "남은 여지" 참고).
      > **보류 (나중에 확장 시 진행)**: RAG/real_api/mock 검색을 별도 노드로 쪼개고 조건부
      > 엣지로 라우팅하면 `react_trace`에 어떤 데이터 소스를 탔는지 명시적으로 남고 향후
      > 검색 소스 추가도 쉬워지지만, `build_route_plan()`이 이 fallback 말고도 코스 검색/
      > 음식점 확보/재배치/동선 계산까지 한 함수에 다 있어서 분리 범위가 넓음. 데이터 소스를
      > 추가하거나 fallback 경로 디버깅이 실제로 필요해지는 시점에 진행.
- [x] `app/graph/workflow.py` — 그래프 조립 완료. `StateGraph(TripRouteState)`에 4개 노드를
      선형으로 연결(parse → route_planner → financial → finalize)하고 `compile()`, 모듈 로드
      시 1회 컴파일해 재사용. `app/agents/coordinator.py`는 이 그래프를 호출하는 얇은
      wrapper로 축소(함수 시그니처/반환 형태 그대로 유지돼 react_loop.py/main.py/gradio_app.py
      수정 불필요). 상세 내용은 `docs/langgraph_workflow.md` 참고.
- [x] Supabase 기반 LangGraph Checkpoint 저장 연결 — `app/graph/checkpointer.py`에서
      `SUPABASE_DB_URL`(REST API용 `SUPABASE_URL`과 별개, Postgres 직접 연결 문자열)로
      `PostgresSaver` 생성, `graph.compile(checkpointer=...)`로 연결. `thread_id`(보통
      대화 세션 id)는 `coordinator.py`/`react_loop.py`/`main.py`/`gradio_app.py`까지
      배선 완료. 연결 실패 시(설정 안 함/네트워크 문제) 경고만 남기고 체크포인트 없이
      기존과 동일하게 동작(graceful fallback), DNS 일시 오류 대비 재시도(3회) 로직 포함.
      Supabase pooler(transaction 모드)가 prepared statement를 지원 안 해서 나던
      `DuplicatePreparedStatement` 에러는 `prepare_threshold=None`으로 해결. 실제
      Supabase Postgres에 체크포인트 행이 쌓이는 것까지 라이브 검증 완료.
- [x] `/trip/plan` 엔드포인트에서 Workflow end-to-end 실행 확인 완료 (FastAPI `TestClient`로
      실제 Solar/RAG/TourAPI/Kakao Mobility 연동까지 호출해 정상 응답 확인)

---

## Step 4. RAG 구현

- [x] 관광지 설명 데이터 수집 (TourAPI 개요 텍스트) — 강릉·속초·춘천·부산·제주·경주·전주·여수·인천·서울
      10개 도시 × 관광지/문화시설/축제/여행코스/레포츠/숙박/쇼핑/음식점 8개 카테고리 수집 완료
      (약 1100건). 수집 중 발견된 이슈와 대응은 `docs/api_notes.md` "TourAPI 대량 수집 이슈" 참고.
- [x] `app/rag/embedder.py` — Upstage Embedding으로 관광지 설명 벡터화
- [x] `app/rag/vector_store.py` — Supabase pgvector 테이블 생성 및 임베딩 저장
      (`ingest_city`/`ingest_cities`), category·축제 개최기간(`event_start_date`/`event_end_date`)·
      Google Places 평점(`rating`/`review_count`) 백필 함수까지 포함
- [x] `app/rag/retriever.py` — 사용자 취향 문장 임베딩 → 유사도 검색 (`city` 필터 파라미터 추가)
- [x] Route Planner에서 RAG 검색 결과 연동 완료 (`_search_rag_places`, Step 3 참고)
- [x] RAG 유사도 점수를 Route Planner 추천 로직에 반영 — `similarity`는 결과에 포함되지만
      최종 정렬 기준은 review_count(`prefer_local`) 우선. RAG는 "취향에 맞는 후보 풀"을 좁히는
      역할이고, 그 안에서 순서는 review_count로 정함
- [x] **평점/리뷰수 보강**: TourAPI/카카오/네이버 모두 별점·리뷰 데이터가 없어서 Google Places
      API(New)를 추가 연동함 (`app/services/google_places_api.py`). 이름 텍스트 검색만으로는
      전혀 무관한 곳이 매칭되는 사고가 있어(예시는 api_notes.md 참고), TourAPI 좌표(mapx/mapy)
      기반 `locationBias`(500m 반경)로 오매칭을 방지함 — **좌표 없이 이름만으로 호출하지 말 것.**

---

## Step 5. 동선 및 비용 계산 고도화

- [x] `app/utils/transport_rules.py` — 대중교통 휴리스틱 (시간 ×1.7, 거리 기반 요금) +
      자차/렌터카/택시 분기(`estimate_transport_cost`) — 팀원 PR로 구현돼 있었고 그대로 사용 중
- [x] `app/utils/cost_rules.py` — 식비·카페비 추정 규칙(고정) + 입장료·숙박비는 실측 데이터
      기반으로 확장 완료 (아래 Financial Agent 항목 참고)
- [x] Route Planner — 카카오 API 기반 구간별 이동시간 계산 및 State 기록 (`_build_real_routes`,
      `route_summary`/`route_segments`에 기록됨 — 팀원 PR로 이미 구현돼 있었음)
- [x] Route Planner — 하루 일정 과밀도 체크 (일정 강도·계절 반영) 완료.
      `_check_daily_density()`: 하루 단위 구간 이동시간 합이 일정 강도별 기준(여유
      180분/빡빡 300분)을 넘으면 경고. `_build_time_slots()`에 `season` 파라미터 추가 —
      겨울이면 일조시간이 짧다고 보고 저녁 슬롯을 제외(예: 여유+1일 기준 여름 3슬롯 →
      겨울 2슬롯), 관련 경고 문구도 추가. 라이브 검증 완료(강릉 1박2일: 여름 5슬롯 vs
      겨울 4슬롯). 테스트 5건 추가.
- [x] Financial Agent — 이동수단별 비용 분기 (자차/렌터카/택시/대중교통) — `transport_rules`
      재사용, 하드코딩됐던 `travel_days=2`도 실제 daily_schedule 기준으로 수정
- [x] Financial Agent — TourAPI usefee 비정형 텍스트 파싱 (Upstage 구조화 활용) 완료
      (`parse_usefee_amount`, `FINANCIAL_USEFEE_PARSE_SYSTEM_PROMPT`). 숙박비도 `detailInfo2`
      객실 요금으로 실측 반영(인원수/성수기 고려), 요금 "0" 데이터 오류 방어 처리 포함.
- [x] Financial Agent — State의 route_segments를 읽어 총 예상 비용 산정 완료
      (`build_financial_summary`가 route_plan의 route_summary/daily_schedule/selected_places/
      lodging_place를 모두 읽어서 계산)

---

## Step 6. 최종 출력 포맷 구성

- [x] `app/utils/formatter.py` — State → 최종 응답 Markdown 포맷 변환 완료 (섹션별 함수로 분리:
      `format_condition_summary`/`format_daily_schedule`/`format_route_summary`/
      `format_cost_summary`/`format_warnings`/`format_react_trace`)
- [x] 조건 요약 출력
- [x] 시간대별 일정표(Day/시간대/장소/추천이유/동선메모) 출력
- [x] 예상 비용표 출력 (교통비·식비·카페비·입장료·숙박비·총액)
- [x] 주의사항(warnings) 출력 — 대중교통 추정치 안내 문구 포함 확인(`finalize` 노드에서
      `transport_mode == "대중교통"`일 때 항상 추가)
- [x] Gradio UI에서 결과 렌더링 (표 형태) — 챗봇 버블이 아니라 탭형 결과 패널로 분리 렌더링
- [x] **UX: 파이프라인 진행상황 표시 + 최종 문장 스트리밍**
  - [x] 앞 단계(관광지 검색 → RAG → 동선 계산 → 비용 계산) 진행 중 Gradio 상태 메시지 표시
        (예: "관광지 찾는 중...", "동선 계산 중...", "비용 계산 중...")
  - [x] Coordinator의 최종 문장 생성(추천 이유·일정 설명) 부분은 Upstage `stream=True` +
        Gradio `yield` 기반으로 타이핑 효과 스트리밍 (SSE 직접 구현 불필요)
  - [x] 주의: `cost_summary`/`route_summary` 같은 계산된 수치 데이터는 스트리밍 대상이 아니라
        계산 완료 시 한 번에 표시됨 — 스트리밍은 자연어 텍스트 부분에만 적용

---

## Step 7. 테스트 및 시연 준비

- [x] `tests/test_route_planner.py` — 동선 설계 로직 테스트 (RAG/코스/거리/밀도/숙박 선택 등 다수)
- [x] `tests/test_financial.py` — 비용 계산 로직 테스트 (usefee 파싱, 숙박 요금, 성수기 등)
- [x] `tests/test_rag.py` — RAG 검색 테스트 (파일만 있고 내용 비어있음 — retriever.py 직접
      테스트하는 케이스는 아직 없음, route_planner 테스트가 간접적으로만 커버 중)
- [x] API 실패 시 `data/sample/` fallback 처리 검증
- [x] 시연용 대표 시나리오(예: 강릉 1박2일) end-to-end 동작 확인
- [x] `docs/` 문서 정리 (architecture, api_notes, state_design)
- [x] 발표용 아키텍처 다이어그램 및 실행 화면 캡처

---

## Step 8. Docker 컨테이너화 및 CI/CD 기반 GCP 배포

> 배포 대상이 원래 계획했던 **Cloud Run이 아니라 GCE(Compute Engine) VM**으로 바뀌었습니다.
> FastAPI 한 컨테이너 안에서 `/ui` 경로로 Gradio까지 같이 서빙(별도 서비스 분리 안 함).

- [x] 배포 대상 서비스 확정 — GCE VM 한 대에 Docker Compose로 컨테이너 실행(Cloud Run 아님)
- [x] `Dockerfile` 작성 (멀티스테이지 빌드: 의존성 빌드용 `builder` + 실행용 `runtime`,
      non-root `appuser`로 실행) — `docker-compose.prod.yml` 헬스체크가 정상 통과하는 것으로
      로컬/운영 컨테이너 실행 자체는 확인됨
- [x] CI/CD 파이프라인 구성 — GitHub Actions 2단계로 완료:
      `ci.yml`(PR/main push 시 ruff lint + pytest) →
      `cd.yml`(CI 성공 시 Docker 이미지 빌드 → **GHCR**(Artifact Registry 아님) push →
      SSH로 GCE VM에 `docker compose up` 배포 → `curl localhost:8000` 헬스체크)
- [x] 배포 및 외부 접속 URL로 최종 시연 확인

---

## 핵심 설계 원칙 (전 단계 공통 준수)

- **State 중심 결합**: Agent 간 직접 호출 대신 `TripRouteState`를 매개로 데이터 공유
- **Coordinator가 흐름 제어**: 입력 분석 → 하위 Agent 디스패치 → 최종 조립 담당
- **대중교통은 휴리스틱**: 실시간 환승 API 미사용, 결과에 반드시 추정치 안내 문구 포함
- **Fallback 우선**: API 장애/호출 제한 대비 캐시·샘플 데이터 상시 유지
- **MVP 범위 고정**: 지도 시각화·실시간 재최적화·예약/결제는 제외 (로그인/대화 세션은 Step 9에서 범위에 추가되어 구현됨)

---

## MVP 범위 요약

**포함**: 로그인/회원가입 · 대화 세션 저장 · 멀티턴 후속 요청 · 자연어 입력 · 이동수단 선택 · 인원수 · 관광지 후보 조회 · RAG 취향 매칭 · Google Places 평점 기반 필터링 · 카카오 기반 동선 · 대중교통 휴리스틱 · 일정표 · 예상 비용 · Gradio UI · FastAPI 엔드포인트 · GCP GCE VM 배포

**제외**: 숙소/식당 예약 · 결제/예매 · 실시간 교통 · 실시간 대중교통 환승 · 지도 시각화 · 장기 개인화 · 모바일 앱

---

## Step 9. 로그인 및 대화 세션 관리 (MVP 확장)

> 원래 8단계 계획에는 없었으나, 로그인 후 대화를 이어가며 일정을 수정하는 흐름이 필요해져 범위에
> 추가됨. 구현 상세는 `docs/tech_architecture.md` 4-1/7절 참고.

- [x] `app/services/auth_client.py` — Supabase Auth 기반 회원가입/로그인
- [x] `app/services/chat_store.py` — 로그인 사용자의 대화 세션(`chat_sessions`)/메시지(`chat_messages`)
      저장·조회, service_role 키로 접속하므로 세션 소유자 검증은 코드에서 직접 수행
- [x] `app/schemas/request.py`의 `previous_condition_summary`/`previous_result`/`thread_id` —
      멀티턴 후속 요청("맛집 위주로 바꿔줘", "3일로 늘려줘") 처리, LangGraph 체크포인터와 연동
- [x] UI 다크 3단 레이아웃(사이드바/결과패널/요청)으로 재구성, 새 대화 시작 시 사이드바에서 새 세션
      바로 선택 표시

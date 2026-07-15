# LangGraph State 설계

TripRoute의 Coordinator / Route Planner / Financial Agent는 `app/core/state.py`의
`TripRouteState`(TypedDict, `total=False`)를 통해 데이터를 주고받는다. 각 노드는 State
전체가 아니라 자신이 갱신한 필드만 담은 dict를 반환하고, LangGraph가 이를 기존 State에
병합한다.

## 필드 목록

### 사용자 입력

| 필드 | 타입 | 설명 |
|---|---|---|
| `user_input` | `str` | 사용자의 원문 자연어 입력 |
| `transport_mode` | `str` | 이동수단 (자차/렌터카/대중교통/택시) |
| `people_count` | `int` | 여행 인원수 |
| `previous_condition_summary` | `Optional[Dict]` | 직전 턴의 조건 요약. 멀티턴 후속 요청("맛집 위주로 바꿔줘")에서 이전 조건을 이어받는 데 사용 |
| `previous_result` | `Optional[Dict]` | 직전 턴의 전체 결과(`daily_schedule`/`route_summary` 포함). 기간 연장·슬롯 교체 후속 요청에서 기존 일정을 유지한 채 일부만 재구성하는 데 사용 |

### Coordinator 파싱 결과 (`parse_trip_request`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `city` / `season` / `duration` | `str` | 여행 도시 / 계절 / 기간 |
| `travel_style` | `List[str]` | 여행 취향 리스트 |
| `schedule_intensity` | `str` | 일정 강도 ("여유로운 일정" / "빡빡한 일정" 등) |
| `prefer_local` | `bool` | 로컬/한적한 곳 선호 여부 (review_count 기반 정렬에 반영) |
| `prefer_budget` | `bool` | 가성비 선호 여부 (숙박비 최저가 선택 등에 반영) |
| `is_peak_season` | `bool` | 성수기 여행 여부 (숙박 요금 계산에 반영) |
| `must_include_places` | `List[str]` | 사용자가 명시적으로 콕 집은 장소 |
| `parser` | `str` | 파싱 경로 ("solar" 또는 "mock") |
| `target_day` / `target_time_slot` | `Optional[int]` / `Optional[str]` | 슬롯 교체 후속 요청("2일차 점심만 바꿔줘")에서만 채워짐 |
| `move_source_day` / `move_source_time_slot` / `move_destination_day` / `move_destination_time_slot` | `Optional[int]` / `Optional[str]` | 장소 이동/맞바꾸기 후속 요청("2일차 관광지를 1일차로 옮겨줘")에서만 채워짐 |
| `daily_preferences` | `List[Dict]` | 일차별 취향/강도 오버라이드. 언급 안 된 날짜는 전체 공통값을 따름 |

### Route Planner 결과 (`build_route_plan`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `candidate_places` | `List[Dict]` | RAG/TourAPI 기반 관광지 후보 |
| `rag_ranked_places` | `List[Dict]` | RAG 유사도 검색 결과 |
| `related_places` | `List[Dict]` | 여행코스 데이터 기반 연관 관광지 |
| `selected_places` | `List[Dict]` | 최종 일정에 배치된 장소 |
| `route_summary` | `List[Dict]` | 구간별 거리/이동시간/택시비/통행료 |
| `daily_schedule` | `List[Dict]` | 시간대별 일정표 |
| `lodging_place` | `Optional[Dict]` | 선택된 숙박 장소 |
| `data_source` | `str` | 이번 응답이 어떤 경로(RAG/실시간 API/Mock)로 만들어졌는지 |

### Financial 결과 (`build_financial_summary`)

| 필드 | 타입 | 설명 |
|---|---|---|
| `cost_summary` | `Dict` | 교통비/식비/카페비/입장료/숙박비/총액 |

### 공통 누적 필드

| 필드 | 타입 | 설명 |
|---|---|---|
| `warnings` | `Annotated[List[str], operator.add]` | 대중교통 추정치, API 실패 등 주의사항. 노드마다 반환한 리스트가 기존 값 뒤에 이어 붙음 |
| `react_trace` | `Annotated[List[Dict], operator.add]` | 실제 실행된 노드 기록(`parse_trip_request`/`build_route_plan`/`build_financial_summary`/`finalize_response`) |

### 최종 조립 결과

| 필드 | 타입 | 설명 |
|---|---|---|
| `result` | `Dict` | `finalize` 노드가 조립한 최종 응답(`condition_summary`/`daily_schedule`/`route_summary`/`cost_summary`/`warnings`/`react_trace`) |

## 병합 규칙

- 대부분의 필드는 LangGraph 기본 동작대로 **마지막에 쓴 값으로 교체**된다.
- `warnings`, `react_trace`만 `operator.add` 리듀서로 **누적**된다 — 각 노드가 자신의 몫만 반환해도 이전 노드가 쌓아둔 값이 사라지지 않는다.

## 노드별 State 흐름

```
[parse_trip_request]
  user_input, previous_condition_summary → city/season/duration/travel_style/... 채움
        ↓
[route_planner]
  city/travel_style/prefer_local/... → candidate_places/route_summary/daily_schedule/lodging_place 채움
        ↓
[financial]
  daily_schedule/route_summary/lodging_place → cost_summary 채움
        ↓
[finalize]
  전체 State → result 조립
```

자세한 노드/엣지 연결은 `docs/langgraph_workflow.md`, LangGraph 도입 배경은
`docs/architecture.md` 참고.

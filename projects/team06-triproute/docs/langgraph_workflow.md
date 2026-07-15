# TripRoute LangGraph Workflow 연결

TripRoute의 Coordinator/Route Planner/Financial Agent는 `app/graph/workflow.py`가 조립하는
LangGraph `StateGraph(TripRouteState)`로 연결되어 있다.

## 노드와 엣지

`app/graph/nodes.py`가 Coordinator/Route Planner/Financial Agent 경계를 그대로 노드 경계로
쓴다(각 Agent의 로직 자체는 건드리지 않고, 그 호출을 노드로 감싸기만 함):

| 노드 | 하는 일 |
|---|---|
| `parse_trip_request` | Solar API/Mock parser로 입력 파싱, 파싱 결과를 State 필드로 분해 |
| `route_planner` | `build_route_plan()` 호출, 관광지/동선/일정 결과를 State에 반영 |
| `financial` | `build_financial_summary()` 호출, 비용 요약을 State에 반영 |
| `finalize` | 최종 응답(`condition_summary`/`daily_schedule`/`route_summary`/`cost_summary`/`warnings`/`react_trace`) 조립 |

`app/graph/edges.py`의 `LINEAR_EDGES`가 `parse → route_planner → financial → finalize` 4단계를
조건 분기 없이 그대로 연결한다. 그래프는 모듈 로드 시 한 번만 `compile()`되어 재사용된다.

각 노드는 실행되며 자기 자신의 `react_trace` 항목 1개씩을 반환한다 — 트레이스는 미리 적어둔
설명이 아니라 **실제로 그 노드가 실행됐다는 기록**이다.

`app/agents/coordinator.py`(`run_triproute_coordinator`)는 이 그래프를 호출하는 얇은
wrapper다. 함수 시그니처와 반환 dict 형태를 그대로 유지하고 있어, `react_loop.py`/`app/main.py`
(FastAPI)/`ui/gradio_app.py` 등 호출부는 그래프 도입과 무관하게 동일하게 동작한다.

State 필드 전체 목록은 `docs/state_design.md`, 후속 요청(기간 연장/슬롯 교체/장소 이동)에 따른
Route Planner 분기는 `docs/tech_architecture.md` 3-3절 참고.

## 남은 여지 (지금은 안 한 것)

- 노드 4개는 여전히 각 Agent 함수를 통째로 호출하는 수준이라, `build_route_plan()` 내부(장소 검색/연관 장소/동선 계산)를 더 잘게 쪼개 별도 그래프 노드로 만들면 트레이스가 더 세분화되고 조건부 재시도(예: RAG 실패 시 real_api로, 그마저 실패 시 mock으로) 같은 로직을 엣지의 조건부 분기(`add_conditional_edges`)로 명시적으로 표현할 수 있다. 지금은 그 fallback 로직이 여전히 `build_route_plan()` 내부에 `try/except`로 감춰져 있음 — 필요해지면 다음 단계로 고려.

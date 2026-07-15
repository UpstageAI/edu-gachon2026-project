# app/graph/ — LangGraph 에이전트 정의

질문 한 건이 들어와서 답변이 나가기까지의 전체 흐름(분류 → 조회 → 판정 → 생성)을 정의합니다.

| 파일 | 역할 |
|---|---|
| `state.py` | `AgentState` TypedDict — 노드 간 주고받는 상태(질문, 라우트, 품목, 가격, 판정, 답변 등) |
| `router.py` | 1차 라우터(`router_node`: LLM 구조화 출력으로 price/knowledge/hybrid/off-topic 분류 + 품목 추출, 실패 시 키워드 폴백) + 2차 방어(`validate_request_node`: 장난/대사체 문장 등 오탐 차단) |
| `graph.py` | StateGraph 배선 — 노드 등록과 조건부 분기(`_route_decision`, `_post_resolve_decision`, `_post_judge_decision`). `compiled_graph`가 최종 산출물 |
| `nodes.py` | 나머지 모든 노드와 답변 생성 로직 |

## nodes.py 주요 구성

- **`_invoke_with_prompts`** — 공통 프롬프트 + 노드별 프롬프트를 2개의 SystemMessage로 LLM에 전달, 마크다운 강조(`**`) 제거
- **`search_knowledge_node`** — 제철·보관법 지식 RAG. ChromaDB `food_knowledge` 컬렉션에서 검색한 문서만 근거로 답변(문서 없으면 "정보 없음" 안내, 지어내지 않음)
- **`search_substitute_node`** — 비쌈 판정 품목의 대체품을 ChromaDB에서 **같은 부류(축산물/채소류 등) 안에서만** 유사도 검색
- **`resolve_processed_items_node` / `compare_items_node`** — 시나리오 1(쌀 vs 즉석밥): KAMIS 원물 + 참가격 가공식품 비교, 밥 1공기 환산
- **`search_processed_price_node`** — 가공식품 단독 조회(참치캔 등): 매칭 상품 전부의 평균가 나열(판정 없음)
- **`generate_answer_node`** — 최종 답변 생성 + 3중 하드개런티(품목명 언급 / 시작 문장-판정 일치 / 퍼센트 수치 조작 검증), 실패 시 결정론적 템플릿으로 폴백

## 그래프 흐름

```text
START → router → [off-topic → 거절 / 그 외 → validate_request(2차 검증)]
  → price·hybrid → user_input(지역/단위 확보) → get_raw_price → resolve_processed_items
       ├ 원물+가공 2개 조합 → compare_items ────────┐
       ├ 전부 KAMIS에 없음 → search_processed_price ─┤
       └ 그 외 → judge_price → [비쌈 → search_substitute] ─┤
  → knowledge → search_knowledge ────────────────────┤
                                              generate_answer → END
```

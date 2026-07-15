# LangGraph 재설계 구현 정리

이 문서는 대화를 통해 합의한 설계(관련성 검증 루프, 결정론적 검색, 알레르기 disclose 처리,
현재 조리 단계 힌트 등)를 실제 코드에 반영한 결과를 정리한다. "왜 이렇게 바꿨는지"의 배경
논의는 `langgraph-design-review.md`를 참고하고, 이 문서는 **최종적으로 코드에 무엇이
들어갔는지**에 집중한다.

## 1. Graph 1 — 레시피 추천 (`app/agent/graph.py`)

### 변경 핵심

기존에는 `react_agent`가 `generate_sql`/`execute_sql` 도구를 스스로 호출해 LLM이 매번 SQL을
새로 작성하는 방식이었다. 이 방식은 `ORDER BY` 없이 `LIMIT 20`만 강제해 결과가 비결정적이고,
"카레+양파를 넣었는데 카레 계열이 하나도 안 나오는" 문제의 원인이었다.

**후보 검색은 결정론적 알고리즘으로, 결과가 적절한지 판단만 LLM으로** 바꿨다.

### 노드 구성

| 노드 | 파일 | 역할 |
|---|---|---|
| `resolve_inputs` | `nodes/resolve_inputs.py` | (변경 없음) id → 이름 변환 |
| `input_guardrail` | `nodes/input_guardrail.py` | (변경 없음) 재료 미선택 차단 |
| `search_recipes` | `nodes/search_recipes.py` (신규) | `search_service.search_recipes()` 호출. 재료 매칭 개수 기준 결정론적 검색 |
| `rank_candidates` | `nodes/rank_candidates.py` | (변경 없음) 알레르기 필터 + 부족 재료 오름차순 top 3 |
| `verify_relevance` | `nodes/verify_relevance.py` (신규) | `relevance_service.verify()` 호출. LLM이 관련성/재료 활용도 판단 |
| `broaden_search` | `nodes/broaden_search.py` (신규) | `min_match`↓, `search_limit`↑, `retry_count`+1 후 `search_recipes`로 루프백 |
| `best_effort_response` | `nodes/best_effort_response.py` (신규) | 재시도 소진 + 후보 존재 시, 단서를 달아 최선의 후보 반환 |
| `ask_clarification` | `nodes/ask_clarification.py` (신규) | 재시도 소진 + 후보 0건일 때만 재료 추가 요청 |

### 그래프 흐름

```
search_recipes → rank_candidates → verify_relevance
                                        │
                          relevance_passed=True → respond
                                        │ False
                                        ▼
                          retry_count < 1(MAX_SEARCH_RETRIES)?
                              Yes → broaden_search → (search_recipes로 루프)
                              No  → candidate_recipes 존재?
                                      Yes → best_effort_response → respond
                                      No  → ask_clarification → respond
```

라우팅은 다이어그램의 "관련성 통과?"/"재시도<MAX?"/"후보 존재?" 3개 판단 다이아몬드를 별도
노드로 만들지 않고, `graph.py`의 `_route_after_verify_relevance()` 함수 하나로 구현했다 —
이 코드베이스의 기존 관례(`_route_after_input_guardrail` 등)와 일치시키기 위함이다.

### 새 State 필드 (`app/agent/state.py`)

```python
min_match: int = 2       # 후보로 인정할 최소 재료 매칭 개수 (broaden_search가 낮춤)
search_limit: int = 20   # search_recipes가 가져올 후보 상한 (broaden_search가 늘림)
retry_count: int = 0
relevance_passed: bool = False
relevance_reason: str | None = None
low_confidence: bool = False
```

### 새 검색 로직 (`app/agent/services/search_service.py`)

```python
def search_recipes(ingredient_ids, min_match, limit):
    recipe_ids = find_recipe_ids_by_ingredient_ids(ingredient_ids)
    ...
    # 각 후보의 실제 재료 id와 ingredient_ids 교집합 크기(match_count)를 계산
    # match_count >= min_match인 것만 남기고, match_count 내림차순 정렬 후 limit개 반환
```

Supabase 클라이언트 기반(`app/data/repositories/recipe_repository.py`에 추가한
`find_recipe_ingredient_matches`, `get_recipes_by_ids`)으로
구현해 기존 리포지토리 패턴과 일치시켰고, LLM이 SQL을 짜는 방식보다 재현 가능하고 SQL
인젝션 표면도 없앴다. 재료명 대신 id로 매칭해 ingredients_master 이름 왕복 조회를 없애고,
자유 입력 표기 차이로 인한 매칭 누락도 방지한다.

### Agent 프롬프트 — `verify_relevance` (`app/agent/prompts/verify_relevance_prompt.py`)

```
사용자가 가진 재료: {selected_ingredients}

추천 후보 레시피 목록 (이름과 부족한 재료):
{candidates_repr}

이 후보들이 사용자가 가진 재료를 활용하기에 적절한지 판단하라.
- 후보가 하나도 없으면 통과 실패(passed=false)로 판단한다.
- 후보 레시피들이 사용자가 가진 재료와 명백히 무관해 보이거나(예: 카레와 양파를 가졌는데
  카레 계열 레시피가 전혀 없는 경우), 대부분의 재료가 부족해 실제로 만들기 어려워 보이면
  통과 실패로 판단한다.
- 그 외에는 통과(passed=true)로 판단한다.

reason에는 왜 그렇게 판단했는지 한두 문장으로 간단히 적어라. 통과 실패로 판단했다면,
사용자에게 그대로 보여줘도 자연스러운 문장으로 적어라(예: "재료 활용도가 낮아 보여요").
```

구조화 출력(`VerifyRelevanceOutput`): `passed: bool`, `reason: str`.

---

## 2. Graph 2 — STT 음성 질의 (`app/agent/voice_graph.py`)

### 변경 핵심

Graph 1과 달리 이 그래프는 **구조를 바꾸지 않았다.** 실제 코드는 처음부터
`voice_react_agent ↔ voice_tool_node` ReAct 루프 하나로 모든 질문 유형(대체재/알레르기/조리
방법 등)을 처리하고 있었고, "질문 유형별 분기"는 시스템 프롬프트 한 줄
("대체 질문이면 도구 호출, 아니면 일반 지식으로 답변")로 이미 구현되어 있었다. 대화 중
설계했던 `question_router`/`cooking_step_lookup` 같은 명시적 노드들은 이 실제 구조와 맞지
않아 채택하지 않았고, 대신 **시스템 프롬프트를 확장**해 다음을 반영했다:

1. 현재 조리 단계 텍스트를 참고용 힌트로 제공 (제약 아님)
2. 알레르기 발화를 "조회"와 "새 알레르겐 disclose"로 구분해 disclose는 대체재 탐색으로 위임
3. 확신이 낮아도 회피하지 말고 최선의 답을 먼저 제시 (best-effort 원칙)

### State/API 변경

- `VoiceQueryState.current_step_text: str | None` 필드 추가 (`app/agent/voice_state.py`)
- `VoiceQueryRequest.current_step_text: str | None` 필드 추가 (`app/api/schemas/request.py`) —
  FE가 지금 화면에 보여주는 스텝 원문을 보내는 용도. **저장하지 않음**, 이번 응답에만 반영.
- `run_voice_query()`/`voice_query` 라우트가 `current_step_text`를 그대로 전달 (`app/agent/voice_graph.py`, `app/api/routes/voice_query.py`)
- `cooking_step_lookup` 같은 별도 조회 노드는 만들지 않았다 — 조리 단계는 DB에 저장되지 않고
  FE 로컬 state로만 존재하므로 "조회"할 근거 데이터가 없고, 실제로는 일반 지식 기반 답변과
  동일하게 처리하는 게 기존 코드와 일치한다.

### Agent 프롬프트 — `VOICE_SYSTEM_PROMPT` (`app/agent/nodes/voice_query_nodes.py`)

```
당신은 '뚜이', 영화 <라따뚜이>의 레미처럼 요리를 진심으로 사랑하는 작은 생쥐 셰프입니다.
지금 사용자 옆에서 함께 요리하며 부지런히 돕고 있습니다.

말투는 딱딱한 설명문이 아니라, 요리를 좋아하는 친구가 옆에서 같이 고민해주듯
다정하고 활기차게 답하세요. 사용자를 믿어주고 응원하되, 수다스럽게 늘어지지 말고
핵심은 분명하고 실용적으로 전달하세요.

현재 조리 중인 레시피: {recipe_name} (분류: {recipe_category}).
사용자의 알레르기 성분: {allergies}.
현재 조리 단계: {current_step_text}
(이건 참고용 맥락일 뿐입니다. 이 단계 내용을 벗어나는 질문이어도 일반 조리 지식을
활용해 자유롭게 답하세요 — 이 단계에 없는 내용이라고 답변을 거부하지 마세요.)

재료 대체나 생략 가능 여부를 물으면 반드시 find_substitutes 도구로 확인한 뒤 답하세요.
알레르기 관련 발화는 두 가지로 구분하세요:
- 이미 알려진 알레르기 성분에 대해 묻는 것(조회)이면 위 정보로 바로 답하세요.
- 사용자가 기존에 없던 새로운 알레르기 성분을 언급하면(예: '저 새우도 못 먹어요'),
그 성분이 이 레시피에 들어갈 수 있는 재료라고 보고 find_substitutes로 대체재를
확인한 뒤 답하세요. 단, 이 정보는 이번 답변에만 반영되고 별도로 저장되지 않으니,
다음에도 반영되길 원하면 알레르기 설정 화면에서 저장하라고 안내하세요.
그 외 조리 방법/순서 질문은 알고 있는 일반 조리 지식으로 답하세요.
알레르기 유발 재료는 절대 대체재로 추천하지 마세요.

확신이 낮은 질문이어도 답변을 회피하지 말고, 아는 한도 내에서 최선의 답을 먼저
제시하세요. 정말 판단이 안 서는 경우에만 무엇이 더 필요한지 되물으세요.

답변 형식 규칙:
- 한두 문단으로 나누어 답하세요. 문단 사이는 반드시 빈 줄(줄바꿈 두 번)로 구분하세요.
- 이모티콘은 전체 답변에 최대 1개까지만, 정말 어울릴 때만 쓰세요. 남발하지 마세요.
- 마크다운 문법(**볼드**, 백틱, #, 인용부호(>), 목록 기호(-) 등)은 절대 쓰지 마세요
— 화면에 그대로 텍스트로 표시됩니다.
```

### FE 연동 필요 사항 (백엔드만 반영됨, FE 작업 별도 필요)

`/cooking/voice-query` 요청 바디에 `current_step_text` 필드가 추가됐다. FE가 이 필드에
`steps[stepIndex]`(현재 화면에 보여주는 스텝 원문)를 실어 보내야 실제로 효과가 있다.
안 보내도 동작은 하지만(옵셔널 필드, 기본값 None → 프롬프트엔 "정보 없음"으로 채워짐)
그러면 이번에 추가한 힌트 기능이 무의미해진다.

---

## 3. 테스트

- `tests/unit/agent/test_search_service.py` (신규): 검색 필터링/정렬/limit 단위 테스트
- `tests/unit/agent/test_relevance_service.py` (신규): 빈 후보 단락 처리, LLM 호출 검증
- `tests/unit/agent/test_search_and_verify_nodes.py` (신규): `search_recipes`/`verify_relevance`/`broaden_search`/`best_effort_response`/`ask_clarification` 노드 단위 테스트
- `tests/integration/scenarios/test_recommend_scenario.py` (전면 재작성): 정상 흐름, 재시도 후
  성공, best-effort 폴백, 재료 0건 안내, 알레르기 제외, Phase B 대체재 시나리오
- 전체 스위트: **78 passed**

## 4. 정리 필요 항목 (orphaned, 삭제는 보류함)

`search_recipes`가 후보 검색을 대체하면서 아래 파일들이 더 이상 그래프에 연결되지 않는다.
Git이 없는 로컬 디렉터리라 되돌리기가 어려워 **직접 삭제하지 않고 남겨뒀다** — 새 흐름을
검증한 뒤 필요 없다고 판단되면 지워도 된다.

- `app/agent/nodes/react_agent.py`, `app/agent/nodes/tool_node.py`
- `app/agent/services/recipe_sql_service.py`
- `app/agent/prompts/generate_sql_prompt.py`, `app/agent/prompts/react_agent_prompt.py`
- `app/agent/tools/recipe_tools.py`의 `generate_sql`/`execute_sql`, `tools/registry.py`의 `ALL_TOOLS`
- 이들을 단위로 테스트하던 `tests/unit/agent/test_react_agent.py`, `tests/unit/agent/test_tool_node.py` (여전히 통과하지만 대상 코드가 죽은 경로)

`app/data/sql_executor.py`(SQL 검증/실행 계층)와 `tests/unit/data/test_sql_executor.py`는
그대로 두었다 — 이 계층 자체는 여전히 유효한 안전장치 코드이고, 재사용 여지도 있다.

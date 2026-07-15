# LangGraph Agent 구현 계획 — Text-to-SQL + SQL 안전장치 + 2단계 추천 흐름

> 대상 범위: 재료 ID·알레르기 ID 입력 → 레시피 후보 3개 추천 → 사용자 선택 → 선택 레시피 상세 판단(생략/대체) → 검증 → 응답 생성, 그리고 조리 중 STT 음성 질의(B흐름)까지의 LangGraph 에이전트 코어.
> 전체 로드맵(Day1~7) 중 **2단계(MVP)~4단계(검증)**, 즉 Day3~6에 해당하는 부분을 구체화한다. Day1~2 데이터 적재, Day7 배포는 본 문서 범위 밖.

## 0. 설계 원칙

- **Tool은 얇게, Service는 두껍게.** Tool은 Pydantic 스키마 검증 + Service 호출만 담당하고, 실제 DB 쿼리·비즈니스 로직은 Service Layer에 둔다. 이렇게 하면 Tool을 LangGraph 없이도(유닛 테스트에서) 직접 호출 가능.
- **판단은 구조화된 출력으로.** 분류·검증처럼 LLM이 판단하는 단계는 반드시 Pydantic 모델로 구조화된 출력을 받는다(자유 텍스트 파싱 금지).
- **Text-to-SQL은 LLM이 SQL을 직접 생성하는 방식(Option A)으로 구현한다.** 수업 목표(LLMOps·LangGraph 실습)상 Agent가 도구를 스스로 판단·실행하는 걸 보여줘야 하므로, "파라미터화된 쿼리 빌더"가 아니라 실제 자유 SQL 생성을 채택한다. 대신 실행 전 반드시 안전장치(읽기 전용 role, 화이트리스트 검증, 쿼리 타임아웃)를 거친다.
- **재료·알레르기는 프론트에서 ID 목록으로 전달받아 그대로 사용한다.** 자유 텍스트 파싱, 동의어 정규화, 서버 측 `user_id` 기반 알레르기 조회는 하지 않는다.
- **세션 상태(Checkpointer)를 사용하지 않는 Stateless 설계.** `ingredient_ids`/`allergy_ids`/`recipe_id`를 매 요청 파라미터로 전달받으며, 멀티턴 재판단·대화 상태 누적은 다루지 않는다.
- **ReAct 루프는 두 개의 독립된 진입점(그래프)으로 나뉜다.** "후보 추천" 그래프는 검색만, "선택 레시피 상세" 그래프는 분류·대체재 판단만 담당한다. 이렇게 나누는 이유는 대체재 판단(LLM 호출)을 선택되지 않은 후보에는 수행하지 않기 위함이다(불필요한 LLM 호출 절감).

## 1. 디렉토리 구조

```
RatBox-BE/app/
├── main.py                          # FastAPI 앱, 라우터 등록만
├── api/
│   └── routes/
│       ├── recommend.py             # POST /recipes/recommend (1단계, SSE)
│       ├── detail.py                # POST /recipes/{recipe_id}/detail (2단계, SSE)
│       └── voice_query.py           # POST /cooking/voice-query (B흐름, 단발 응답)
├── agents/
│   ├── state.py                     # RecommendState, DetailState, VoiceQueryState (Pydantic)
│   ├── graph.py                     # build_recommend_graph(), build_detail_graph(), build_voice_query_graph()
│   └── nodes/
│       ├── input_guardrail.py
│       ├── react_agent.py           # ReAct 판단 노드 (Tool binding, 그래프별로 분리 사용)
│       ├── validate.py              # 제약(알레르기) 위반 재검증
│       ├── output_guardrail.py
│       └── respond.py               # 최종 응답 생성 (SSE/단발 공용)
├── tools/
│   ├── schemas.py                   # 모든 Tool의 Input/Output Pydantic 스키마
│   ├── sql_tools.py                 # generate_sql, execute_sql (Text-to-SQL + 안전장치 경유)
│   ├── classification_tools.py      # classify_missing_ingredients
│   ├── substitute_tools.py          # find_substitutes (LLM 판단, DB 조회 아님)
│   └── registry.py                  # RECOMMEND_TOOLS, DETAIL_TOOLS, VOICE_TOOLS
├── services/
│   ├── sql_safety_service.py        # 읽기 전용 role 연결, 화이트리스트 검증(sqlglot), 쿼리 타임아웃
│   ├── recipe_service.py            # SQL 실행 결과 파싱 + 알레르기 필터링 + 부족재료 개수 정렬(상위 3개)
│   ├── substitute_service.py        # LLM 기반 대체재/생략가능 판단
│   └── guardrail_service.py         # 입력/출력 가드레일 판정 로직
├── schemas/
│   └── domain.py                    # Ingredient, Recipe, Allergen 등 공용 도메인 모델
├── core/
│   └── llm.py                       # Upstage Solar Pro(ChatUpstage) 클라이언트 팩토리
└── db/
    ├── supabase_client.py           # 기존 (쓰기 가능 role, 필요한 경우만 사용)
    └── supabase_readonly_client.py  # 신규, DATABASE_URL_READONLY(ratbox_readonly) 사용
```

**기존 대비 삭제된 것**: `services/ingredient_service.py`(동의어 정규화), `services/rag_service.py`, `tools/rag_tools.py`, `core/checkpointer.py`. `nodes/extract.py`(자연어 재료 추출)도 삭제 — 입력이 이미 ID 목록이라 추출 자체가 불필요.

## 2. 단계별 구현 계획

### Step 1 — State 스키마 정의 (`agents/state.py`)

그래프별로 필요한 state만 최소한으로 정의한다. Checkpointer가 없으므로 각 state는 요청 하나의 생명주기 동안만 존재한다.

```python
class RecommendState(BaseModel):
    messages: list[AnyMessage]
    ingredient_ids: list[str]
    allergy_ids: list[str] = []
    candidate_recipes: list[RecipeCandidate] = []
    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    final_answer: str | None = None

class DetailState(BaseModel):
    messages: list[AnyMessage]
    recipe_id: str
    allergy_ids: list[str] = []
    missing_classification: ClassificationResult | None = None
    substitutes: list[SubstituteResult] = []
    guardrail_blocked: bool = False
    final_answer: str | None = None

class VoiceQueryState(BaseModel):
    messages: list[AnyMessage]
    recipe_id: str
    allergy_ids: list[str] = []
    target_ingredient: str | None = None
    intent: Literal["substitute", "omit_check"] | None = None
    final_answer: str | None = None
```

- `messages`만 `add_messages` reducer로 누적, 나머지 필드는 override.
- 멀티턴/누적 로직(`excluded_ingredients` 등)은 제거되었다 — 후속 피드백 재판단 루프는 이번 범위에서 다루지 않기 때문.

**DoD**: 세 State가 각각 Pydantic으로 정의되고, `messages` reducer 동작을 확인하는 유닛 테스트.

### Step 2 — SQL 안전장치 서비스 (`services/sql_safety_service.py`) — 최우선 구현

LLM이 SQL을 직접 생성하는 방식을 채택했으므로, Tool 구현보다 먼저 안전장치부터 갖춘다.

- `ratbox_readonly` 읽기 전용 DB role 커넥션 준비 (`DATABASE_URL_READONLY`)
- 생성된 SQL을 `sqlglot` 등으로 파싱해 다음을 검증:
  - `SELECT`문인지 (INSERT/UPDATE/DELETE/DROP 등 원천 차단)
  - 화이트리스트 테이블(`recipes`, `recipe_ingredients`, `ingredients_master`, `allergen_master`)만 접근하는지
- 쿼리 타임아웃 설정 (`statement_timeout`)

```python
class SQLSafetyService:
    ALLOWED_TABLES = {"recipes", "recipe_ingredients", "ingredients_master", "allergen_master"}

    def validate(self, sql: str) -> SQLValidationResult:
        parsed = sqlglot.parse_one(sql)
        if parsed.key.upper() != "SELECT":
            raise UnsafeSQLError("SELECT 문만 허용됩니다.")
        tables = extract_table_names(parsed)
        if not tables.issubset(self.ALLOWED_TABLES):
            raise UnsafeSQLError(f"허용되지 않은 테이블 접근: {tables - self.ALLOWED_TABLES}")
        return SQLValidationResult(is_safe=True)
```

**DoD**: SQL Injection 시도 문자열, DDL(`DROP TABLE`), DML(`DELETE FROM`), 화이트리스트 밖 테이블 접근 시도가 전부 거부되는 유닛 테스트. 정상 SELECT 쿼리는 통과하는 테스트도 함께.

### Step 3 — Service Layer 구현 (`services/*.py`)

- `RecipeService.search_by_sql(sql: str) -> list[RecipeRow]`: `sql_safety_service.validate()` 통과 후 읽기 전용 커넥션으로 실행.
- `RecipeService.filter_by_allergy(recipes, allergy_ids) -> list[RecipeCandidate]`: `ingredients_master.allergen_id`가 `allergy_ids`에 해당하는 재료가 포함된 레시피 제외.
- `RecipeService.sort_by_missing_count(recipes, ingredient_ids) -> list[RecipeCandidate]`: 레시피별 부족 재료 개수를 계산해 오름차순 정렬 후 상위 3개 반환.
- `SubstituteService.judge(ingredient_name, recipe_context, intent) -> JudgmentResult`: DB 조회가 아닌 LLM 호출로 "생략 가능한가" 또는 "대체재는 무엇인가"를 판단 (B흐름의 생략가능 질의도 이 Service를 공유).
- `GuardrailService.check_input(payload) -> GuardrailVerdict`: 부적절 요청 판정.
- `GuardrailService.filter_allergens(result, allergy_ids) -> (filtered, violations)`: 알레르기 재료 하드 필터링.

**DoD**: Supabase 없이도 동작 확인 가능한 유닛 테스트(mock/fixture). 특히 `sort_by_missing_count`의 정렬 로직과 `filter_by_allergy`의 제외 로직을 중점적으로 테스트.

### Step 4 — Pydantic Tool Schema 정의 (`tools/schemas.py`)

```python
class GenerateSQLInput(BaseModel):
    ingredient_ids: list[str] = Field(..., description="사용자가 선택한 재료 ID 목록")
    schema_context: str = Field(..., description="쿼리 대상 테이블 스키마 설명")

class GenerateSQLOutput(BaseModel):
    sql: str
    설명: str

class ExecuteSQLInput(BaseModel):
    sql: str

class ExecuteSQLOutput(BaseModel):
    rows: list[dict]
    row_count: int

class ClassifyMissingInput(BaseModel):
    recipe_id: str
    ingredient_ids: list[str]

class ClassifyMissingOutput(BaseModel):
    필수재료: list[str]
    생략가능: list[str]
    이유: str

class FindSubstitutesInput(BaseModel):
    ingredient_name: str
    recipe_id: str

class FindSubstitutesOutput(BaseModel):
    대체재: list[str]
    이유: str
```

- `ClassifyMissingOutput`, `FindSubstitutesOutput`처럼 **판단이 들어가는 출력은 반드시 `이유` 필드를 포함**한다(근거 명시 원칙).
- 각 스키마는 `Field(description=...)`를 촘촘히 채운다 — Solar Pro의 `bind_tools`에 그대로 전달되는 tool spec이 되므로 설명 품질이 tool 선택 정확도에 직결된다.

**DoD**: 모든 스키마에 description이 채워져 있고, `model_json_schema()` 출력을 눈으로 확인. Solar Pro(`ChatUpstage`)의 `with_structured_output`/`bind_tools`로 스모크 테스트.

### Step 5 — Tool 구현 (`tools/*.py`)

```python
@tool("generate_sql", args_schema=GenerateSQLInput)
def generate_sql(ingredient_ids: list[str], schema_context: str) -> GenerateSQLOutput:
    ...  # LLM 호출로 SQL 생성

@tool("execute_sql", args_schema=ExecuteSQLInput)
def execute_sql(sql: str) -> ExecuteSQLOutput:
    sql_safety_service.validate(sql)  # 실행 전 필수 검증
    rows = recipe_service.search_by_sql(sql)
    return ExecuteSQLOutput(rows=rows, row_count=len(rows))
```

`registry.py`에서 그래프별 Tool 목록을 분리한다:
- `RECOMMEND_TOOLS = [generate_sql, execute_sql]`
- `DETAIL_TOOLS = [classify_missing_ingredients, find_substitutes]`
- `VOICE_TOOLS = [find_substitutes]` (B흐름은 대체재/생략 판단 Tool만 필요)

**DoD**: 각 Tool을 LangGraph 없이 직접 `.invoke({...})` 호출해 스키마 검증 + Service 연동 확인. `execute_sql`에 안전장치를 우회하는 SQL을 넣었을 때 차단되는지 확인.

### Step 6 — 그래프 구성 (`agents/graph.py`) — 2개 진입점 + B흐름

**후보 추천 그래프**
```
input_guardrail → react_agent(RECOMMEND_TOOLS) ⇄ tool_node → filter+sort → respond(SSE, 3개 후보) → END
```

**선택 레시피 상세 그래프**
```
react_agent(DETAIL_TOOLS) ⇄ tool_node → validate → output_guardrail → respond(SSE, 조리단계+대체재) → END
```

**조리 중 음성 질의 그래프 (B흐름)**
```
react_agent(VOICE_TOOLS) ⇄ tool_node → validate(알레르기 충돌만 확인) → respond(단발 텍스트) → END
```

- 세 그래프 모두 Checkpointer 없이, 요청마다 새로운 state 인스턴스로 실행된다.
- `react_agent` 노드: `llm.bind_tools(TOOLS)` 호출 → `tool_calls` 있으면 `tool_node`로, 없으면 다음 단계로 조건부 라우팅.
- 무한루프 방지: `recursion_limit` 설정 + 진입 횟수 카운트, 임계치 초과 시 안전 응답으로 강제 종료.

**DoD**: 후보 추천/상세판단/음성질의 각 그래프가 최소 3개 시나리오로 정상 종료(무한루프 없음)하는지 확인, Langfuse(추후) 또는 로그로 Tool 호출 순서 확인.

### Step 7 — 결과 검증 & 가드레일 노드

- `validate` 노드: `guardrail_service.filter_allergens`로 최종 결과에 알레르기 재료가 남아있는지 재검사.
- `output_guardrail` 노드: 남아있으면 자동 제외 후 `guardrail_reason`에 기록.
- `input_guardrail`은 후보 추천 그래프의 최초 진입점 — 차단 판정 시 즉시 `END`로 라우팅하고 고정 반려 메시지 반환.

**DoD**: 알레르기 재료가 섞인 인위적 테스트 케이스에서 최종 응답에 해당 재료가 0건인지 확인(목표: 알레르기 노출 0건).

### Step 8 — FastAPI 통합 + SSE + STT (`api/routes/*.py`)

- `POST /recipes/recommend` (`ingredient_ids`, `allergy_ids`) → 후보 추천 그래프 실행, SSE로 후보 3개 스트리밍.
- `POST /recipes/{recipe_id}/detail` (`allergy_ids`) → 상세 그래프 실행, SSE로 레시피명·조리단계·대체재 스트리밍.
- `POST /cooking/voice-query` (`recipe_id`, `allergy_ids`, `audio`) → Google Cloud Speech-to-Text로 텍스트 변환 → 음성질의 그래프 실행 → 단발 텍스트 응답 (SSE 아님).
- 이벤트 타입(SSE 엔드포인트용): `status`(현재 노드/도구 실행 중), `token`, `final`, `error`.

**DoD**: `curl -N`으로 SSE 응답이 순서대로 흘러나오는지 확인. `voice-query`는 오디오 샘플로 STT 변환 정확도와 응답 지연을 확인하는 스모크 테스트.

### Step 9 — 테스트 & 관찰가능성

- **유닛**: Service/Tool 단위(Supabase mock, SQL 안전장치 우회 시도 포함).
- **통합**: 세 그래프를 합쳐 5~10개 시나리오(정상/재료 0건/알레르기 위반 시도/SQL Injection·DDL·DML 시도/후보 3개 미만/음성질의 알레르기 충돌)로 실행.
- **Langfuse**: MVP 이후 연동 예정 — 이번 범위에서는 로그 기반으로 Tool 호출 순서만 확인.

**DoD**: 기획서의 KPI(핵심 루프 성공률 80%, 알레르기 노출 0건)를 시나리오 테스트 결과로 수치화.

## 3. 확정된 설계 이슈 (변경 이력)

| 이슈 | 결정 |
|---|---|
| Text-to-SQL 방식 | ~~구조화 필터(Option B)~~ → **Option A(LLM 직접 SQL 생성) + 안전장치**로 확정 |
| `ingredient_substitutes` 테이블 | ~~스키마 신규 설계 필요~~ → **불필요**, 대체재는 LLM이 레시피 맥락으로 즉석 판단 |
| `ingredient_synonyms` 활용 | ~~정규화에 사용~~ → **미사용 확정**, 재료는 목록 선택(ID)만 지원, 자유 입력 없음 |
| 알레르기/재료 전달 방식 | ~~`user_id` 기반 서버 조회~~ → **프론트가 ID 목록을 직접 전달**로 확정 |
| Checkpointer 사용 여부 | ~~멀티턴 상태 유지~~ → **미사용, Stateless 확정** (후속 피드백 재판단 루프 제외) |
| RAG(pgvector 유사 레시피 검색) | 이번 범위 제외 |
| 레시피 추천 개수/판단 시점 | 부족 재료 개수 오름차순 정렬 → 상위 3개 우선 제공, **대체재 판단은 사용자가 선택한 1개에만 수행** |
| STT 서비스 | Google Cloud Speech-to-Text로 확정 |
| B흐름 질의 범위 | 대체재 요청 + 생략 가능 여부 질문만 포함, **조리 중 알레르기 추가·변경 언급은 반영하지 않음**(Stretch) |

## 4. 로드맵 매핑

| Step | 내용 | 대략적 Day |
|---|---|---|
| 1 | State 정의 | Day 3 |
| 2 | SQL 안전장치 (최우선) | Day 3 |
| 3~5 | Service, Pydantic Tool Schema, Tool 구현 | Day 3 |
| 6 | 후보추천/상세판단 그래프 구성 | Day 3~4 |
| 7 | 검증/가드레일 노드 | Day 4~5 |
| 8 | FastAPI + SSE (뼈대 Day4 → STT 통합 Day5) | Day 4~5 |
| 9 | 테스트/관찰가능성 | Day 6 |
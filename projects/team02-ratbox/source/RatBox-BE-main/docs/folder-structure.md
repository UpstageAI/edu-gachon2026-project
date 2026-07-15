# 폴더 구조 — 레이어드 아키텍처 매핑

5개 레이어(Presentation / API·Controller / Business Logic / Data Access / Database)를 실제 폴더에 1:1로 매핑한다. 각 레이어는 자기 책임만 가지고 아래 레이어에만 의존하는 단방향 흐름을 유지한다(예: `api/`가 `agent/`를 호출하고, `agent/`가 `data/`를 호출 — 역방향 의존 금지).

```
RatBox/
├── RatBox-FE/                          # === Presentation Layer ===
│   └── src/
│       ├── api/
│       │   ├── client.ts                # FastAPI REST 호출 래퍼
│       │   └── sse.ts                    # SSE 연결 및 이벤트 파서 (status/token/final/error)
│       ├── hooks/
│       │   └── useRecommendStream.ts     # SSE 상태를 구독하는 훅
│       ├── components/
│       │   ├── ChatInput.tsx             # 재료/알레르기 입력 폼
│       │   ├── StreamingStatus.tsx       # "재료 검색 중..." 등 판단 과정 표시
│       │   ├── RecipeCard.tsx
│       │   └── RecipeDetail.tsx
│       ├── pages/
│       │   └── HomePage.tsx
│       └── types/
│           └── recipe.ts
│
└── RatBox-BE/
    ├── app/
    │   ├── main.py                       # FastAPI 앱 생성, 라우터/미들웨어 등록
    │   ├── core/
    │   │   ├── config.py                  # env 설정
    │   │   ├── cors.py                    # CORS 설정
    │   │   └── llm.py                     # LLM 클라이언트 팩토리 (function calling)
    │   │
    │   ├── api/                          # === API / Controller Layer ===
    │   │   ├── routes/
    │   │   │   └── recommend.py           # POST /recommend (SSE 스트리밍 응답)
    │   │   ├── schemas/                    # 요청/응답 DTO (Pydantic)
    │   │   │   ├── request.py
    │   │   │   └── response.py
    │   │   └── deps.py                     # 요청 검증, 의존성 주입(인증 등)
    │   │
    │   ├── agent/                         # === Business Logic Layer ===
    │   │   ├── state.py                    # AgentState (Pydantic) — 멀티턴 상태
    │   │   ├── graph.py                    # LangGraph 그래프 조립 (ReAct 루프)
    │   │   ├── checkpointer.py             # 세션(thread_id)별 상태 유지
    │   │   ├── nodes/
    │   │   │   ├── input_guardrail.py       # 부적절/무관 입력 차단
    │   │   │   ├── extract.py               # 자연어 → 재료/알레르기 구조화 추출
    │   │   │   ├── react_agent.py           # 도구 선택 판단 (bind_tools)
    │   │   │   ├── validate.py              # 제약 위반 재검증
    │   │   │   ├── output_guardrail.py      # 알레르기 재료 최종 필터링
    │   │   │   └── respond.py               # 자연어 응답 생성
    │   │   ├── tools/                       # Pydantic Tool Schema + Tool 함수
    │   │   │   ├── schemas.py                # Input/Output Pydantic 모델
    │   │   │   ├── recipe_tools.py           # search_recipes (Text-to-SQL Tool)
    │   │   │   ├── classification_tools.py   # classify_missing_ingredients
    │   │   │   ├── substitute_tools.py       # find_substitutes
    │   │   │   └── rag_tools.py              # search_similar_recipes (pgvector)
    │   │   ├── services/                     # 도구가 호출하는 순수 판단 로직 (DB 비의존)
    │   │   │   └── guardrail_service.py       # 알레르기/욕설 판정 규칙
    │   │   └── prompts/                       # 역할별 프롬프트 (역할 분리 원칙)
    │   │       ├── extract_prompt.py
    │   │       ├── classify_prompt.py
    │   │       └── respond_prompt.py
    │   │
    │   ├── data/                           # === Data Access Layer ===
    │   │   ├── supabase_client.py           # 클라이언트 초기화, 커넥션 관리 (기존 파일)
    │   │   ├── sql_executor.py               # LLM이 뽑은 조건을 안전하게 쿼리로 실행
    │   │   │                                 #   (자유 SQL 실행 대신 파라미터 바인딩 + 화이트리스트)
    │   │   ├── repositories/
    │   │   │   ├── recipe_repository.py       # recipes / recipe_ingredients 조회
    │   │   │   ├── ingredient_repository.py   # ingredients_master / ingredient_synonyms
    │   │   │   └── substitute_repository.py   # ingredient_substitutes
    │   │   └── mappers/
    │   │       └── recipe_mapper.py            # DB row(dict) → 도메인 객체 매핑
    │   │
    │   └── domain/                          # 레이어 공통 도메인 모델 (순수 데이터 클래스)
    │       └── models.py                      # Recipe, Ingredient, SubstituteCandidate 등
    │
    ├── db/                                 # === Database Layer (실행 코드 아님, 스키마 정의) ===
    │   ├── migrations/
    │   │   ├── 0001_init.sql
    │   │   ├── 0002_recipe_ingredients.sql
    │   │   └── 0003_ingredient_substitutes.sql   # 대체재 테이블 (신규 필요)
    │   └── schema.sql                             # 전체 스키마 스냅샷 (문서용)
    │
    ├── tests/
    │   ├── unit/
    │   │   ├── data/                        # repository/mapper 테스트 (Supabase mock)
    │   │   ├── agent/                        # tool/service 테스트
    │   │   └── api/                          # 라우트 테스트
    │   └── integration/
    │       └── scenarios/                    # 시나리오 10개 통합 테스트
    │
    └── docs/
        ├── langgraph-agent-plan.md           # 에이전트 구현 계획
        └── folder-structure.md               # 본 문서
```

## 레이어 ↔ 폴더 대응표

| 레이어 | 폴더 | 의존 방향 |
|---|---|---|
| Presentation | `RatBox-FE/src/` | API Layer 호출만 (SSE/REST) |
| API / Controller | `app/api/` | `agent/`(Business Logic) 호출, `data/` 직접 참조 금지 |
| Business Logic | `app/agent/` | `data/repositories/`를 통해서만 DB 접근, Supabase 클라이언트 직접 사용 금지 |
| Data Access | `app/data/` | `db/` 스키마를 대상으로 쿼리 실행, 상위 레이어(agent/api) 모름 |
| Database | `db/` (Supabase 관리형 PostgreSQL) | 최하위, 어떤 코드도 의존하지 않음 |

## 기존 계획서와 달라진 점

- `docs/langgraph-agent-plan.md`의 `tools/services/schemas`가 최상위 폴더였던 것을 이번엔 **레이어 이름 기준**으로 재배치: `services/`는 DB 접근용이 아니라 "가드레일 판정처럼 DB 없이도 되는 순수 로직"만 남기고, DB 접근은 전부 `data/repositories/`로 이동.
- Text-to-SQL을 "LLM이 생성한 동적 SQL 실행"이라고 명시했지만, 실제 `sql_executor.py`는 자유 SQL 문자열을 그대로 실행하지 않고 파라미터 바인딩 + 화이트리스트 검증을 거치도록 유지(이전 대화에서 flag한 SQL Injection 리스크 완화). 완전한 자유 SQL이 꼭 필요하면 이 파일 안에서만 예외적으로 허용하고 읽기 전용 계정으로 제한.
- `ingredient_substitutes` 마이그레이션(`0003`)은 아직 존재하지 않음 — Business Logic Layer의 대체재 Tool 작업 착수 전에 먼저 추가해야 함.

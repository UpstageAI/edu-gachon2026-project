# LangGraph 에이전트 설계 점검 및 개선 보고서

> 2026-07-11. 재료 ID 기반 stateless 그래프로 전환한 이후, 실제 구현이 `docs/langgraph-agent-plan.md`가
> 목표한 "Agent가 도구를 스스로 판단·실행"을 실질적으로 달성하고 있는지 점검하고 개선한 기록.

---

## 1. 기존 로직 (개선 전)

### 1.1 그래프 구조

그래프는 하나(`build_graph()`, `app/agent/graph.py`)이고 `recipe_id` 유무로 내부에서 분기한다.

```
resolve_inputs → input_guardrail ─┬─(recipe_id 없음)→ react_agent ⇄ tool_node → rank_candidates ─┐
                                   └─(recipe_id 있음)→ classify_and_substitute → validate → output_guardrail ─┤
                                                                                                              → respond → END
```

| 구간 | 그래프 노드? | LLM이 도구를 실제로 판단하는가 |
|---|---|---|
| Phase A: 후보 검색 (`react_agent ⇄ tool_node`) | O | 형식적으로만 O |
| Phase B: 분류+대체재 (`classify_and_substitute`) | O (그래프의 한 칸) | X — 결정론적 직접 호출 |

Phase B는 "에이전트가 도구를 자율 선택할 필요가 없는 결정론적 파이프라인"이라고 코드 주석에도 명시돼
있어 원래부터 문제 삼을 지점이 아니었다. 문제는 Phase A였다.

### 1.2 Phase A ReAct 루프의 실효성 문제

`app/agent/prompts/react_agent_prompt.py`의 기존 시스템 프롬프트는 순서를 못박아뒀다:

> "먼저 generate_sql 도구로 SQL을 만들고, execute_sql 도구로 실행해 결과를 확인하라. execute_sql
> 결과에 error가 있으면 그 이유를 참고해 generate_sql을 다시 호출해 SQL을 고쳐라. 실행에 성공해
> 후보 목록을 얻었으면 더 이상 도구를 호출하지 말고 종료하라."

유효 경로가 `generate_sql → execute_sql → (에러 시 재호출) → 종료` 하나뿐이라, 다음 파이썬 코드와
행동이 사실상 동일했다:

```python
for _ in range(2):
    sql = generate_sql(ingredients)
    result = execute_sql(sql)
    if not result.error:
        break
```

`bind_tools`/`tool_node`/조건부 엣지 없이 짜도 결과가 같다 — LangGraph의 ReAct 루프가 실질보다
형식에 가까웠다.

---

## 2. 트러블슈팅

### 2.1 "마늘/양파 같은 흔한 재료도 후보 0건" — RLS 정책 누락

**증상**: 실제 존재하는 재료(마늘, 양파)로 `/recommend`를 호출해도 항상 후보 0건.

**조사**:
1. `run_agent()`를 직접 호출해 그래프 내부 메시지를 확인 — LLM이 SQL을 정상 생성하고 실행까지
   성공(`error: null`)했는데도 `execute_sql` 결과가 `recipes: []`.
2. `ratbox_readonly` 역할로 직접 `SELECT COUNT(*)`를 날려보니 `recipes`/`recipe_ingredients`/
   `ingredients_master` 전부 0건 — 반면 같은 데이터를 `supabase-py`(anon/service key)로 조회하면
   정상적으로 나옴. 데이터는 있는데 이 역할로만 안 보임.
3. `pg_class`/`pg_policies`/`pg_roles`를 조회해 확인: 세 테이블 모두 **RLS 활성화**돼 있지만
   `ratbox_readonly`에 대한 정책이 **하나도 없었음** (`ingredients_master`에 `anon`용 정책 2개만 존재).
   `ratbox_readonly`는 `rolbypassrls = false`.

**근본 원인**: Postgres RLS는 `GRANT SELECT`를 줬어도 해당 역할에 매칭되는 정책이 없으면 기본적으로
모든 행을 숨긴다. `db/migrations/0005_readonly_role.sql`에서 `GRANT SELECT`만 주고 정책을 안 만들어서,
SQL 실행 자체는 항상 성공하지만 결과는 항상 빈 배열이었다. **앱 코드 버그가 아니라 DB 권한 설정
누락**이었다.

**조치**: `db/migrations/0007_readonly_rls_policy.sql` 추가 — `ratbox_readonly`용 SELECT 정책을
3개 테이블에 부여. Supabase SQL Editor에서 수동 실행 완료.

### 2.2 RLS 수정 후에도 남아있던 진짜 설계 결함

RLS를 고친 뒤에도 "SQL 실행이 성공했는데 0건이면 아무 판단 없이 그냥 포기한다"는 문제 자체는
남아있었다 — 프롬프트에 "0건일 때 뭘 할지" 지침이 아예 없었기 때문("성공하면 종료"만 있고
"0건도 성공(error=null)"이라 그대로 끝나버림). 이건 3절의 개선 작업으로 이어졌다.

### 2.3 브랜치 동기화 충돌

feature 브랜치를 push한 뒤 main이 15커밋 앞서있는 걸 뒤늦게 발견 — 팀원이 독자적으로 만든
`allergen_repository.py` 등과 충돌 위험이 있었다. `git merge origin/main`으로 동기화했고, 충돌
6개(`.env.example`, `requirements.txt`, `config.py`, `request.py`, `allergen_repository.py`,
`ingredient_repository.py`) 전부 "같은 파일에 서로 다른 걸 추가한" 형태라 양쪽 다 보존하는 방식으로
해결. 병합 후 테스트 48개 + `app.main` import 스모크 테스트로 검증.

또한 `.gitignore`의 `__pycache__/`가 `_pycache__/`로 오타나 있어 디렉터리 단위 무시가 깨져있던 것도
발견해 수정 (`*.pyc` 규칙 덕분에 실제 유출은 없었음).

---

## 3. 개선한 부분

### 3.1 개념 정리 — ReAct vs Router

개선에 앞서 두 패턴을 구분했다.

| | Router | ReAct |
|---|---|---|
| 판단 횟수 | 한 번 판단하고 끝 | 결과 나올 때마다 계속 다시 판단 |
| 판단 후 | 정해진 길로 쭉 감 | 도구 쓰고 → 결과 보고 → 다시 판단(루프) |
| 언제 쓰나 | 카테고리가 몇 개인지 미리 아는 문제 (예: 향후 음성질의 의도 분류) | 몇 번 시도해야 끝날지 모르는 문제 (예: SQL 재시도) |

**핵심 원칙**: 그래프가 사람 개입 없이 스스로 반복하려면, 다음 행동을 결정할 신호가 **기계(도구)에서
나와야** 한다. SQL 케이스는 `execute_sql`이 반환하는 `error`/결과 건수가 기계 신호라서 한 번의 요청
안에서 반복이 가능하다. 반대로 "사용자가 '그것도 없어요'라고 다시 말해야 아는 것"처럼 **사람의 다음
입력이 있어야 아는 신호는 그래프 반복으로 표현할 수 없고**, 여러 번의 stateless 요청 + 클라이언트가
넘겨주는 컨텍스트(예: 이미 거절된 대체재 목록)로 풀어야 한다. 이 통찰은 향후 음성질의 설계의 기반이 된다.

또한 "프롬프트를 디테일하게 쓰는 게 맞냐"는 질문에 대해: **절차를 못박는 디테일**(판단을 죽임)과
**판단 기준을 주는 디테일**(판단을 살림)을 구분해야 하며, 후자는 LangGraph를 쓰든 안 쓰든 정상적인
프롬프트 엔지니어링이라는 결론을 정리했다.

### 3.2 실제 코드 개선 — Phase A 재시도를 "진짜 판단"으로

도구 개수는 늘리지 않고(생성/실행 2개 유지), `generate_sql`에 `strategy` 파라미터를 추가해 "0건일 때
완화 검색으로 재시도할지"를 LLM이 재료 특성을 보고 직접 판단하게 만들었다.

**변경 파일**:
- `app/agent/tools/schemas.py` — `GenerateSQLInput.strategy: Literal["exact", "relaxed"]` 추가.
- `app/agent/prompts/generate_sql_prompt.py` — `strategy`별로 다른 SQL 생성 지침을 주는
  `build_generate_sql_prompt()`로 재작성. `relaxed`는 `ingredient_category` 기준 완화 또는
  `is_required=false` 재료 제외 두 가지 방법을 제시.
- `app/agent/services/recipe_sql_service.py`, `app/agent/tools/recipe_tools.py` — `strategy`를
  끝까지 관통.
- `app/agent/prompts/react_agent_prompt.py` — 절차 나열형에서 **판단 기준형**으로 재작성:
  - 에러 → exact 유지, SQL만 고쳐서 재시도
  - 0건 + 흔한 재료 → `strategy=relaxed`로 한 번만 재시도
  - 0건 + 특수/대체 불가능한 재료 → 재시도 없이 종료
  - 1건 이상 → 즉시 종료
  - relaxed로 이미 재시도했다면 결과 무관하게 종료 (무한 루프 방지)

**검증**:
- `tests/integration/scenarios/test_recommend_scenario.py`에
  `test_zero_results_retries_once_with_relaxed_strategy` 추가 — exact 0건 → relaxed 재시도 →
  결과 발견 흐름을 스크립트된 LLM으로 검증.
- 기존 `test_tool_node.py`를 `strategy` 기본값에 맞게 보정.
- 유닛+통합 테스트 49개 전부 통과.
- 커밋: `2c75c9e fix: SQL 후보 검색 0건 시 relaxed 전략으로 재시도하도록 개선`

### 3.3 실제 LLM/DB로 재검증하며 발견한 것 — "동작한다"와 "품질이 좋다"는 다른 문제

**한계 인지**: 처음 트러플오일/성게알로 검증했는데, 이 재료들이 **프롬프트 예시에 그대로 들어있어서**
LLM이 진짜 판단한 게 아니라 예시를 패턴 매칭했을 가능성이 있다는 걸 스스로 발견 — 오염된 테스트였다.
프롬프트에 없는 재료로 재검증을 시도했으나, `ingredients_master`의 모든 재료가 레시피에 최소 1건 이상
쓰이고 있어(전수 조사로 확인) 실제 데이터로는 "진짜 0건"을 자연 재현하기 어렵다는 것도 확인했다. 즉
0건 재시도 로직은 실전에서는 주로 재료명 오타/동의어 불일치, SQL 문법 오류 상황에서만 트리거될
가능성이 높고, 이는 여전히 안전망으로서 가치가 있다.

**대체재 품질 문제 발견**: 토마토야채스프(양파·마늘·셀러리 등 필요) 레시피에서 양파만 빼고 Phase B를
직접 실행해봤다.

```
분류: 양파 = 필수 재료
대체재 추천: ① 양파 → 파(쪽파/대파)   ② 양파 → 마늘
```

①은 합리적이지만, **②는 이 레시피에 마늘이 이미 별도 필수 재료로 들어있어서 부적절한 추천**이다
("같은 향신채소과"라는 얕은 유사성만으로 이미 쓰이고 있는 재료를 대체재로 추천). 코드는 에러 없이
정상 동작했지만, 요리 도메인 지식으로 보면 결과 품질에 결함이 있다 — **이런 문제는 유닛테스트로는
절대 잡을 수 없고, 사람이 직접 봐야 발견된다**는 걸 실제 사례로 확인했다.

### 3.4 대체재 품질 개선 — 레시피에 이미 있는 재료 제외

**조치**: `FindSubstitutesInput`에 `exclude_ingredients: list[str]` 필드를 추가하고,
`classify_and_substitute.py`에서 대체재를 찾을 때 현재 부족한 재료를 제외한 레시피의 나머지 재료
목록을 함께 전달하도록 수정. `SUBSTITUTE_PROMPT`에 "이미 이 레시피에 쓰이는 다른 재료는 대체재로
추천 금지" 지침 추가.

**검증**: 같은 토마토야채스프 시나리오 재실행 — 개선 전 `양파 → 파, 마늘(레시피에 이미 있음)` /
개선 후 `양파 → 파(쪽파/대파 흰부분), 샬롯`으로 확인. 마늘이 더 이상 추천되지 않고 실제로 합리적인
대체재(샬롯)가 나옴. `test_substitute_service.py`에 exclude 목록이 프롬프트에 실제로 포함되는지
검증하는 테스트 추가. 테스트 50개 전부 통과.

**커밋**: `a5d5954 fix: 대체재 추천 시 레시피에 이미 있는 재료는 후보에서 제외`

---

## 4. Langfuse 연동 (완료)

### 4.1 왜 필요한가

지금까지의 디버깅·검증 과정(마늘/양파 RLS 버그, 트러플오일 재현 시도, 양파 대체재 품질 확인)을
전부 `run_agent()`를 스크립트로 직접 호출하고 메시지를 파일에 덤프해서 눈으로 읽는 방식으로 했다.
Langfuse를 붙이면 이 과정이 자동으로 대시보드에 남는다 — 어떤 요청에서 어떤 SQL을 생성했고, 몇 건
나왔고, 재시도했는지, 최종 대체재가 뭐였는지가 한눈에 보인다.

원래 계획(`docs/Project.md`)은 "MVP 이후 연동"이었지만, **지금처럼 프롬프트/판단 로직을 반복적으로
고치고 품질을 확인해야 하는 시기에 오히려 가치가 크다** — "설계가 안정된 뒤 운영 관찰"보다 "설계를
계속 고치는 지금"이 트레이스 가시성의 ROI가 더 높다.

### 4.2 Langfuse가 해주는 것 / 못 해주는 것

- **해주는 것**: Tool 호출 순서·파라미터, LLM 응답 원문, 지연시간, 토큰 사용량을 트레이스로 자동 기록.
  "이 요청에서 왜 이런 판단을 했는지"를 스크립트 없이 바로 조회 가능.
- **못 해주는 것**: "이 대체재 추천이 요리로서 말이 되는가" 같은 **품질 판단은 자동으로 안 해준다.**
  이건 여전히 사람(또는 LLM-as-judge)이 트레이스를 보고 직접 채점해야 한다. Langfuse는 이 사람 검수를
  더 빠르게 만들어주는 도구지, 대체하는 도구가 아니다.

### 4.3 실제 구현

계획 당시엔 "`get_llm()`에 LangChain 콜백 핸들러 연결"을 상정했으나, 실제로 확인해보니
`langfuse.langchain.CallbackHandler`는 전체 `langchain` 패키지를 요구했다(이 프로젝트는
`langchain-core`/`langchain-upstage`만 사용, 무거운 의존성 추가 불필요). 대신 Langfuse v4의 OTel
기반 `@observe()` 데코레이터로 LLM 호출 지점을 직접 감싸는 방식으로 구현했다.

**변경 파일**:
- `requirements.txt` — `langfuse` 추가.
- `app/core/config.py` — `langfuse_public_key`/`langfuse_secret_key`/`langfuse_base_url` 설정 추가.
- `app/core/observability.py` (신규) — `init_langfuse()`, 키가 없으면 조용히 스킵(로컬 개발 시
  에러 없이 비활성화 클라이언트로 동작).
- `app/main.py` — 앱 시작 시 `init_langfuse()` 호출.
- `@observe()` 데코레이터 적용 지점:

  | 함수 | as_type |
  |---|---|
  | `run_agent` (그래프 전체) | 최상위 trace |
  | `run_voice_query` (음성질의 그래프 전체) | 최상위 trace |
  | `react_agent` (도구 선택 LLM 호출) | generation |
  | `voice_react_agent` | generation |
  | `generate_sql` | generation |
  | `execute_sql` | tool |
  | `classify` | generation |
  | `find` (대체재) | generation |
  | `resolve_inputs` / `voice_resolve_inputs` | span |
  | `input_guardrail` / `voice_input_guardrail` | span |
  | `tool_node` / `voice_tool_node` | span |
  | `rank_candidates` | span |
  | `classify_and_substitute` | span |
  | `validate` / `voice_validate` | span |
  | `output_guardrail` | span |
  | `respond` / `voice_respond` | span |

  CallbackHandler 없이도 트레이스 안에서 노드 실행 순서·분기·소요시간을 전부 볼 수 있도록,
  LLM 호출이 없는 노드에도 `@observe(name=...)`를 붙여 span으로 감쌌다(§4.3 CallbackHandler
  미사용 결정은 그대로 유지). CallbackHandler 기반 Langfuse "Graph View"(노드-엣지 다이어그램
  자동 렌더링)는 여전히 지원하지 않으며, 대신 트레이스 트리에서 전체 노드 시퀀스를 확인한다.

**검증**: 실제 Langfuse 프로젝트 키를 `.env`에 넣고 `client.auth_check()` → `True`, 실제
`run_agent()` 실행 후 `client.api.trace.get(trace_id)`로 조회해 `recommend_graph` trace 안에
`react_agent`(3회, ReAct 턴마다) / `generate_sql` / `execute_sql`이 자식 관찰로 정확히 중첩되어
있음을 확인. 키가 없는 환경(로컬/CI)에서도 테스트 50개 전부 통과 — 비활성화 클라이언트가 안전하게
no-op으로 동작.

**커밋**: `828215a feat: Langfuse 트레이싱 연동`

### 4.4 Langfuse가 해주는 것 / 못 해주는 것 (재확인)

붙이고 나니 4.2에서 예상한 그대로였다 — 트레이스 조회는 즉시 편해졌지만, "이 대체재가 요리로서
말이 되는가"는 여전히 사람이 트레이스를 읽고 판단해야 했다(5절의 QA 결과 참고).

---

## 5. 사람 검수 결과 (3순위, 완료)

`docs/Project.md`의 KPI("판단 정확도: ... 팀 자체 검수 — 목표 8/10 이상") 기준대로, 실제 레시피
데이터로 시나리오 7개(Phase B 6개 + Phase A 1개)를 실행해 직접 채점했다.

| # | 시나리오 | 분류(필수/생략) | 대체재 적절성 | 판단 근거 문장 품질 |
|---|---|---|---|---|
| 1 | 오이샌드위치 - 소금 누락 | ✅ optional 정확 | ⚠️ "간장" 추천 — 크림치즈 스프레드엔 안 어울릴 수 있음 | ✅ |
| 2 | 청경채새송이들깨볶음 - 청경채 누락 | ✅ required 정확 | ⚠️ "비단초" — 실존 재료명인지 불확실(환각 의심) | ✅ |
| 3 | 케일쌈밥 - 케일 누락 | ✅ required 정확 | ✅ 상추/깻잎 — 우수 | ✅ |
| 4 | 간장멸치볶음 - 마늘 누락 | ✅ required 정확 | ✅ 양파/생강 — 우수, 이미 있는 진간장 추천 안 함(3.4 exclusion 정상 작동) | ✅ |
| 5 | 크래미볶음밥 - 참치액 누락 | ✅ required 정확 | ✅ 간장/다시마육수 — 양호 | ⚠️ 결론을 냈다 뒤집는 장황하고 모순적인 문장 |
| 6 | 꽃송편 - 잣 누락 | ✅ required (최종판단 타당) | ✅ 아몬드/호박씨 — 양호 | ⚠️ 매우 장황하고 자기모순적 |
| 7 | Phase A: 두부+김치, 새우 알레르기 | — | — | 알레르기 필터는 정상(새우 포함 레시피 없음)이나, "두부냉동보관하는방법"(레시피 아닌 보관 팁)과 "조미료"(모호한 재료명)가 후보/부족재료로 섞여 나옴 — **에이전트 로직이 아닌 원본 데이터 품질 이슈** |

**종합 평가**:
- **분류(필수/생략) 판단**: 6/6 전부 타당 — 신뢰할 만함.
- **대체재 적절성**: 6개 중 4개 우수, 2개 애매(①의 간장, ②의 "비단초" — 후자는 DB에 실존하는
  재료명인지 별도 확인 필요).
- **판단 근거 문장 품질**: 6개 중 2개가 스스로 결론을 냈다 뒤집는 장황한 문장 — 사용자에게 그대로
  노출되면 신뢰도가 떨어질 수 있어 프롬프트를 더 간결하게 다듬을 여지가 있음.
- **완전히 깨끗한 케이스**: 2/6(③ 케일쌈밥, ④ 간장멸치볶음). KPI 목표(8/10)를 엄격히 적용하면
  아슬아슬한 수준 — 불합격은 아니나 여유롭게 통과라고 보기도 어려움. 정직하게 "합격선 근처, 개선
  여지 있음"으로 본다.
- **별도 발견(에이전트 로직 밖)**: 레시피 DB 자체에 조리법이 아닌 "보관 팁" 항목이 섞여 있고,
  "조미료"처럼 구체적이지 않은 재료명도 존재 — 원본 데이터 정제가 필요한 별개 이슈.

이 7개는 대표 샘플이며, `docs/Project.md`가 명시한 10~15개 규모의 정식 검수는 아직 남은 작업이다.

---

## 6. 앞으로의 구현 계획

| 순위 | 항목 | 상태 |
|---|---|---|
| 1 | 대체재 프롬프트 개선(exclude_ingredients) | ✅ 완료 (3.4) |
| 2 | Langfuse 연동 | ✅ 완료 (4절) |
| 3 | 사람 검수 기반 품질 확인 (대표 샘플 7개) | ✅ 완료 (5절) |
| 4 | 음성질의(B흐름) 신규 구현 | 남음 — 새 이슈/브랜치로 분리 |
| 5 | (선택) 그래프/엔드포인트 분리 | 남음, 낮은 우선순위 |
| 6 | (선택) 대체재 자체검증 루프 | 남음, 선택사항 |
| 7 | (신규) 판단 근거 문장 프롬프트 간결화 | 5절에서 발견, 미착수 |
| 8 | (신규) 대체재 환각 여부 검증 로직 | 5절에서 발견("비단초" 등 실존 재료명인지 확인), 미착수 |
| 9 | (신규) 레시피 DB 데이터 정제 | 5절에서 발견(보관팁/모호한 재료명 혼입), 에이전트 로직 밖 — 별도 트래킹 |

**4번(음성질의)은 별도 이슈/브랜치로 분리해 진행한다** — 이번 브랜치(`feat/#7-에이전트-핵심구현`)의
범위를 벗어나는 신규 기능이기 때문.

---

## 7. 관련 파일
- `app/agent/graph.py` — 그래프 조립, 조건부 라우팅
- `app/agent/nodes/react_agent.py`, `app/agent/nodes/tool_node.py` — ReAct 루프 구현
- `app/agent/prompts/react_agent_prompt.py` — 판단 기준형으로 재작성한 시스템 프롬프트
- `app/agent/prompts/generate_sql_prompt.py` — strategy별 SQL 생성 지침
- `app/agent/tools/schemas.py` — `GenerateSQLInput.strategy`, `FindSubstitutesInput.exclude_ingredients` 필드
- `app/agent/nodes/classify_and_substitute.py`, `app/agent/prompts/substitute_prompt.py` — Phase B,
  대체재 품질 개선
- `app/core/observability.py` — Langfuse 초기화
- `db/migrations/0007_readonly_rls_policy.sql` — RLS 트러블슈팅 조치
- `tests/integration/scenarios/test_recommend_scenario.py` — relaxed 재시도 시나리오 테스트
- `tests/unit/agent/test_substitute_service.py` — exclude_ingredients 프롬프트 반영 검증

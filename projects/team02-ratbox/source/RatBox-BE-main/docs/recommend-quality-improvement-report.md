# 추천 품질 평가 체계 구축 및 개선 보고서

> 2026-07-15. `feat/#41-추천-품질-평가-골든셋-langfuse-연동` 브랜치 작업 기록. "소금/감자/우유를
> 넣으면 들기름두부지짐이나 전복죽이 뜬다"는 버그 리포트에서 출발해, 추천 품질을 숫자로 재고 개선하는
> 체계를 만들고 실제 알고리즘을 고쳤다.

---

## 1. 배경 — 무엇이 문제였나

`/recommend`에 `소금, 감자, 우유`를 넣으면 감자·우유가 핵심인 요리(감자수프 등) 대신 소금만 우연히
겹치는 `전복죽`, `들기름두부지짐` 같은 레시피가 나왔다. 개선을 시작하기 전에 먼저 두 가지가
없었다.

- **원인이 뭔지 코드로 확인된 적이 없었다.** "소금이 흔해서 그런 것 같다"는 추정만 있었다.
- **개선 전/후를 비교할 자동화된 지표가 없었다.** `docs/langgraph-design-review.md`의 사람 검수
  7건이 유일한 품질 확인 수단이었고, 자동 회귀 테스트는 "로직이 의도대로 배선됐는지"만 확인했지
  "추천이 실제로 적절한지"는 아무것도 검증하지 않았다.

이번 작업은 **(1) 재현 가능한 평가 체계를 먼저 만들고 → (2) 그 체계로 원인을 정량적으로 확인하고
→ (3) 고친 뒤 같은 체계로 개선폭을 다시 측정**하는 순서로 진행했다.

---

## 2. 원인 조사 — 코드와 실제 DB로 재현

`app/agent/services/search_service.py`(검색), `app/agent/services/recipe_service.py`(랭킹),
`app/agent/services/relevance_service.py`(LLM 검증) 3곳을 실제 Supabase 데이터로 직접 재현해 원인을
찾았다.

1. **가중치 없는 매칭**: `find_recipe_ingredient_matches`가 반환한 매칭 개수만으로 정렬했다. 소금은
   전체 8,082개 레시피 중 2,268개(28.1%)에 들어가는 반면 감자는 416개(5.1%), 우유는 315개(3.9%)뿐 —
   소금 하나만 겹쳐도 감자·우유가 핵심인 레시피와 동일한 "매칭 1개" 취급을 받았다.
2. **rank_candidates의 크기 편향**: 부족한 재료 개수 오름차순으로 top-3를 골라, 재료 3개짜리
   `전복죽`(소금만 매칭, 나머지 2개 부족)이 재료 12개짜리 실제 관련 레시피보다 항상 유리했다.
3. **verify_relevance의 블라인드 판단**: LLM이 레시피 이름과 "부족한 재료" 목록만 보고 판단해서,
   애초에 "왜 이 후보가 뽑혔는지(매칭된 재료가 뭔지)"를 전혀 몰랐다.
4. **PostgREST 응답 상한 트렁케이션 (조사 중 새로 발견)**: `find_recipe_ingredient_matches`가 재료
   id 여러 개를 한 번에 조회할 때 PostgREST 기본 응답 상한(1,000행)에 걸렸다. 소금/감자/우유를 같이
   조회하면 실제로는 2,999행이 매칭되는데 응답은 1,000행에서 잘렸고, 잘린 1,000행이 전부 소금
   매칭이라 **감자·우유의 매칭 자체가 조회 단계에서 통째로 사라지고 있었다.** 순수 가중치 문제인 줄
   알았던 버그의 상당 부분이 사실 이 트렁케이션 때문이었다.

---

## 3. 평가 체계 — 무엇을, 왜 그 방식으로 쟀나

### 3.1 골든셋 (`scripts/eval/golden_set.py`)

재료 조합 15개를 4가지 성격으로 나눠 구성했다: 실제 버그 재현 케이스, 핵심재료가 아예 없는 극단
케이스(조미료만), 흔한 강조합, 희귀재료 단독 케이스. "정답 레시피"를 사람이 미리 라벨링하지 않은
이유는 라벨링 자체가 비용이 크고 주관적이라 — 대신 아래 결정론적 지표로 1차 스크리닝하고, 사람
라벨링(Langfuse UI에서 트레이스 보고 pass/fail)은 다음 단계 몫으로 남겨뒀다.

### 3.2 지표와 선택 이유

| 지표 | 정의 | 왜 이 지표인가 |
|---|---|---|
| `core_ingredient_hit_rate` | top-3 후보 중 매칭된 재료에 흔하지 않은(비-조미료) 재료가 하나라도 있는 비율 | 버그의 핵심 증상("조미료 하나만 겹쳐도 추천됨")을 직접 계측 |
| `zero_candidate_rate` | 재시도까지 다 거쳐도 후보가 0건인 비율 | 필터를 너무 엄격하게 만들어 커버리지를 해치지 않는지 확인 |
| `retry_rate` | broaden_search가 실제로 발동한 비율 | 초기 검색 조건(min_match=2)이 얼마나 자주 부족한지 |
| `avg_recipe_ingredient_count_top` | top-3 후보의 평균 총 재료 수 | rank_candidates의 "재료 적은 레시피" 쏠림 여부 확인 |

`GENERIC_DF_RATIO_THRESHOLD = 0.15`(재료가 코퍼스의 15% 이상 레시피에 들어가면 "흔한" 재료로 판정)는
소금(28.1%)과 감자(5.1%) 실측치 사이에서 잡은 **잠정값**이다. 사람 라벨링 데이터가 쌓이면 그 데이터로
재보정해야 한다 — 지금은 근거가 되는 라벨이 없어 확정값이 아니라는 점을 분명히 해둔다.

### 3.3 Langfuse 연동

기존엔 Langfuse가 `@observe()` 데코레이터로 트레이싱만 하고(패시브), 스코어링·데이터셋 기능은 전혀
안 쓰고 있었다. 이번에 추가한 것:

- `recommend-golden-set-v1` **Dataset**을 만들어 골든셋 15개 케이스를 등록 (`scripts/eval/run_baseline.py`).
- `langfuse.run_experiment()`로 매 실행을 **Dataset Run**으로 남겨, 알고리즘을 바꿀 때마다 이전 run과
  나란히 비교 가능하게 함. run URL: [베이스라인](https://jp.cloud.langfuse.com/project/cmrgi7x5o00frad0elhn9n7h8/datasets/cmrllbqfi0001ad0c7re4yu0q/runs/f9dc5864-1cff-4396-a124-144af7a5cc7d),
  [A-2/A-3 이후](https://jp.cloud.langfuse.com/project/cmrgi7x5o00frad0elhn9n7h8/datasets/cmrllbqfi0001ad0c7re4yu0q/runs/53c9df45-e7aa-4139-bd52-a440af74ed2f).
- 위 결정론적 지표들을 각 케이스의 trace에 Evaluation으로 붙여, 트레이스 옆에서 "왜 이렇게
  판단했는지"와 "그게 맞았는지"를 같이 볼 수 있게 함.

---

## 4. 개선 내역

### 4-1. 재료 문서빈도 가중치 + 핵심재료 하드필터 (커밋 `d6c8961`)

- `app/agent/services/ingredient_weight_service.py` 신설: 재료별 문서빈도(df) 비율 계산, `GENERIC_DF_RATIO_THRESHOLD` 상수를 한 곳에서 관리해 평가 스크립트와 실제 추천 로직이 같은 값을 쓰게 함.
- `app/data/repositories/recipe_repository.py`: `get_ingredient_document_frequency`/`get_total_recipe_count` 추가 (Redis 캐싱, 재료 id별 `count="exact"` 개별 조회).
- `app/agent/services/search_service.py`: 매칭 개수 대신 `Σ(1 - df_ratio)` 가중 점수로 정렬하고, 매칭된 재료 중 하나도 비-조미료 재료가 없으면 후보에서 제외.
- **부수적으로 발견한 PostgREST 트렁케이션 버그도 같이 수정**: `find_recipe_ingredient_matches`를 `.range()` 기반 완전 페이지네이션으로 변경 (§2-4 참고). 회귀 방지 테스트를 `tests/unit/data/test_recipe_repository.py`에 추가.

### 4-2. verify_relevance 판단 근거 노출 + 재시도 단계별 완화 (커밋 `dd84369`)

- `RecipeCandidate`에 `matched_ingredients` 추가, `rank_candidates`가 채움. `verify_relevance_prompt.py`가 겹치는/부족한 재료를 각각 보여주고 "조미료만 겹치면 실패로 판단하라"고 명시 — LLM이 더 이상 매칭 근거를 모른 채 판단하지 않음.
- `broaden_search.py` 재설계: 기존엔 min_match를 한 번 낮추자마자 바닥(1)에 닿고 search_limit도 캡(40)에 닿아서, 재시도 횟수를 늘려도 두 번째 재시도부터 완전히 무의미했다(같은 후보로 LLM만 다시 호출). **1단계(min_match 완화) → 2단계(min_match가 이미 바닥이면 search_limit을 크게 확장)**로 나누고 `MAX_SEARCH_RETRIES`를 1→2로 올려 두 단계가 실제로 서로 다른 효과를 내게 했다.
  - 이 재설계는 사용자 피드백으로 방향이 잡혔다: 처음엔 "횟수를 늘리는 게 의미가 없다"고 결론 내렸는데, "원래 재시도마다 파라미터를 바꿔가며 시도하려 했다"는 지적을 받고 축을 분리하는 쪽으로 다시 설계했다.

### 4-3. 대체재료 보유재료 우선순위 (커밋 `dd84369`)

- `classify_and_substitute.py`가 사용자 보유재료(`state.selected_ingredients` 중 해당 레시피에 쓰이는 것)를 `substitute_service.find()`에 넘기도록 수정.
- `substitute_prompt.py`에 2단계 우선순위 명시: (1) 보유재료 중 대체 가능한 게 있으면 최우선, (2) 없으면 집에서 직접 만들어야 하는 것보다 마트에서 바로 살 수 있는 형태 제안(예: 멸치육수 없으면 "멸치를 우려내라"가 아니라 "시판 멸치육수를 사라").
- **한계**: 음성 질의(voice Q&A) 흐름은 `VoiceQueryState`가 사용자 보유재료를 아예 추적하지 않아 이번 범위에서 제외됨. `FindSubstitutesInput`/`find_substitutes` 툴 시그니처에는 `owned_ingredients`를 옵션으로 추가해뒀지만, 음성 흐름에서 실제로 채워지는 값은 없다 — 별도 작업(VoiceQueryState 확장 + API 스키마 변경) 필요.

---

## 5. 결과 (골든셋 15케이스, 3단계 비교)

| 지표 | 베이스라인 (원본) | A-1 이후 | A-2+A-3 이후 |
|---|---|---|---|
| avg_core_ingredient_hit_rate | 0.6 | 1.0 | 1.0 |
| retry_rate | 0.667 | 0.467 | **0.4** |
| zero_candidate_rate | 0.0 | 0.067 | 0.067 |

- **`bug_salt_potato_milk` 케이스**: 베이스라인은 `core_ingredient_hit_rate=0.0`(top-3 전부 조미료성
  재료만 매칭)이었으나, 개선 후에는 재시도 없이(`retry_triggered=0`) 감자·우유 기반 레시피(매쉬포테이토,
  감자스프, 홍합차우더 등)가 바로 상위에 오른다.
- `zero_candidate_rate`의 유일한 1건(`single_generic_salt`, 재료가 소금 하나뿐인 극단 케이스)은
  핵심재료가 정말 하나도 없는 게 맞으므로 의도된 정상 동작이다.
- `seasoning_only_soy_sugar_garlic`(간장/설탕/마늘)은 A-1 이후에도 재시도가 발동했지만, A-2의
  판단-근거-노출 이후에는 재시도 없이 바로 통과한다 — LLM이 마늘의 매칭 근거를 볼 수 있게 되면서
  판단이 안정된 것으로 보인다.

전체 유닛/통합 테스트는 97개 전부 통과 상태를 유지했다 (`tests/unit/data/test_recipe_repository.py`,
`tests/unit/agent/test_verify_relevance_prompt.py` 등 회귀 테스트 신규 추가 포함).

---

## 6. 한계 및 후속 작업

- **`GENERIC_DF_RATIO_THRESHOLD=0.15`는 잠정값**이다. 사람이 Langfuse Dataset Run의 트레이스를 보고
  pass/fail 라벨을 채우면, 그 라벨과 df_ratio 분포를 대조해 임계값을 재보정해야 한다.
- **음성 질의 흐름의 대체재 보유재료 우선순위 미적용** (§4-3 한계 참고).
- **카테고리 표시 응답 구조**: 조사 결과 `IngredientRef{name, category}`가 이미 API 응답에 존재해
  FE가 카테고리별로 묶어 보여줄 수 있는 상태였음을 확인했다 (이번 브랜치에서 변경하지 않음). 다만
  이름 문자열 기준 join이라 동의어/표기 차이가 있으면 카테고리가 조용히 빠질 수 있는 fragility가
  남아있다 — ID 기반으로 바꾸는 건 별도 과제.
- **로컬 검증 환경 제약**: 이번 브랜치의 실행 검증은 로컬에 Redis가 없어(Docker Desktop 미기동)
  in-memory fake redis로 대체해 확인했다. 유닛 테스트는 정식 fake client로 작성했지만, 실제
  배포 환경(Redis 컨테이너 존재)에서의 캐싱 동작은 별도로 한 번 더 확인하는 게 안전하다.

---

## 7. 관련 커밋

| 커밋 | 내용 |
|---|---|
| `1e3ace6` | 골든셋 15케이스 + Langfuse Dataset/run_experiment 베이스라인 측정 하네스 |
| `d6c8961` | 재료 문서빈도 가중치 + 핵심재료 하드필터, PostgREST 트렁케이션 버그 수정 |
| `dd84369` | verify_relevance 판단 근거 노출, 재시도 단계별 완화, 대체재 보유재료 우선순위 |
